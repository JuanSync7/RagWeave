# KG Phase 1b Design Sketch — LLM Extractor, SV Parser, LLM Query Fallback

**Date:** 2026-04-08
**Status:** Draft
**Spec refs:** REQ-KG-306, REQ-KG-307, REQ-KG-308, REQ-KG-309, REQ-KG-602

---

## Goal

Implement three Phase 1b deliverables on top of the existing Phase 1 KG architecture:

1. **LLM Extractor** — structured JSON extraction of entities, relations, and descriptions from document chunks using the project's LiteLLM Router.
2. **SV Parser Extractor** — deterministic structural extraction from SystemVerilog files using tree-sitter-verilog.
3. **LLM Query Fallback** — semantic entity matching when spaCy/substring matching finds nothing.

All three must return the existing `ExtractionResult` / entity-list contracts and integrate with the existing `LLMProvider`, `SchemaDefinition`, and `KGConfig` infrastructure.

---

## 1. LLM Extractor

### Approach Evaluation

| # | Approach | Pros | Cons |
|---|----------|------|------|
| A | **Single-prompt extraction** — one LLM call per chunk producing a JSON object with `entities`, `triples`, and `descriptions` arrays | Simplest; one round-trip; lower latency and cost; easier retry logic | Larger prompt; model may miss relations if entity list is long; harder to isolate entity vs. relation errors |
| B | **Two-pass extraction** — first call extracts entities, second call extracts relations given the entity list | Entity list is concrete input to relation pass, improving relation precision; easier to debug each step | 2x latency and cost per chunk; entity errors propagate to relation pass; more complex orchestration |
| C | **Schema-guided single-prompt** — single call but prompt constrains output to YAML schema types with extraction hints | Same cost as A; schema types act as a rubric so the model doesn't hallucinate types; extraction hints improve recall for domain-specific types | Prompt is longer (schema context); if schema is very large the context window pressure grows |

**Recommendation: C (schema-guided single-prompt).**

Rationale: Option C combines the simplicity and cost efficiency of a single call with the precision benefit of schema grounding. The YAML schema has 41 node types and 22 edge types — roughly 3-4K tokens when rendered as a compact list with hints — well within context budgets. This aligns directly with REQ-KG-306 AC3 ("prompt template includes all active node types, edge types, and extraction hints") and REQ-KG-307 (configurable prompt template with `{schema_types}`, `{schema_edges}`, `{extraction_hints}` variables).

Two-pass (B) would be justified if single-pass relation quality proves poor in practice, but that is a refinement for later — start simple.

### Chosen Approach Details

**Prompt design:**

- System message: role definition + output format specification (JSON schema).
- User message: rendered template with four substitution variables:
  - `{schema_types}` — active node types with descriptions and extraction hints, filtered by `runtime_phase`.
  - `{schema_edges}` — active edge types with descriptions + source/target constraints.
  - `{extraction_hints}` — concatenated hints block (redundant with types but useful as a summary section).
  - `{chunk_text}` — the document chunk to analyze.
- Output format: JSON object matching a Pydantic/dataclass contract:

```json
{
  "entities": [
    {"name": "AXI_Arbiter", "type": "RTL_Module", "description": "Arbitrates AXI bus requests"}
  ],
  "triples": [
    {"subject": "AXI_Arbiter", "predicate": "instantiates", "object": "RoundRobinArb"}
  ]
}
```

**LLM integration:**

- Use `LLMProvider.json_completion()` (already provides `response_format: {"type": "json_object"}`).
- Accept an optional `LLMProvider` instance via constructor injection; fall back to `get_llm_provider()` singleton.
- Model alias: `"default"` (configurable via constructor or config).

**Validation + retry:**

- Parse JSON response; on `json.JSONDecodeError`, log warning and retry once with a "fix your JSON" follow-up message.
- Validate each entity type against `SchemaDefinition.is_valid_node_type(type, runtime_phase)`.
- Validate each triple predicate against `SchemaDefinition.is_valid_edge_type()`.
- Invalid types: reclassify to `"concept"` (legacy fallback) with a logged warning, matching merge node behavior.
- Invalid edge predicates: drop the triple, log warning.
- Maximum 1 retry (configurable). On second failure, return empty `ExtractionResult` rather than raising.

**Prompt template storage:**

- Default template embedded as a module-level constant string in `llm_extractor.py`.
- Overridable via `KGConfig` field `llm_extraction_prompt_template` (path to a text file).
- Template rendering uses `str.format_map()` with the four variables.

**Interface contract:**

```python
class LLMEntityExtractor:
    extractor_name: str = "llm"

    def __init__(
        self,
        schema: SchemaDefinition,
        config: KGConfig,
        llm_provider: Optional[LLMProvider] = None,
    ) -> None: ...

    def extract(self, text: str, source: str = "") -> ExtractionResult: ...
```

---

## 2. SV Parser Extractor

### Approach Evaluation

| # | Approach | Pros | Cons |
|---|----------|------|------|
| A | **tree-sitter-verilog** — Python `tree-sitter` bindings + `tree-sitter-verilog` grammar | Mature grammar; incremental parsing; fast; good Python bindings; widely used in editor tooling; supports `.sv` and `.v` | Grammar may lag latest SV-2023 features; some UVM macro constructs produce ERROR nodes; requires building the grammar `.so` at install time |
| B | **pyslang** — Python bindings for the `slang` SV compiler frontend | Full SV-2017 compliance; handles preprocessor, macros, and elaboration | Heavier dependency; fewer users in the Python ecosystem; binary distribution may have platform issues; overkill for structural extraction |
| C | **Custom regex** — pattern match `module`, `input`, `output`, instance syntax | Zero dependencies; easy to understand | Fragile; breaks on parameterized ports, generate blocks, multiline declarations; not deterministic in edge cases; REQ-KG-308 demands deterministic extraction |

**Recommendation: A (tree-sitter-verilog).**

Rationale: tree-sitter provides the right balance of reliability and weight. The Phase 1b context document already specifies tree-sitter as the intended approach. Full compiler semantics (pyslang) are unnecessary — we need structural AST traversal, not elaboration. Regex is too fragile for the variety of SV syntax.

### Chosen Approach Details

**Grammar setup:**

- Dependency: `tree-sitter` (>=0.22) + `tree-sitter-verilog` Python package.
- Language object loaded via `tree_sitter_verilog.language()` (new API) or built from grammar repo.
- Parser created once per `SVParserExtractor` instance and reused.

**Extraction targets (mapped to YAML schema types):**

| SV Construct | tree-sitter node type | KG Entity Type | Extraction method |
|---|---|---|---|
| `module...endmodule` | `module_declaration` | `RTL_Module` | Walk children for name, ports, body |
| `input/output/inout` | `port_declaration`, `ansi_port_declaration` | `Port` | Direction from keyword, width from range |
| `parameter/localparam` | `parameter_declaration`, `local_parameter_declaration` | `Parameter` | Name, default value, type |
| Module instantiation | `module_instantiation` | `Instance` + `instantiates` triple | Instance name, module type |
| `wire/reg/logic` | `net_declaration`, `data_declaration` | `Signal` | Signal type, width |
| `interface...endinterface` | `interface_declaration` | `Interface` | Name, ports |
| `package...endpackage` | `package_declaration` | `Package` | Name |
| `generate...endgenerate` | `generate_region` | `Generate` (phase_1b) | Generate type |
| `task/function` | `task_declaration`, `function_declaration` | `Task_Function` (phase_1b) | Kind, return type |
| `always @(posedge clk)` | `always_construct` | `ClockDomain` (phase_1b) | Clock signal extraction |

**Relationship extraction:**

- `contains`: parent module → child entity (ports, parameters, signals, instances).
- `instantiates`: instance → instantiated module type.
- `connects_to`: port connection in module instantiation → port/signal.
- `parameterized_by`: instance with parameter overrides → parameter.

**Error handling:**

- tree-sitter parse errors produce `ERROR` or `MISSING` nodes in the CST. Walk the tree; skip ERROR subtrees; log warnings with file path and byte range.
- Non-SV files (detected by extension check `.sv`, `.v`, `.svh`): return empty `ExtractionResult`.
- Maintain a `KNOWN_UNSUPPORTED` list (module constant) per REQ-KG-309: e.g., complex UVM macros, `bind` statements, cross-module references.

**Interface contract:**

```python
class SVParserExtractor:
    extractor_name: str = "sv_parser"

    def __init__(
        self,
        schema: SchemaDefinition,
        config: KGConfig,
    ) -> None: ...

    def extract(self, text: str, source: str = "") -> ExtractionResult: ...
    def extract_file(self, file_path: str) -> ExtractionResult: ...
```

---

## 3. LLM Query Fallback

### Approach Evaluation

| # | Approach | Pros | Cons |
|---|----------|------|------|
| A | **Standalone LLM call** — send query + entity type list to LLM, ask it to identify relevant entity names from a provided list | Simple; can include entity names + types as context; directly answers "which of these entities is the user asking about?" | Requires sending the full entity list (may be large); latency on the query hot path |
| B | **Reuse the LLM extractor** — apply the same extraction pipeline to the query text | Code reuse; consistent extraction logic | Over-engineered for short queries; extracts triples we don't need; query text is too short for meaningful chunk extraction |
| C | **Embedding similarity** — embed the query, find nearest entity name embeddings | Fast at query time (precomputed embeddings); no LLM call | Requires maintaining an entity embedding index; different infrastructure from LLM fallback; less semantic understanding of intent |

**Recommendation: A (standalone LLM call).**

Rationale: The fallback is triggered only when spaCy/substring matching finds nothing — it's an exception path, not the hot path. A purpose-built prompt ("given this query and these entity names, which entities is the user asking about?") is more targeted than repurposing the full extraction pipeline. Entity list size is manageable: send only entity names grouped by type (no descriptions), which fits in ~2-4K tokens even for large graphs. The timeout requirement (REQ-KG-602 AC3) is trivially implemented via the LLMProvider's `timeout` parameter.

Embedding similarity (C) is worth considering as a Phase 2 optimization if LLM latency proves problematic, but for Phase 1b the LLM approach is correct — it handles paraphrased references that embedding similarity would miss ("the module that handles memory arbitration" → "MemArbiter").

### Chosen Approach Details

**Prompt design:**

- System: "You are an entity resolver. Given a user query and a list of known entities, return the entity names that the query is referring to."
- User: query text + entity list formatted as `TYPE: name1, name2, ...` groups.
- Output: JSON array of matched canonical entity names.

**Integration into EntityMatcher:**

```python
def match_with_llm_fallback(self, query: str) -> List[str]:
    results = self.match(query)
    if results:
        return results
    if len(query.split()) < 3:
        return []  # REQ-KG-602 AC2: skip very short queries
    if not self._config.enable_llm_query_fallback:
        return []
    return self._llm_fallback(query)
```

**Timeout handling:**

- Pass `timeout=config.llm_fallback_timeout_ms // 1000` to `LLMProvider.json_completion()`.
- Wrap in try/except; on any exception (timeout, parse error, LLM error), log and return empty list.

**Entity list management:**

- The `EntityMatcher` already holds `_entity_names` and `_aliases`. Format these into the prompt grouped by type (requires storing entity types — extend constructor to accept `Dict[str, str]` mapping name → type, or a flat list of `(name, type)` tuples).
- If the entity list exceeds a configurable token budget (default: 4096 tokens), truncate to highest-mention-count entities.

---

## Key Technical Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| LLM abstraction | `LLMProvider` from `src/platform/llm/provider.py` | Project standard; handles Router config, retries, cost tracking |
| JSON mode | `json_completion()` method | Already wraps `response_format: {"type": "json_object"}` |
| Schema filtering | `SchemaDefinition.active_node_types(runtime_phase)` | Only include types relevant to current phase in prompts |
| Prompt template | Module constant + file override via `KGConfig` | REQ-KG-307 compliance; no code change for prompt iteration |
| SV parser | `tree-sitter` + `tree-sitter-verilog` | Specified in phase context; right balance of reliability and weight |
| Retry policy | 1 retry on malformed JSON, then return empty result | Fail gracefully per REQ-KG-306 AC4; avoid infinite retry loops |
| LLM fallback gating | `KGConfig.enable_llm_query_fallback` (default: False) | REQ-KG-602 AC4; opt-in to avoid latency on the query path |
| Extractor name tags | `"llm"`, `"sv_parser"` | Used by merge node for source attribution and priority resolution (REQ-KG-311) |

---

## Risk Register

| # | Risk | Likelihood | Impact | Mitigation |
|---|------|------------|--------|------------|
| R1 | LLM returns invalid JSON despite `json_object` mode | Medium | Low | 1 retry with corrective prompt; graceful fallback to empty result |
| R2 | LLM hallucinates entity types not in schema | High | Medium | Post-extraction validation against `SchemaDefinition`; reclassify to fallback type |
| R3 | LLM hallucinates entity names not present in text | Medium | Medium | Log provenance; downstream merge node deduplication will absorb some noise; consider adding a "must be mentioned in text" instruction to prompt |
| R4 | tree-sitter-verilog grammar lacks coverage for some SV constructs | Medium | Low | KNOWN_UNSUPPORTED list; ERROR node handling returns partial results; grammar can be updated independently |
| R5 | tree-sitter Python package version incompatibility (0.22 API vs older) | Low | Medium | Pin version in requirements; test in CI; provide clear install instructions |
| R6 | Large entity list exceeds LLM context window in query fallback | Low | Medium | Token budget truncation; group by type and truncate low-frequency entities |
| R7 | LLM query fallback adds unacceptable latency to query path | Medium | Medium | Disabled by default; configurable timeout; timeout returns empty list |
| R8 | LLM extraction cost grows with corpus size (one call per chunk) | Medium | High | Make extractor optional (config toggle); consider batching chunks in future; monitor cost via `LLMResponse.cost_usd` |
| R9 | Prompt template variable substitution fails silently on typo | Low | Low | Validate template variables at init time; raise `ValueError` if required variables are missing |
| R10 | SV parser produces duplicate entities across files (same module name in different files) | Medium | Low | Merge node handles deduplication by normalized name; `source` field distinguishes provenance |
