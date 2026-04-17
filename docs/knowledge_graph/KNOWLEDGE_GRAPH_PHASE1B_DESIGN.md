# KG Phase 1b Design Addendum — Task Decomposition and Code Contracts

**Date:** 2026-04-08
**Status:** Draft
**Parent:** `KNOWLEDGE_GRAPH_SPEC.md` Appendix C (REQ-KG-1b-100 through REQ-KG-1b-305)
**Companion:** `2026-04-08-kg-phase1b-sketch.md` (approved design sketch)

---

## Overview

This document decomposes Phase 1b into five implementation tasks with full code contracts (typed Python signatures), dependency lists, files modified, requirement traceability, and LOC estimates. Each task is independently testable against the acceptance criteria defined in the spec.

**Total estimated LOC:** ~900 (net new + replacement of stubs).

---

## T1b-1: LLM Extractor Implementation

**Estimated LOC:** ~300
**File:** `src/knowledge_graph/extraction/llm_extractor.py` (replace stub)

### Summary

Replace the `NotImplementedError` stub with a schema-guided, single-prompt LLM extraction pipeline. Uses `LLMProvider.json_completion()` for structured JSON output, validates results against `SchemaDefinition`, handles retries and rate limits gracefully.

### Code Contracts

```python
# src/knowledge_graph/extraction/llm_extractor.py

from __future__ import annotations

import json
import logging
import time
from typing import Any, Dict, List, Optional

from src.knowledge_graph.common.schemas import (
    Entity,
    EntityDescription,
    ExtractionResult,
    Triple,
)
from src.knowledge_graph.common.types import KGConfig, SchemaDefinition

# Type alias for the LLM provider (imported at runtime to avoid circular deps)
# from src.platform.llm.provider import LLMProvider, get_llm_provider
# from src.platform.llm.schemas import LLMResponse

logger: logging.Logger

# Module-level constants
DEFAULT_PROMPT_TEMPLATE: str  # Embedded default template with {schema_types},
                              # {schema_edges}, {extraction_hints}, {chunk_text}
SYSTEM_MESSAGE: str           # Role definition + JSON output format spec
REQUIRED_TEMPLATE_VARS: frozenset  # {"schema_types", "schema_edges",
                                   #  "extraction_hints", "chunk_text"}


class LLMEntityExtractor:
    """Schema-guided LLM entity/relation extractor.

    Uses a single LLM call per chunk with the YAML schema injected as
    prompt context. Returns ExtractionResult compatible with the merge node.
    """

    extractor_name: str = "llm"

    def __init__(
        self,
        schema: SchemaDefinition,
        config: KGConfig,
        llm_provider: Optional[Any] = None,  # Optional[LLMProvider]
    ) -> None:
        """Initialise with schema, config, and optional LLM provider.

        Args:
            schema: Parsed YAML schema for type validation and prompt rendering.
            config: KG runtime configuration.
            llm_provider: Optional LLMProvider instance. Falls back to
                get_llm_provider() singleton when None.

        Raises:
            ValueError: If the prompt template is missing required variables.
        """
        ...

    def extract(self, text: str, source: str = "") -> ExtractionResult:
        """Extract entities, triples, and descriptions from a text chunk.

        Args:
            text: Document chunk text.
            source: Document path or URI for provenance.

        Returns:
            ExtractionResult with entities, triples, and descriptions.
            Returns empty result on persistent LLM failure (no exception).
        """
        ...

    # -- Internal methods --

    def _build_prompt(self, text: str) -> List[Dict[str, str]]:
        """Render the prompt template with schema context and chunk text.

        Args:
            text: The chunk text to embed in the prompt.

        Returns:
            OpenAI-style messages list (system + user).
        """
        ...

    def _render_schema_types(self) -> str:
        """Render active node types as a compact string for prompt injection.

        Filters by runtime_phase via SchemaDefinition.active_node_types().
        Includes name, description, and extraction_hints for each type.

        Returns:
            Rendered schema types block.
        """
        ...

    def _render_schema_edges(self) -> str:
        """Render active edge types with descriptions and constraints.

        Returns:
            Rendered schema edges block.
        """
        ...

    def _render_extraction_hints(self) -> str:
        """Render concatenated extraction hints from active node types.

        Returns:
            Hints summary block.
        """
        ...

    def _call_llm(self, messages: List[Dict[str, str]]) -> str:
        """Call LLMProvider.json_completion() with rate-limit retry.

        Implements exponential backoff (1s, 2s, 4s) for HTTP 429 errors,
        up to 3 rate-limit retries. Returns raw content string.

        Args:
            messages: Chat messages for the LLM call.

        Returns:
            Raw JSON string from the LLM response.

        Raises:
            Exception: Re-raises non-rate-limit errors after logging.
        """
        ...

    def _parse_response(self, json_str: str) -> Dict[str, Any]:
        """Parse LLM JSON response into a dict.

        Args:
            json_str: Raw JSON string from LLM.

        Returns:
            Parsed dict with 'entities' and 'triples' keys.

        Raises:
            json.JSONDecodeError: On malformed JSON.
        """
        ...

    def _validate_and_build(
        self, raw: Dict[str, Any], source: str
    ) -> ExtractionResult:
        """Validate extracted data against schema and build ExtractionResult.

        - Entities with invalid types: reclassify to "concept", log warning.
        - Triples with invalid predicates: drop, log warning.
        - Sets extractor_source="llm" on all Entity and Triple objects.
        - Builds EntityDescription entries from entity description fields.

        Args:
            raw: Parsed LLM output dict.
            source: Document source for provenance.

        Returns:
            Validated ExtractionResult.
        """
        ...

    def _load_template(self) -> str:
        """Load prompt template from config path or use default.

        Returns:
            Template string with substitution variables.

        Raises:
            ValueError: If template is missing required variables.
        """
        ...
```

### Dependencies

| Dependency | Import Path | Kind |
|---|---|---|
| `LLMProvider` | `src.platform.llm.provider` | Runtime (lazy import) |
| `get_llm_provider` | `src.platform.llm.provider` | Runtime (lazy import) |
| `LLMResponse` | `src.platform.llm.schemas` | Type reference |
| `SchemaDefinition` | `src.knowledge_graph.common.types` | Constructor param |
| `KGConfig` | `src.knowledge_graph.common.types` | Constructor param |
| `ExtractionResult`, `Entity`, `Triple`, `EntityDescription` | `src.knowledge_graph.common.schemas` | Return/build types |

### Files Modified

| File | Change |
|---|---|
| `src/knowledge_graph/extraction/llm_extractor.py` | Full rewrite (replace stub) |

### REQ Coverage

| REQ | Description | Coverage |
|---|---|---|
| REQ-KG-1b-100 | LiteLLM via LLMProvider, constructor injection | `__init__` signature, `_call_llm` |
| REQ-KG-1b-101 | Schema types injected into prompt | `_build_prompt`, `_render_schema_types`, `_render_schema_edges`, `_render_extraction_hints` |
| REQ-KG-1b-102 | JSON structured output mode | `_call_llm` uses `json_completion()` |
| REQ-KG-1b-103 | Schema validation of entities/triples | `_validate_and_build` |
| REQ-KG-1b-104 | Retry on malformed JSON, empty on double-failure | `extract` retry logic |
| REQ-KG-1b-105 | Entity descriptions extraction | `_validate_and_build` builds `EntityDescription` |
| REQ-KG-1b-106 | Configurable prompt template | `_load_template`, `KGConfig.llm_extraction_prompt_template` |
| REQ-KG-1b-107 | `extractor_source="llm"` on all objects | `_validate_and_build` |
| REQ-KG-1b-108 | Rate-limit backoff (1s, 2s, 4s, max 3 retries) | `_call_llm` |
| REQ-KG-1b-109 | Extraction statistics logging | End of `extract` method |

---

## T1b-2: SV Parser Extractor Implementation

**Estimated LOC:** ~400
**File:** `src/knowledge_graph/extraction/parser_extractor.py` (replace stub)

### Summary

Replace the `NotImplementedError` stub with a tree-sitter-verilog structural extractor. Walks the concrete syntax tree to extract modules, ports, parameters, instances, signals, interfaces, and packages, plus structural relationships (`contains`, `instantiates`, `connects_to`, `parameterized_by`, `depends_on`).

### Code Contracts

```python
# src/knowledge_graph/extraction/parser_extractor.py

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from src.knowledge_graph.common.schemas import (
    Entity,
    ExtractionResult,
    Triple,
)
from src.knowledge_graph.common.types import KGConfig, SchemaDefinition

logger: logging.Logger

# Module-level constants
VALID_EXTENSIONS: frozenset  # {".sv", ".v", ".svh"}

AST_TO_SCHEMA_MAP: Dict[str, str]  # tree-sitter node type -> YAML schema type
# {
#     "module_declaration": "RTL_Module",
#     "port_declaration": "Port",
#     "ansi_port_declaration": "Port",
#     "parameter_declaration": "Parameter",
#     "local_parameter_declaration": "Parameter",
#     "module_instantiation": "Instance",
#     "net_declaration": "Signal",
#     "data_declaration": "Signal",
#     "interface_declaration": "Interface",
#     "package_declaration": "Package",
#     # SHOULD-level (REQ-KG-1b-207):
#     "generate_region": "Generate",
#     "task_declaration": "Task_Function",
#     "function_declaration": "Task_Function",
# }

KNOWN_UNSUPPORTED: List[str]  # Constructs we intentionally skip
# ["bind", "cross_module_reference", "uvm_macro", ...]


class SVParserExtractor:
    """Deterministic structural extractor for SystemVerilog using tree-sitter.

    Extracts entities and structural relationships from the parsed CST.
    All results are tagged with extractor_source="sv_parser".
    """

    extractor_name: str = "sv_parser"

    def __init__(
        self,
        schema: SchemaDefinition,
        config: KGConfig,
    ) -> None:
        """Initialise with schema and config. Creates the tree-sitter parser.

        Args:
            schema: Parsed YAML schema for type validation.
            config: KG runtime configuration.

        Raises:
            ImportError: If tree-sitter or tree-sitter-verilog is not installed.
        """
        ...

    def extract(self, text: str, source: str = "") -> ExtractionResult:
        """Extract structural entities and relations from SV source text.

        Args:
            text: SystemVerilog source code as a string.
            source: File path or URI for provenance.

        Returns:
            ExtractionResult with entities and triples. Partial results
            on parse errors (ERROR subtrees are skipped).
        """
        ...

    def extract_file(self, file_path: str) -> ExtractionResult:
        """Extract from a SystemVerilog file on disk.

        Args:
            file_path: Path to a .sv, .v, or .svh file.

        Returns:
            ExtractionResult. Empty result for non-SV extensions.

        Raises:
            FileNotFoundError: If file_path does not exist.
        """
        ...

    # -- Internal tree-walking methods --

    def _parse_tree(self, text: str) -> Any:
        """Parse text into a tree-sitter CST.

        Args:
            text: Source code bytes (encoded to UTF-8 internally).

        Returns:
            tree-sitter Tree object.
        """
        ...

    def _walk_tree(
        self, node: Any, source: str
    ) -> Tuple[List[Entity], List[Triple]]:
        """Recursively walk the CST and extract entities and triples.

        Skips ERROR and MISSING nodes with a logged warning.
        Dispatches to type-specific extraction methods based on
        AST_TO_SCHEMA_MAP membership.

        Args:
            node: tree-sitter Node to process.
            source: File path for provenance.

        Returns:
            Tuple of (entities, triples) collected from this subtree.
        """
        ...

    def _extract_module(
        self, node: Any, source: str
    ) -> Tuple[List[Entity], List[Triple]]:
        """Extract a module declaration and its children.

        Produces:
        - RTL_Module entity for the module itself.
        - Port, Parameter, Signal, Instance entities from children.
        - 'contains' triples from module to each child entity.
        - 'instantiates' triples from Instance entities to their module types.

        Args:
            node: module_declaration tree-sitter node.
            source: File path for provenance.

        Returns:
            Tuple of (entities, triples).
        """
        ...

    def _extract_ports(
        self, node: Any, module_name: str, source: str
    ) -> Tuple[List[Entity], List[Triple]]:
        """Extract port declarations from a module's port list.

        Extracts direction (input/output/inout) and width from range nodes.

        Args:
            node: Module node whose children are scanned for ports.
            module_name: Parent module name for 'contains' triples.
            source: File path for provenance.

        Returns:
            Tuple of (port entities, contains triples).
        """
        ...

    def _extract_instances(
        self, node: Any, module_name: str, source: str
    ) -> Tuple[List[Entity], List[Triple]]:
        """Extract module instantiations.

        Produces Instance entities, 'contains' triples (parent -> instance),
        'instantiates' triples (instance -> module type), and 'connects_to'
        triples from port connections.

        Args:
            node: Module body node to scan for instantiations.
            module_name: Parent module name.
            source: File path for provenance.

        Returns:
            Tuple of (entities, triples).
        """
        ...

    def _extract_parameters(
        self, node: Any, module_name: str, source: str
    ) -> Tuple[List[Entity], List[Triple]]:
        """Extract parameter and localparam declarations.

        Args:
            node: Module node to scan.
            module_name: Parent module name for 'contains' triples.
            source: File path for provenance.

        Returns:
            Tuple of (parameter entities, contains triples).
        """
        ...

    def _extract_signals(
        self, node: Any, module_name: str, source: str
    ) -> Tuple[List[Entity], List[Triple]]:
        """Extract net/data declarations (wire, reg, logic).

        Args:
            node: Module body node to scan.
            module_name: Parent module name for 'contains' triples.
            source: File path for provenance.

        Returns:
            Tuple of (signal entities, contains triples).
        """
        ...

    def _extract_interface(
        self, node: Any, source: str
    ) -> Tuple[List[Entity], List[Triple]]:
        """Extract an interface declaration.

        Args:
            node: interface_declaration tree-sitter node.
            source: File path for provenance.

        Returns:
            Tuple of (entities, triples).
        """
        ...

    def _extract_package(
        self, node: Any, source: str
    ) -> Tuple[List[Entity], List[Triple]]:
        """Extract a package declaration.

        Args:
            node: package_declaration tree-sitter node.
            source: File path for provenance.

        Returns:
            Tuple of (entities, triples).
        """
        ...

    def _extract_node_name(self, node: Any) -> Optional[str]:
        """Extract the identifier name from a declaration node.

        Looks for the first simple_identifier or other name-bearing child.

        Args:
            node: Any declaration node.

        Returns:
            Name string, or None if no identifier found.
        """
        ...

    def _make_entity(
        self, name: str, entity_type: str, source: str
    ) -> Entity:
        """Create an Entity with sv_parser attribution.

        Args:
            name: Entity canonical name.
            entity_type: YAML schema type name.
            source: File path for provenance.

        Returns:
            Entity with extractor_source=["sv_parser"] and sources=[source].
        """
        ...

    def _make_triple(
        self, subject: str, predicate: str, obj: str, source: str
    ) -> Triple:
        """Create a Triple with sv_parser attribution.

        Args:
            subject: Source entity name.
            predicate: Edge type label.
            obj: Target entity name.
            source: File path for provenance.

        Returns:
            Triple with extractor_source="sv_parser".
        """
        ...
```

### Dependencies

| Dependency | Import Path | Kind |
|---|---|---|
| `tree_sitter` | `tree_sitter` | External package (>=0.22) |
| `tree_sitter_verilog` | `tree_sitter_verilog` | External package (grammar) |
| `SchemaDefinition` | `src.knowledge_graph.common.types` | Constructor param |
| `KGConfig` | `src.knowledge_graph.common.types` | Constructor param |
| `ExtractionResult`, `Entity`, `Triple` | `src.knowledge_graph.common.schemas` | Return/build types |

### Files Modified

| File | Change |
|---|---|
| `src/knowledge_graph/extraction/parser_extractor.py` | Full rewrite (replace stub) |

### REQ Coverage

| REQ | Description | Coverage |
|---|---|---|
| REQ-KG-1b-200 | tree-sitter >=0.22, parser reuse, extension validation | `__init__`, `extract_file` extension check |
| REQ-KG-1b-201 | 7 mandatory entity types extraction | `_extract_module`, `_extract_ports`, `_extract_parameters`, `_extract_instances`, `_extract_signals`, `_extract_interface`, `_extract_package` |
| REQ-KG-1b-202 | Structural relationships | `contains`, `instantiates`, `connects_to`, `parameterized_by`, `depends_on` triples in extraction methods |
| REQ-KG-1b-203 | Explicit AST-to-schema mapping table | `AST_TO_SCHEMA_MAP` constant |
| REQ-KG-1b-204 | ERROR/MISSING node handling, partial results | `_walk_tree` skip logic |
| REQ-KG-1b-205 | `extract_file()` method | `extract_file` with extension check and delegation |
| REQ-KG-1b-206 | `extractor_source="sv_parser"` | `_make_entity`, `_make_triple` |
| REQ-KG-1b-207 | Generate, Task_Function extraction (SHOULD) | `AST_TO_SCHEMA_MAP` entries, dispatch in `_walk_tree` |
| REQ-KG-1b-208 | Clock domain crossing detection (SHOULD) | Deferred -- noted in `KNOWN_UNSUPPORTED` as stretch goal |
| REQ-KG-1b-209 | File path in Entity.sources | `_make_entity` sets `sources=[source]` |

**Note on REQ-KG-1b-208 (CDC detection):** This SHOULD-level requirement is complex and cross-cutting (requires correlating signals across multiple `always` blocks). It is listed in `KNOWN_UNSUPPORTED` for T1b-2 and may be addressed as a follow-up if time permits. The other SHOULD requirements (REQ-KG-1b-207) are included in the primary implementation.

---

## T1b-3: LLM Query Fallback

**Estimated LOC:** ~100
**File:** `src/knowledge_graph/query/entity_matcher.py` (modify existing class)

### Summary

Replace the stub `match_with_llm_fallback()` with an actual LLM call. When spaCy/substring matching returns nothing, the query has >= 3 tokens, and the feature is enabled, send the query + entity list (grouped by type) to the LLM for semantic entity resolution. Validate returned names against the known entity set.

### Code Contracts

```python
# src/knowledge_graph/query/entity_matcher.py
# Modifications to the existing EntityMatcher class.

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Set, Tuple

# New constructor signature (backward-compatible — new params have defaults):

class EntityMatcher:

    def __init__(
        self,
        entity_names: List[str],
        aliases: Dict[str, str],
        entity_types: Optional[Dict[str, str]] = None,  # NEW: name -> type mapping
        config: Optional[KGConfig] = None,               # NEW: for fallback settings
        llm_provider: Optional[Any] = None,               # NEW: optional LLM provider
    ) -> None:
        """Initialise with known entity names, aliases, and optional type info.

        Args:
            entity_names: All canonical entity names from the graph.
            aliases: Mapping of alias -> canonical name.
            entity_types: Optional mapping of entity name -> schema type
                (e.g., {"top": "RTL_Module", "clk": "Port"}).
                Required for LLM fallback prompt grouping.
            config: KG config for fallback settings. When None, fallback is disabled.
            llm_provider: Optional LLMProvider for fallback calls.
                Falls back to get_llm_provider() when None and fallback is enabled.
        """
        ...

    def match_with_llm_fallback(self, query: str) -> List[str]:
        """Match with LLM fallback when the fast tier finds nothing.

        Flow:
        1. Run spaCy/substring match.
        2. If results found, return immediately (no LLM call).
        3. If query has < 3 tokens, return empty (REQ-KG-1b-305).
        4. If enable_llm_query_fallback is False, return empty.
        5. Call _llm_fallback(query).

        Args:
            query: Raw query string.

        Returns:
            Deduplicated list of canonical entity names.
        """
        ...

    # -- New private methods --

    def _llm_fallback(self, query: str) -> List[str]:
        """Invoke the LLM to resolve entity references in the query.

        Sends the query + entity names grouped by type to the LLM.
        Validates returned names against the known entity set.
        Returns empty list on any error (timeout, parse, provider).

        Args:
            query: User query string.

        Returns:
            List of canonical entity names identified by the LLM.
        """
        ...

    def _build_entity_list_prompt(self) -> str:
        """Format entity names grouped by type for the LLM prompt.

        Format: "RTL_Module: top, sub_mod, axi_arb\\nPort: clk, data, ..."
        Truncates to llm_fallback_token_budget if entity list is too large,
        prioritizing entities by mention count.

        Returns:
            Formatted entity list string.
        """
        ...

    def _build_fallback_messages(
        self, query: str, entity_list: str
    ) -> List[Dict[str, str]]:
        """Build the system + user messages for the LLM fallback call.

        System: Entity resolver role definition.
        User: Query text + entity list.

        Args:
            query: User query.
            entity_list: Formatted entity list from _build_entity_list_prompt().

        Returns:
            OpenAI-style messages list.
        """
        ...

    def _validate_llm_response(self, names: List[str]) -> List[str]:
        """Filter LLM-returned names to those that exist in the graph.

        Uses canonical casing from the graph, not the LLM's casing.
        Logs discarded names at DEBUG level.

        Args:
            names: Raw entity names from LLM response.

        Returns:
            Validated canonical entity names.
        """
        ...
```

### Dependencies

| Dependency | Import Path | Kind |
|---|---|---|
| `LLMProvider` | `src.platform.llm.provider` | Runtime (lazy import) |
| `get_llm_provider` | `src.platform.llm.provider` | Runtime (lazy import) |
| `KGConfig` | `src.knowledge_graph.common.types` | Constructor param |

### Files Modified

| File | Change |
|---|---|
| `src/knowledge_graph/query/entity_matcher.py` | Extend `__init__` signature, implement `match_with_llm_fallback`, add private methods |

### REQ Coverage

| REQ | Description | Coverage |
|---|---|---|
| REQ-KG-1b-300 | Actual LLM call in fallback | `_llm_fallback` via `json_completion()` |
| REQ-KG-1b-301 | Entity list grouped by type, token budget truncation | `_build_entity_list_prompt` |
| REQ-KG-1b-302 | Validate returned names against graph | `_validate_llm_response` |
| REQ-KG-1b-303 | Config gating via `enable_llm_query_fallback` | Guard in `match_with_llm_fallback` |
| REQ-KG-1b-304 | Configurable timeout, empty on timeout | `timeout` kwarg to `json_completion()` |
| REQ-KG-1b-305 | Skip LLM for < 3 token queries | Token count guard in `match_with_llm_fallback` |

### Backward Compatibility

The new `__init__` parameters are all optional with `None` defaults. Existing callers that construct `EntityMatcher(entity_names, aliases)` continue to work. When `config` is `None` or `enable_llm_query_fallback` is `False`, `match_with_llm_fallback()` degrades to the current behavior (returns spaCy/substring results only).

---

## T1b-4: Config Extensions

**Estimated LOC:** ~50
**Files:** `src/knowledge_graph/common/types.py`, `config/settings.py`

### Summary

Add new `KGConfig` fields required by T1b-1 and T1b-3. Add corresponding environment variable bindings in `config/settings.py` following the existing `RAG_KG_*` naming convention.

### New KGConfig Fields

```python
# Added to the existing KGConfig dataclass in src/knowledge_graph/common/types.py

@dataclass
class KGConfig:
    # ... existing fields ...

    # T1b-1: LLM Extractor config
    llm_extraction_model: str = "default"
    """Router model alias for LLM extraction calls."""

    llm_extraction_prompt_template: Optional[str] = None
    """Path to a custom prompt template file. None = use embedded default."""

    llm_extraction_max_retries: int = 1
    """Max retries on malformed JSON response (REQ-KG-1b-104)."""

    llm_extraction_rate_limit_retries: int = 3
    """Max retries on HTTP 429 rate-limit errors (REQ-KG-1b-108)."""

    # T1b-3: LLM Query Fallback config
    llm_fallback_token_budget: int = 4096
    """Max token budget for entity list in LLM fallback prompt (REQ-KG-1b-301)."""
```

### New Environment Variables in config/settings.py

```python
# Added to config/settings.py, in the KG settings section

RAG_KG_LLM_EXTRACTION_MODEL = os.environ.get(
    "RAG_KG_LLM_EXTRACTION_MODEL", "default"
)
RAG_KG_LLM_EXTRACTION_PROMPT_TEMPLATE = os.environ.get(
    "RAG_KG_LLM_EXTRACTION_PROMPT_TEMPLATE", ""
) or None
RAG_KG_LLM_EXTRACTION_MAX_RETRIES = int(
    os.environ.get("RAG_KG_LLM_EXTRACTION_MAX_RETRIES", "1")
)
RAG_KG_LLM_EXTRACTION_RATE_LIMIT_RETRIES = int(
    os.environ.get("RAG_KG_LLM_EXTRACTION_RATE_LIMIT_RETRIES", "3")
)
RAG_KG_LLM_FALLBACK_TOKEN_BUDGET = int(
    os.environ.get("RAG_KG_LLM_FALLBACK_TOKEN_BUDGET", "4096")
)
RAG_KG_ENABLE_LLM_QUERY_FALLBACK = os.environ.get(
    "RAG_KG_ENABLE_LLM_QUERY_FALLBACK", "false"
).lower() in ("true", "1", "yes")
RAG_KG_LLM_FALLBACK_TIMEOUT_MS = int(
    os.environ.get("RAG_KG_LLM_FALLBACK_TIMEOUT_MS", "1000")
)
```

### Files Modified

| File | Change |
|---|---|
| `src/knowledge_graph/common/types.py` | Add 5 new fields to `KGConfig` dataclass |
| `config/settings.py` | Add 7 env var bindings in KG settings section |

### REQ Coverage

| REQ | Description | Coverage |
|---|---|---|
| REQ-KG-1b-100 AC1 | LLM provider injection | Existing `enable_llm_extractor` toggle |
| REQ-KG-1b-104 AC5 | Configurable max retry count | `llm_extraction_max_retries` |
| REQ-KG-1b-106 | Configurable prompt template path | `llm_extraction_prompt_template` |
| REQ-KG-1b-108 | Rate-limit retry count | `llm_extraction_rate_limit_retries` |
| REQ-KG-1b-301 | Token budget for entity list | `llm_fallback_token_budget` |
| REQ-KG-1b-303 | Enable flag for LLM fallback | Existing `enable_llm_query_fallback` (env binding added) |
| REQ-KG-1b-304 | Fallback timeout | Existing `llm_fallback_timeout_ms` (env binding added) |

---

## T1b-5: Integration Updates

**Estimated LOC:** ~50
**Files:** `src/knowledge_graph/extraction/__init__.py`, `src/ingest/embedding/nodes/knowledge_graph_extraction.py`

### Summary

Update package exports to include the new extractors. Update Node 10 (`knowledge_graph_extraction_node`) to optionally use the LLM extractor when `enable_llm_extractor` is set, alongside the existing regex/GLiNER selection.

### Changes to extraction/__init__.py

```python
# src/knowledge_graph/extraction/__init__.py

from src.knowledge_graph.extraction.base import EntityExtractor
from src.knowledge_graph.extraction.regex_extractor import RegexEntityExtractor, STOPWORDS
from src.knowledge_graph.extraction.llm_extractor import LLMEntityExtractor
from src.knowledge_graph.extraction.parser_extractor import SVParserExtractor

__all__ = [
    "EntityExtractor",
    "RegexEntityExtractor",
    "LLMEntityExtractor",
    "SVParserExtractor",
    "STOPWORDS",
]
```

### Changes to Node 10 (_get_extractor)

```python
# src/ingest/embedding/nodes/knowledge_graph_extraction.py
# Updated _get_extractor() function.

def _get_extractor():
    """Lazy-load the appropriate extractor based on config.

    Priority order (first available wins):
    1. LLM extractor (if enable_llm_extractor is True)
    2. GLiNER extractor (if use_gliner is True)
    3. Regex extractor (always available)

    The SV parser extractor is NOT selected here -- it is invoked
    separately for .sv/.v/.svh files via extract_file(), not per-chunk.
    """
    from src.knowledge_graph.common.types import KGConfig, load_schema

    config = KGConfig.from_env()

    if config.enable_llm_extractor:
        try:
            from src.knowledge_graph.extraction.llm_extractor import (
                LLMEntityExtractor,
            )
            schema = load_schema(str(config.schema_path))
            return LLMEntityExtractor(schema=schema, config=config)
        except Exception as exc:
            logger.warning("LLM extractor unavailable (%s), falling back", exc)

    if config.use_gliner:
        try:
            from src.knowledge_graph.extraction.gliner_extractor import (
                GLiNEREntityExtractor,
            )
            return GLiNEREntityExtractor()
        except Exception as exc:
            logger.warning("GLiNER unavailable (%s), falling back to regex", exc)

    from src.knowledge_graph.extraction.regex_extractor import RegexEntityExtractor
    return RegexEntityExtractor()
```

### Files Modified

| File | Change |
|---|---|
| `src/knowledge_graph/extraction/__init__.py` | Add `LLMEntityExtractor` and `SVParserExtractor` imports and exports |
| `src/ingest/embedding/nodes/knowledge_graph_extraction.py` | Add LLM extractor branch in `_get_extractor()` |

### REQ Coverage

| REQ | Description | Coverage |
|---|---|---|
| REQ-KG-1b-100 | LLM extractor integration | Node 10 LLM branch |
| REQ-KG-310 | Merge node compatibility | Extractors return `ExtractionResult` (unchanged contract) |

---

## Task Dependency Graph

```
T1b-4 (Config Extensions)
  |
  +---> T1b-1 (LLM Extractor)  --+
  |                                |--> T1b-5 (Integration Updates)
  +---> T1b-2 (SV Parser)       --+
  |
  +---> T1b-3 (LLM Query Fallback)
```

- **T1b-4** has no dependencies and should be implemented first -- all other tasks depend on the new config fields.
- **T1b-1**, **T1b-2**, and **T1b-3** are independent of each other and can be implemented in parallel after T1b-4.
- **T1b-5** depends on T1b-1 and T1b-2 being complete (imports their classes).

### Recommended Implementation Order

1. **T1b-4** -- Config extensions (unblocks everything)
2. **T1b-1** / **T1b-2** / **T1b-3** -- in parallel or any order
3. **T1b-5** -- Integration wiring (last)

---

## Summary Table

| Task | File(s) | Est. LOC | REQs Covered | Dependencies |
|---|---|---|---|---|
| T1b-1: LLM Extractor | `extraction/llm_extractor.py` | ~300 | 1b-100 through 1b-109 | T1b-4, LLMProvider |
| T1b-2: SV Parser | `extraction/parser_extractor.py` | ~400 | 1b-200 through 1b-209 | T1b-4, tree-sitter, tree-sitter-verilog |
| T1b-3: LLM Query Fallback | `query/entity_matcher.py` | ~100 | 1b-300 through 1b-305 | T1b-4, LLMProvider |
| T1b-4: Config Extensions | `common/types.py`, `config/settings.py` | ~50 | Cross-cutting | None |
| T1b-5: Integration | `extraction/__init__.py`, `nodes/knowledge_graph_extraction.py` | ~50 | 1b-100, KG-310 | T1b-1, T1b-2 |
| **Total** | | **~900** | **25 REQs** | |

---

## Open Questions

1. **LLM extractor model alias:** The sketch uses `"default"`. Should Phase 1b add a dedicated `"kg_extraction"` alias to the Router config for independent model selection and cost tracking? (Current design: configurable via `llm_extraction_model`, defaults to `"default"`.)

2. **SV parser grammar build:** The `tree-sitter-verilog` Python package (PyPI) bundles a pre-built grammar. Should we also support building from a local grammar repo for teams that maintain custom grammar forks? (Current design: PyPI package only.)

3. **Entity mention counts in fallback:** REQ-KG-1b-301 requires truncation by mention count. The `EntityMatcher` constructor does not currently receive mention counts. Options: (a) pass a `Dict[str, int]` of mention counts, (b) infer from entity frequency in the graph, (c) truncate alphabetically as a simpler fallback. (Current design: option (a) -- add an optional `entity_mention_counts` param.)
