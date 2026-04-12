# @summary
# Graph-based query expansion for KG-augmented retrieval.
# Finds entities in queries via EntityMatcher, fans out through graph
# neighbours, and optionally includes community-derived terms (global retrieval).
# Exports: GraphQueryExpander
# Deps: src.knowledge_graph.backend, src.knowledge_graph.query.entity_matcher,
#       src.knowledge_graph.query.sanitizer, src.knowledge_graph.community.detector
# @end-summary
"""Graph-based query expansion for KG-augmented retrieval.

Finds entities in queries using :class:`EntityMatcher`, expands via graph
neighbours through :class:`GraphStorageBackend`, and returns related terms
to augment BM25 search.  Replaces the legacy ``GraphQueryExpander`` from
``src/core/knowledge_graph.py``.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Dict, List, Optional

if TYPE_CHECKING:
    from src.knowledge_graph.community import CommunityDetector

from src.knowledge_graph.backend import GraphStorageBackend
from src.knowledge_graph.query.entity_matcher import EntityMatcher
from src.knowledge_graph.query.sanitizer import QuerySanitizer

__all__ = ["GraphQueryExpander"]

logger = logging.getLogger("rag.knowledge_graph.query")


class GraphQueryExpander:
    """Find entities in a query and expand via graph neighbours.

    Uses :class:`EntityMatcher` for token-boundary-aware entity detection
    (replacing legacy substring matching) and :class:`QuerySanitizer` for
    normalisation and alias management.

    When a :class:`CommunityDetector` is provided and global retrieval is
    enabled, expansion includes community-derived terms after local terms.
    """

    def __init__(
        self,
        backend: GraphStorageBackend,
        max_depth: int = 1,
        max_terms: int = 3,
        community_detector: Optional["CommunityDetector"] = None,
        enable_global_retrieval: bool = False,
    ) -> None:
        """Initialise with a graph backend and optional community detector.

        Args:
            backend: Graph storage backend for neighbour queries.
            max_depth: Maximum hop depth for expansion.
            max_terms: Maximum number of expansion terms to return.
            community_detector: Optional detector for community-aware expansion.
                Must have is_ready==True for community terms to be included.
            enable_global_retrieval: When True and detector is ready, include
                community terms in expansion. Default False.
        """
        self._backend = backend
        self._max_depth = max_depth
        self._max_terms = max_terms
        self._community_detector = community_detector
        self._enable_global_retrieval = enable_global_retrieval
        self._global_retrieval_warned = False

        # Build matcher + sanitiser from backend index
        self._matcher: EntityMatcher
        self._sanitizer: QuerySanitizer
        self._build_from_backend()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def expand(self, query: str, depth: Optional[int] = None) -> List[str]:
        """Return related entity names to augment the search query.

        Traverses the graph outward (and inward) from matched entities
        up to *depth* hops.  Returns only terms not already in the query,
        capped at ``max_terms``.

        Args:
            query: User query text.
            depth: Override max depth (default: use init value).

        Returns:
            List of related entity names.
        """
        try:
            depth = depth if depth is not None else self._max_depth
        _t0 = time.monotonic()

            # Normalise query for matching
            normalized = self._sanitizer.normalize(query)

            # Tier 1: spaCy / substring match
            seed_entities = self._matcher.match(normalized)

            # Tier 2: LLM fallback (Phase 1b)
            if not seed_entities:
                seed_entities = self._matcher.match_with_llm_fallback(normalized)

            if not seed_entities:
                return []

            # Phase 3: Multi-hop for connects_to edges
            effective_depth = depth
            if effective_depth < 2:
                for entity in seed_entities:
                    out_edges = self._backend.get_outgoing_edges(entity)
                    if any(e.predicate == "connects_to" for e in out_edges):
                        effective_depth = max(effective_depth, 2)
                        logger.debug(
                            "Increased expansion depth to %d for connects_to edges on %s",
                            effective_depth, entity,
                        )
                        break

            # Expand via graph neighbours
            expanded: set[str] = set(seed_entities)

            for entity in seed_entities:
                # Forward + backward neighbours within depth hops
                neighbours = self._backend.query_neighbors(entity, depth=effective_depth)
                for neighbour in neighbours:
                    expanded.add(neighbour.name)

                # Explicit predecessors (entities that point at this one)
                predecessors = self._backend.get_predecessors(entity)
                for pred in predecessors:
                    expanded.add(pred.name)

            # Filter out terms already in the query
            query_lower = query.lower()
            local_terms = [e for e in expanded if e.lower() not in query_lower]

            # Phase 2: Community-aware global retrieval
            community_terms: List[str] = []
            if self._enable_global_retrieval and self._community_detector is not None:
                if self._community_detector.is_ready:
                    community_terms = self._expand_with_communities(
                        seed_entities, set(local_terms) | expanded
                    )
                    # Filter community terms not already in query
                    community_terms = [
                        t for t in community_terms if t.lower() not in query_lower
                    ]
                elif not self._global_retrieval_warned:
                    logger.warning(
                        "Global retrieval enabled but CommunityDetector is not ready "
                        "(detection or summarization incomplete). "
                        "Falling back to local-only expansion."
                    )
                    self._global_retrieval_warned = True

            # Merge: local terms first, community terms fill remaining slots
            result = local_terms[: self._max_terms]
            remaining = self._max_terms - len(result)
            if remaining > 0 and community_terms:
                result.extend(community_terms[:remaining])

            logger.debug(
                "GraphQueryExpander.expand: query=%r depth=%d terms=%d elapsed=%.3fs",
                query, effective_depth, len(result), time.monotonic() - _t0,
            )
            return result
        except Exception:
            logger.exception(
                "GraphQueryExpander.expand() failed for query %r; returning empty expansion",
                query,
            )
            return []

    def get_context_summary(
        self, entities: List[str], max_lines: int = 5
    ) -> str:
        """Build a short text summary of entity relationships.

        When community summaries are available, appends community context
        for matched entities.

        Args:
            entities: Entity names to summarise.
            max_lines: Maximum relationship lines to include.

        Returns:
            Semicolon-separated relationship summary.
        """
        lines: list[str] = []
        for entity in entities:
            edges = self._backend.get_outgoing_edges(entity)
            for edge in edges:
                lines.append(f"{edge.subject} {edge.predicate} {edge.object}")
                if len(lines) >= max_lines:
                    break
            if len(lines) >= max_lines:
                break

        # Append community context if available
        if (
            self._enable_global_retrieval
            and self._community_detector is not None
            and self._community_detector.is_ready
        ):
            seen_communities: set[int] = set()
            for entity in entities:
                cid = self._community_detector.get_community_for_entity(entity)
                if cid is not None and cid != -1 and cid not in seen_communities:
                    seen_communities.add(cid)
                    summary = self._community_detector.get_summary(cid)
                    if summary:
                        lines.append(f"[Community {cid}] {summary.summary_text}")

        return "; ".join(lines)

    def _expand_with_communities(
        self, seed_entities: List[str], existing_terms: set[str]
    ) -> List[str]:
        """Extract community-derived expansion terms.

        For each seed entity, looks up its community and retrieves other
        member names not already in existing_terms.

        Args:
            seed_entities: Entities matched in the query.
            existing_terms: Local expansion terms already collected.

        Returns:
            Community-derived terms, deduplicated.
        """
        assert self._community_detector is not None
        community_terms: list[str] = []
        seen_communities: set[int] = set()

        for entity in seed_entities:
            cid = self._community_detector.get_community_for_entity(entity)
            if cid is None or cid == -1 or cid in seen_communities:
                continue
            seen_communities.add(cid)

            summary = self._community_detector.get_summary(cid)
            if summary is None:
                continue

            # Add community members not already in expansion
            for member in summary.member_names:
                if member not in existing_terms and member not in community_terms:
                    community_terms.append(member)

        return community_terms

    def rebuild_matcher(self) -> None:
        """Rebuild entity matcher and sanitiser from current graph state.

        Call after the graph has been mutated (new documents ingested)
        so that the matcher picks up newly added entities and aliases.
        """
        self._build_from_backend()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _build_from_backend(self) -> None:
        """(Re)build matcher and sanitiser from the backend's entity index."""
        # get_all_node_names_and_aliases returns {lowercase_name_or_alias: canonical}
        name_index: Dict[str, str] = self._backend.get_all_node_names_and_aliases()

        # Entity names = unique canonical names
        entity_names = list(set(name_index.values()))

        # Alias index = non-canonical entries  (alias → canonical)
        alias_index: Dict[str, str] = {}
        canonical_lower = {n.lower() for n in entity_names}
        for key, canonical in name_index.items():
            if key not in canonical_lower:
                alias_index[key] = canonical

        self._matcher = EntityMatcher(entity_names, alias_index)
        self._sanitizer = QuerySanitizer(alias_index)
