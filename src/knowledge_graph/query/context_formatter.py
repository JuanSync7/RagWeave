# @summary
# Graph context formatter for LLM prompt injection.
# Transforms traversal results into structured text with token budget.
# Exports: GraphContextFormatter
# Deps: src.knowledge_graph.common (Entity, Triple),
#        src.knowledge_graph.query.schemas (PathResult, PathHop)
# @end-summary
"""Graph context formatter for LLM prompt injection.

Produces a structured text block from graph traversal results with
three sections: Entity Summaries, Relationship Triples, Path Narratives.
Enforces a configurable token budget with priority-based truncation.

Token budget is approximated using a fixed chars-per-token ratio
(``_CHARS_PER_TOKEN = 4``). This is intentionally simple — it avoids
a tokenizer dependency and stays fast at inference time. Actual token
counts may vary by ±20-30% depending on content.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from src.knowledge_graph.common.schemas import Entity, Triple
from src.knowledge_graph.query.schemas import PathResult

__all__ = ["GraphContextFormatter"]

_log = logging.getLogger("rag.knowledge_graph.query.context_formatter")

# Sentinel used inside _apply_token_budget to tag seed vs neighbour lines.
_SEED_TAG = "__seed__"
_NEIGHBOUR_TAG = "__neighbour__"


class GraphContextFormatter:
    """Formats graph traversal results into a structured text block for LLM prompts.

    The output is divided into three optional sections:

    1. **Entity Summaries** — canonical name, type, and description for each entity.
    2. **Relationship Triples** — edges grouped by predicate.
    3. **Path Narratives** — human-readable sentences for each matched traversal path.

    A configurable token budget is enforced via priority-based truncation:
    neighbour entity descriptions are dropped first, then relationship groups
    (smallest first), then path narratives, and seed entity descriptions last.
    Seed entity name+type lines are *never* dropped.

    Parameters
    ----------
    token_budget:
        Maximum token count for the entire output block. Set to ``0`` for
        unlimited (no truncation). Default: ``500``.
    marker_style:
        Section header style — ``"markdown"``, ``"xml"``, or ``"plain"``.
        Default: ``"markdown"``.
    description_fallback_k:
        When ``current_summary`` is absent, use the top-K ``raw_mentions``
        texts joined by space as the description fallback. Default: ``3``.
    max_path_hops:
        Paths with more hops than this limit are truncated and annotated with
        ``"[... N additional hops]"``. Default: ``5``.
    """

    _CHARS_PER_TOKEN: int = 4  # approximate token-to-char ratio

    def __init__(
        self,
        token_budget: int = 500,
        marker_style: str = "markdown",
        description_fallback_k: int = 3,
        max_path_hops: int = 5,
    ) -> None:
        self.token_budget = token_budget
        self.marker_style = marker_style
        self.description_fallback_k = description_fallback_k
        self.max_path_hops = max_path_hops

        self._section_markers = self._get_section_markers(marker_style)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def format(
        self,
        entities: List[Entity],
        triples: List[Triple],
        paths: List[PathResult],
        seed_entity_names: Optional[List[str]] = None,
    ) -> str:
        """Format graph traversal results into a structured text block.

        Parameters
        ----------
        entities:
            Entities to include in the Entity Summaries section.
        triples:
            Relationship triples to include in the Relationship Triples section.
        paths:
            Traversal paths to include in the Path Narratives section.
        seed_entity_names:
            Optional explicit list of seed (query anchor) entity names. Used
            by the token budget to determine which entities are high-priority.
            When omitted, all entities are treated as seed entities.

        Returns
        -------
        str
            A formatted, budget-bounded context block, or ``""`` if all
            sections are empty after truncation.
        """
        seed_names: set[str] = (
            set(seed_entity_names) if seed_entity_names is not None
            else {e.name for e in entities}
        )

        entity_lines = self._format_entity_summaries(entities, seed_names)
        triple_lines = self._format_relationship_triples(triples)
        path_lines = self._format_path_narratives(paths)

        sections: Dict[str, List[str]] = {
            "entities": entity_lines,
            "triples": triple_lines,
            "paths": path_lines,
        }

        if self.token_budget > 0:
            sections, truncation_note = self._apply_token_budget(sections)
        else:
            # No budget enforcement — still strip internal priority tags.
            sections = {
                "entities": [_strip_tag(l) for l in entity_lines],
                "triples": triple_lines,
                "paths": path_lines,
            }
            truncation_note = ""

        # Check whether anything survived truncation.
        if not any(sections.values()):
            return ""

        return self._assemble(sections, truncation_note)

    # ------------------------------------------------------------------
    # Section formatters
    # ------------------------------------------------------------------

    def _format_entity_summaries(
        self, entities: List[Entity], seed_names: set[str]
    ) -> List[str]:
        """Build entity summary lines, tagged for budget prioritisation.

        Each line has the form::

            - **name** [type]: description (also: alias1, alias2)

        Internal tags (``__seed__``/``__neighbour__``) are embedded as a
        line prefix so ``_apply_token_budget`` can distinguish priorities.
        They are stripped before final assembly.

        Parameters
        ----------
        entities:
            Entities to format.
        seed_names:
            Set of names that should be treated as seed (high-priority) entities.

        Returns
        -------
        List[str]
            Tagged formatted lines, one per entity.
        """
        lines: List[str] = []
        for entity in entities:
            description = self._entity_description(entity)
            line = f"- **{entity.name}** [{entity.type}]: {description}"
            if entity.aliases:
                alias_str = ", ".join(entity.aliases)
                line += f" (also: {alias_str})"
            tag = _SEED_TAG if entity.name in seed_names else _NEIGHBOUR_TAG
            lines.append(f"{tag}{line}")
        return lines

    def _format_relationship_triples(self, triples: List[Triple]) -> List[str]:
        """Build relationship triple lines grouped by predicate.

        Each group has a subheading followed by individual triple lines::

            **predicate_name**
            - subject --[predicate_name]--> object

        Parameters
        ----------
        triples:
            Triples to format.

        Returns
        -------
        List[str]
            Formatted lines (subheading + members) for all predicate groups.
        """
        if not triples:
            return []

        groups: Dict[str, List[Triple]] = defaultdict(list)
        for triple in triples:
            groups[triple.predicate].append(triple)

        lines: List[str] = []
        for predicate, group_triples in groups.items():
            lines.append(f"**{predicate}**")
            for triple in group_triples:
                lines.append(
                    f"- {triple.subject} --[{triple.predicate}]--> {triple.object}"
                )
        return lines

    def _format_path_narratives(self, paths: List[PathResult]) -> List[str]:
        """Build a natural-language narrative sentence for each traversal path.

        Examples
        --------
        1-hop:  ``"A was fixed by B"``
        2-hop:  ``"A was fixed by B, which is specified by C"``
        N-hop:  chain with ``, which ...`` connectors, truncated at
                ``max_path_hops``.

        Underscores in predicate names are replaced with spaces.

        Parameters
        ----------
        paths:
            Traversal paths to narrate.

        Returns
        -------
        List[str]
            One narrative string per path.
        """
        if not paths:
            return []

        narratives: List[str] = []
        for path in paths:
            hops = path.hops
            if not hops:
                continue

            truncated = False
            extra_hops = 0
            if len(hops) > self.max_path_hops:
                extra_hops = len(hops) - self.max_path_hops
                hops = hops[: self.max_path_hops]
                truncated = True

            # Build the narrative chain.
            first_hop = hops[0]
            predicate_str = first_hop.edge_type.replace("_", " ")
            narrative = f"{first_hop.from_entity} {predicate_str} {first_hop.to_entity}"

            for hop in hops[1:]:
                pred = hop.edge_type.replace("_", " ")
                narrative += f", which {pred} {hop.to_entity}"

            if truncated:
                narrative += f" [... {extra_hops} additional hops]"

            narratives.append(narrative)

        return narratives

    # ------------------------------------------------------------------
    # Token budget
    # ------------------------------------------------------------------

    def _apply_token_budget(
        self, sections: Dict[str, List[str]]
    ) -> Tuple[Dict[str, List[str]], str]:
        """Truncate sections to fit within ``token_budget`` characters.

        Priority-based truncation order (lowest priority dropped first):

        1. Neighbour entity descriptions (non-seed entities).
        2. Relationship triple groups — smallest group removed first.
        3. Path narrative lines — trailing paths removed first.
        4. Seed entity description text (name+type stub preserved).

        Seed entity name+type lines are **never** dropped.

        Parameters
        ----------
        sections:
            Mapping of section key to list of formatted lines (may include
            ``__seed__``/``__neighbour__`` tags on entity lines).

        Returns
        -------
        Tuple[Dict[str, List[str]], str]
            Truncated sections and an optional annotation string describing
            any truncation that was applied (empty string if none).
        """
        char_budget = self.token_budget * self._CHARS_PER_TOKEN
        truncation_notes: List[str] = []

        entity_lines: List[str] = list(sections.get("entities", []))
        triple_lines: List[str] = list(sections.get("triples", []))
        path_lines: List[str] = list(sections.get("paths", []))

        def _total_chars() -> int:
            return sum(len(l) for l in entity_lines + triple_lines + path_lines)

        # ---- Phase 1: Drop neighbour entity descriptions ----
        # A neighbour line starts with _NEIGHBOUR_TAG — drop these first.
        i = len(entity_lines) - 1
        while _total_chars() > char_budget and i >= 0:
            if entity_lines[i].startswith(_NEIGHBOUR_TAG):
                entity_lines.pop(i)
                truncation_notes.append("neighbour entity description(s) truncated")
            i -= 1

        # ---- Phase 2: Drop relationship triple groups (smallest first) ----
        # Rebuild group structure to identify boundaries.
        if _total_chars() > char_budget and triple_lines:
            groups = _parse_triple_groups(triple_lines)
            # Sort by group size ascending (smallest first = cheapest to remove)
            groups.sort(key=lambda g: len(g[1]))
            while _total_chars() > char_budget and groups:
                _heading, _members = groups.pop(0)
                removed_count = 1 + len(_members)  # heading + member lines
                # Find and remove from triple_lines (heading line is the marker)
                idx = next(
                    (j for j, l in enumerate(triple_lines) if l == _heading), None
                )
                if idx is not None:
                    del triple_lines[idx: idx + removed_count]
            if not triple_lines:
                truncation_notes.append("all relationship triples truncated")
            else:
                truncation_notes.append("some relationship triple groups truncated")

        # ---- Phase 3: Drop path narratives (trailing first) ----
        while _total_chars() > char_budget and path_lines:
            path_lines.pop()
            truncation_notes.append("path narrative(s) truncated")

        # ---- Phase 4: Truncate seed entity descriptions ----
        # Keep the name+type stub; drop the description text after the colon.
        i = len(entity_lines) - 1
        while _total_chars() > char_budget and i >= 0:
            line = entity_lines[i]
            tag = _SEED_TAG if line.startswith(_SEED_TAG) else (
                _NEIGHBOUR_TAG if line.startswith(_NEIGHBOUR_TAG) else ""
            )
            if tag == _SEED_TAG:
                raw = line[len(_SEED_TAG):]
                # Truncate description text; preserve "- **name** [type]" stub.
                colon_idx = raw.find("]:")
                if colon_idx != -1:
                    stub = raw[: colon_idx + 1]  # up to and including "]"
                    entity_lines[i] = f"{_SEED_TAG}{stub}"
                    truncation_notes.append("seed entity description(s) truncated")
            i -= 1

        # Strip internal tags from entity lines.
        cleaned_entities = [_strip_tag(l) for l in entity_lines]

        result = {
            "entities": cleaned_entities,
            "triples": triple_lines,
            "paths": path_lines,
        }

        # Deduplicate truncation notes, preserve order.
        seen: set[str] = set()
        unique_notes: List[str] = []
        for note in truncation_notes:
            if note not in seen:
                seen.add(note)
                unique_notes.append(note)

        annotation = f"[Context truncated: {'; '.join(unique_notes)}]" if unique_notes else ""
        return result, annotation

    # ------------------------------------------------------------------
    # Marker styles
    # ------------------------------------------------------------------

    def _get_section_markers(self, marker_style: str) -> Dict[str, str]:
        """Return section header/footer strings for the requested *marker_style*.

        Supported styles:

        * ``"markdown"`` — ATX headings (``##``, ``###``).
        * ``"xml"`` — XML-style tags with opening and closing counterparts.
        * ``"plain"`` — plain ASCII rulers.

        Parameters
        ----------
        marker_style:
            One of ``"markdown"``, ``"xml"``, ``"plain"``.

        Returns
        -------
        Dict[str, str]
            Keys: ``header``, ``entities_open``, ``entities_close``,
            ``triples_open``, ``triples_close``, ``paths_open``,
            ``paths_close``, ``footer``.

        Raises
        ------
        ValueError
            If *marker_style* is not one of the three supported values.
        """
        if marker_style == "markdown":
            return {
                "header": "## Graph Context",
                "entities_open": "### Entities",
                "entities_close": "",
                "triples_open": "### Relationships",
                "triples_close": "",
                "paths_open": "### Paths",
                "paths_close": "",
                "footer": "",
            }
        if marker_style == "xml":
            return {
                "header": "<graph_context>",
                "entities_open": "<entities>",
                "entities_close": "</entities>",
                "triples_open": "<relationships>",
                "triples_close": "</relationships>",
                "paths_open": "<paths>",
                "paths_close": "</paths>",
                "footer": "</graph_context>",
            }
        if marker_style == "plain":
            return {
                "header": "=== GRAPH CONTEXT ===",
                "entities_open": "--- ENTITIES ---",
                "entities_close": "",
                "triples_open": "--- RELATIONSHIPS ---",
                "triples_close": "",
                "paths_open": "--- PATHS ---",
                "paths_close": "",
                "footer": "",
            }
        raise ValueError(
            f"Unknown marker_style '{marker_style}'. "
            "Expected one of: 'markdown', 'xml', 'plain'."
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _entity_description(self, entity: Entity) -> str:
        """Return the best available description for *entity*.

        Priority:

        1. ``current_summary`` — non-empty LLM-generated summary.
        2. Top-K ``raw_mentions`` texts joined by a single space.
        3. ``"[No description available]"`` fallback.
        """
        if entity.current_summary:
            return entity.current_summary

        if entity.raw_mentions:
            mentions = entity.raw_mentions[: self.description_fallback_k]
            return " ".join(m.text for m in mentions)

        return "[No description available]"

    def _assemble(self, sections: Dict[str, List[str]], truncation_note: str) -> str:
        """Join non-empty sections with appropriate markers.

        Parameters
        ----------
        sections:
            Mapping of section key to cleaned (tag-free) lines.
        truncation_note:
            Annotation string from ``_apply_token_budget``, or ``""``.

        Returns
        -------
        str
            The fully assembled context block.
        """
        m = self._section_markers
        parts: List[str] = []

        if m["header"]:
            parts.append(m["header"])

        # Entities section
        entity_lines = sections.get("entities", [])
        if entity_lines:
            if m["entities_open"]:
                parts.append(m["entities_open"])
            parts.extend(entity_lines)
            if m["entities_close"]:
                parts.append(m["entities_close"])

        # Relationships section
        triple_lines = sections.get("triples", [])
        if triple_lines:
            if m["triples_open"]:
                parts.append(m["triples_open"])
            parts.extend(triple_lines)
            if m["triples_close"]:
                parts.append(m["triples_close"])

        # Paths section
        path_lines = sections.get("paths", [])
        if path_lines:
            if m["paths_open"]:
                parts.append(m["paths_open"])
            parts.extend(path_lines)
            if m["paths_close"]:
                parts.append(m["paths_close"])

        if truncation_note:
            parts.append(truncation_note)

        if m["footer"]:
            parts.append(m["footer"])

        return "\n".join(parts)


# ---------------------------------------------------------------------------
# Module-level helpers (not part of the public API)
# ---------------------------------------------------------------------------


def _strip_tag(line: str) -> str:
    """Remove internal priority tag prefix from an entity line."""
    if line.startswith(_SEED_TAG):
        return line[len(_SEED_TAG):]
    if line.startswith(_NEIGHBOUR_TAG):
        return line[len(_NEIGHBOUR_TAG):]
    return line


def _parse_triple_groups(
    triple_lines: List[str],
) -> List[Tuple[str, List[str]]]:
    """Parse flat triple_lines back into (heading, [member, ...]) tuples.

    A heading line is one that does NOT start with ``"- "`` (it is the
    bold predicate subheading produced by ``_format_relationship_triples``).

    Parameters
    ----------
    triple_lines:
        Lines as produced by ``_format_relationship_triples``.

    Returns
    -------
    List[Tuple[str, List[str]]]
        List of ``(heading_line, [member_lines])`` pairs, in original order.
    """
    groups: List[Tuple[str, List[str]]] = []
    current_heading: Optional[str] = None
    current_members: List[str] = []

    for line in triple_lines:
        if not line.startswith("- "):
            # New heading — save previous group if any.
            if current_heading is not None:
                groups.append((current_heading, current_members))
            current_heading = line
            current_members = []
        else:
            current_members.append(line)

    if current_heading is not None:
        groups.append((current_heading, current_members))

    return groups
