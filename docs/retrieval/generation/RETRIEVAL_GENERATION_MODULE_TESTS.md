# Retrieval Pipeline — Generation Subsystem Module Tests

**AION Knowledge Management Platform**
Version: 1.0 | Status: Draft | Domain: Retrieval Pipeline — Generation and Safety
Last updated: 2026-03-25

| Field | Value |
|-------|-------|
| **Phase** | Phase D — White-Box Tests (write-module-tests skill) |
| **Companion Spec** | `RETRIEVAL_GENERATION_SPEC.md` v1.2 |
| **Engineering Guide** | `RETRIEVAL_GENERATION_ENGINEERING_GUIDE.md` (Phase C output — required before Phase D runs) |
| **Implementation Plan** | `RETRIEVAL_IMPLEMENTATION.md` — Phase D tasks |

> **Document intent:** Specifies the Phase D white-box test coverage for each generation and safety subsystem module. Each module section lists the test categories, test cases, and isolation contract for the Phase D agent. These tests are derived from the engineering guide's Error behavior and Test guide sub-sections — NOT from reading source code.
>
> **When to use:** After Phase C-cross completes and `RETRIEVAL_GENERATION_ENGINEERING_GUIDE.md` exists. Dispatch one Phase D agent per module, providing the agent ONLY with: (1) the module's section from the engineering guide, (2) Phase 0 contract files, (3) FR numbers listed in this document.

---

## Agent Isolation Contract

**Include verbatim at the top of every Phase D agent task:**

> **Agent isolation contract:** This agent receives ONLY:
> 1. The module section from `RETRIEVAL_GENERATION_ENGINEERING_GUIDE.md` (Purpose, Error behavior, Test guide sub-sections)
> 2. Phase 0 contract files (TypedDicts, signatures, exceptions)
> 3. FR numbers from `RETRIEVAL_GENERATION_SPEC.md`
>
> **Must NOT receive:** Any source files (`src/`), any Phase A test files, the design doc.
>
> If the engineering guide section is insufficient to write a test, note it as a known gap — do not fetch the source.

---

## Module: Document Formatter

**Source:** `src/retrieval/formatting/formatter.py`
**Engineering Guide Section:** `docs/retrieval/RETRIEVAL_GENERATION_ENGINEERING_GUIDE.md` → Section 3: `src/retrieval/formatting/formatter.py`
**Phase 0 contracts:** `src/retrieval/formatting/types.py`
**FR coverage:** REQ-501, REQ-503
**Phase D test file:** `tests/retrieval/test_document_formatter_coverage.py`

### Isolation contract for this module's Phase D agent

Agent input (ONLY these):
1. Module section from `RETRIEVAL_GENERATION_ENGINEERING_GUIDE.md` for `src/retrieval/formatting/formatter.py` (Purpose, Error behavior, Test guide sub-sections)
2. Phase 0 contracts: `src/retrieval/formatting/types.py`
3. FR numbers: REQ-501, REQ-503

Must NOT receive: `src/retrieval/formatting/formatter.py`, any Phase A test files.

### Error behavior tests
(derived from engineering guide's "Error behavior" sub-section)

- [ ] `test_format_chunks_missing_filename_fills_unknown` — REQ-501: a chunk with no `filename` field produces metadata string containing `"filename: unknown"` rather than raising KeyError
- [ ] `test_format_chunks_missing_version_fills_unknown` — REQ-501: a chunk with no `version` field produces metadata string containing `"version: unknown"`
- [ ] `test_format_chunks_missing_date_fills_unknown` — REQ-501: a chunk with no `date` field produces metadata string containing `"date: unknown"`
- [ ] `test_format_chunks_missing_domain_fills_unknown` — REQ-501: a chunk with no `domain` field produces metadata string containing `"domain: unknown"`
- [ ] `test_format_chunks_missing_section_fills_unknown` — REQ-501: a chunk with no `section` field produces metadata string containing `"section: unknown"`
- [ ] `test_format_chunks_missing_spec_id_fills_unknown` — REQ-501: a chunk with no `spec_id` field produces metadata string containing `"spec_id: unknown"`
- [ ] `test_format_chunks_empty_doc_list_returns_empty_string` — REQ-503: empty input list produces empty context string without raising

### Boundary condition tests
(derived from engineering guide's "Test guide → Boundary conditions")

- [ ] `test_format_chunks_single_doc_numbered_one` — single-document list produces chunk numbered `[1]` (sequential numbering starts at 1)
- [ ] `test_format_chunks_all_metadata_missing_produces_all_unknown` — chunk with no metadata fields at all produces a well-formed context block with all six fields set to `"unknown"`
- [ ] `test_format_chunks_partial_metadata_only_missing_fields_are_unknown` — chunk with only `filename` and `version` present: those two fields appear verbatim, remaining four fields are `"unknown"`
- [ ] `test_format_chunks_metadata_precedes_content` — for any chunk, the metadata block appears before the content text in the context string
- [ ] `test_format_chunks_large_doc_list_numbering_is_sequential` — a list of 20 chunks produces sequentially numbered chunks from 1 to 20 with no gaps or duplicates

### Behavior tests
(derived from engineering guide's "Test guide → Behaviors to test")

- [ ] `test_format_chunks_all_six_metadata_fields_present_in_output` — REQ-501: when all six metadata fields are provided, all six appear in the formatted context block for that chunk
- [ ] `test_format_chunks_sequential_numbering_across_all_chunks` — REQ-503: a list of N chunks produces exactly chunks numbered 1 through N in order
- [ ] `test_format_chunks_deterministic_same_input_same_output` — REQ-503: calling the formatter twice with identical input produces byte-identical output strings
- [ ] `test_format_chunks_deterministic_ordering_preserved` — REQ-503: chunk ordering in the output matches input list ordering (chunk 1 is first in list, chunk N is last)
- [ ] `test_format_chunks_consistent_format_across_all_chunks` — REQ-503: all chunks in a multi-document list use the same metadata field labels and separator characters
- [ ] `test_format_chunks_version_conflict_flag_appears_in_context` — REQ-503: when a version conflict flag is present in the input state, a conflict warning block is included in the context string

### Known test gaps (to note in Phase D agent output)
- Determinism test may be sensitive to Python dict ordering in older Python versions — confirm implementation uses `sorted()` or `dataclass` field order, not arbitrary dict iteration.
- Floating-point values in metadata (e.g., confidence scores embedded in chunk content) do not affect formatting determinism because formatter handles only string fields — no known gap.
- Format specification (separator characters, field label strings, block delimiters) is not observable until the engineering guide documents it — if the engineering guide omits the exact format, Phase D agent must note this as a gap.

### Pytest command
```bash
cd /home/juansync7/RAG && python -m pytest tests/retrieval/test_document_formatter_coverage.py -v
# Expected: FAIL (new tests — implementation exists but these are new coverage tests)
# Phase E will confirm ALL PASS after full suite verification
```

---

## Module: Version Conflict Detection

**Source:** `src/retrieval/formatting/conflicts.py`
**Engineering Guide Section:** `docs/retrieval/RETRIEVAL_GENERATION_ENGINEERING_GUIDE.md` → Section 3: `src/retrieval/formatting/conflicts.py`
**Phase 0 contracts:** `src/retrieval/formatting/types.py`
**FR coverage:** REQ-502
**Phase D test file:** `tests/retrieval/test_version_conflicts_coverage.py`

### Isolation contract for this module's Phase D agent

Agent input (ONLY these):
1. Module section from `RETRIEVAL_GENERATION_ENGINEERING_GUIDE.md` for `src/retrieval/formatting/conflicts.py` (Purpose, Error behavior, Test guide sub-sections)
2. Phase 0 contracts: `src/retrieval/formatting/types.py`
3. FR numbers: REQ-502

Must NOT receive: `src/retrieval/formatting/conflicts.py`, any Phase A test files.

### Error behavior tests
(derived from engineering guide's "Error behavior" sub-section)

- [ ] `test_detect_conflicts_empty_doc_list_returns_no_conflicts` — REQ-502: an empty document list produces zero conflict records without raising
- [ ] `test_detect_conflicts_single_doc_returns_no_conflicts` — REQ-502: a list with a single document cannot have a version conflict; function returns empty conflict list without raising
- [ ] `test_detect_conflicts_docs_with_missing_spec_id_falls_back_to_filename_stem` — REQ-502: documents lacking `spec_id` are grouped by filename stem (e.g., `"Power_Spec"` from both `Power_Spec_v2.pdf` and `Power_Spec_v3.pdf`) — no crash on missing `spec_id`
- [ ] `test_detect_conflicts_docs_with_no_overlap_returns_no_conflicts` — two documents with entirely different spec IDs and different filename stems produce zero conflict records

### Boundary condition tests
(derived from engineering guide's "Test guide → Boundary conditions")

- [ ] `test_detect_conflicts_exactly_two_versions_same_spec_produces_one_conflict` — REQ-502: `Power_Spec_v2.pdf` and `Power_Spec_v3.pdf` in the same doc list produce exactly one conflict record containing both version identifiers
- [ ] `test_detect_conflicts_three_versions_same_spec_produces_one_conflict_record` — three documents with the same `spec_id` but versions `v1`, `v2`, `v3` produce a single conflict record (not two pairwise records) listing all three versions
- [ ] `test_detect_conflicts_two_specs_each_conflicted_produces_two_conflict_records` — two independent specs each with two versions produce two independent conflict records
- [ ] `test_detect_conflicts_same_version_twice_no_conflict` — two documents with identical `spec_id` AND identical `version` are not flagged as a conflict (duplicate, not conflict)

### Behavior tests
(derived from engineering guide's "Test guide → Behaviors to test")

- [ ] `test_detect_conflicts_conflict_record_contains_both_version_identifiers` — REQ-502: the returned conflict record includes both `v2` and `v3` when `Power_Spec_v2.pdf` and `Power_Spec_v3.pdf` conflict
- [ ] `test_detect_conflicts_conflict_injected_into_context_string` — REQ-502: when `inject_conflict_context()` is called with a conflict record, the returned string contains a warning block referencing the conflicting filenames and versions
- [ ] `test_detect_conflicts_conflict_info_present_in_user_facing_message` — REQ-502: the conflict-surfacing function produces a string naming both conflicting versions that can be appended to the user response
- [ ] `test_detect_conflicts_pipeline_state_flagged_when_conflict_detected` — REQ-502: after conflict detection, the pipeline state's conflict flag is set to `True` and the conflict records list is non-empty
- [ ] `test_detect_conflicts_no_silent_resolution_llm_sees_both_versions` — REQ-502: the context string produced when a conflict is present contains references to both conflicting version identifiers (LLM cannot silently ignore one)

### Known test gaps (to note in Phase D agent output)
- Filename stem parsing heuristic (stripping version suffix from filenames like `Power_Spec_v3.pdf`) depends on a regex or string-splitting rule not yet visible without the engineering guide — if the guide does not specify the exact stemming rule, test inputs may not exercise the boundary correctly.
- Three-or-more-version grouping behavior (single record vs. pairwise records) is not specified in the spec acceptance criteria — Phase D agent should confirm the grouping strategy from the engineering guide before writing this test.

### Pytest command
```bash
cd /home/juansync7/RAG && python -m pytest tests/retrieval/test_version_conflicts_coverage.py -v
# Expected: FAIL (new tests — implementation exists but these are new coverage tests)
# Phase E will confirm ALL PASS after full suite verification
```

---

## Module: Prompt Template Loader

**Source:** `src/retrieval/prompt_loader.py`
**Engineering Guide Section:** `docs/retrieval/RETRIEVAL_GENERATION_ENGINEERING_GUIDE.md` → Section 3: `src/retrieval/prompt_loader.py`
**Phase 0 contracts:** none (no Phase 0 type file for this module)
**FR coverage:** REQ-601, REQ-602
**Phase D test file:** `tests/retrieval/test_prompt_template_coverage.py`

### Isolation contract for this module's Phase D agent

Agent input (ONLY these):
1. Module section from `RETRIEVAL_GENERATION_ENGINEERING_GUIDE.md` for `src/retrieval/prompt_loader.py` (Purpose, Error behavior, Test guide sub-sections)
2. Phase 0 contracts: none
3. FR numbers: REQ-601, REQ-602

Must NOT receive: `src/retrieval/prompt_loader.py`, any Phase A test files.

### Error behavior tests
(derived from engineering guide's "Error behavior" sub-section)

- [ ] `test_load_prompt_missing_file_raises_file_not_found_with_path` — REQ-601: loading a prompt from a non-existent path raises `FileNotFoundError` and the exception message includes the attempted file path (not a generic error)
- [ ] `test_render_prompt_unrecognized_variable_raises_error` — REQ-602: passing a variable name not declared in the template raises a clear error (not a silent no-op or a KeyError with an unhelpful message)
- [ ] `test_render_prompt_missing_required_variable_raises_error` — REQ-602: calling render without supplying a required declared variable raises an error rather than producing a partial prompt
- [ ] `test_load_prompt_empty_file_raises_or_returns_empty` — loading a prompt file that is empty either raises a descriptive error or returns an empty string (does not silently inject a blank system prompt)

### Boundary condition tests
(derived from engineering guide's "Test guide → Boundary conditions")

- [ ] `test_render_prompt_document_with_json_curly_braces_not_substituted` — REQ-602: a retrieved document containing `{"voltage": "1.8V", "domain": "analog"}` injected as a template variable does not trigger variable substitution for the keys inside the JSON object
- [ ] `test_render_prompt_document_with_nested_curly_braces_not_substituted` — REQ-602: a document containing `{{double_braces}}` in its content does not cause a template parsing error or incorrect substitution
- [ ] `test_render_prompt_document_with_yaml_block_not_substituted` — REQ-602: a document containing a YAML block with `{key: value}` syntax does not cause template substitution errors
- [ ] `test_render_prompt_only_declared_variables_are_substituted` — REQ-602: a template declaring `{query}` and `{context}` substitutes only those two variables; any `{...}` patterns in the injected context content are passed through verbatim

### Behavior tests
(derived from engineering guide's "Test guide → Behaviors to test")

- [ ] `test_load_prompt_contains_instruction_answer_only_from_documents` — REQ-601: the loaded system prompt contains language covering instruction category 1 ("answer only from provided documents")
- [ ] `test_load_prompt_contains_instruction_no_prior_knowledge` — REQ-601: the loaded system prompt contains language covering instruction category 2 ("never use training data or prior knowledge")
- [ ] `test_load_prompt_contains_instruction_cite_sources` — REQ-601: the loaded system prompt contains language covering instruction category 3 ("cite sources using specified format")
- [ ] `test_load_prompt_contains_instruction_state_insufficient_information` — REQ-601: the loaded system prompt contains language covering instruction category 4 ("explicitly state when information is insufficient")
- [ ] `test_load_prompt_contains_instruction_report_confidence` — REQ-601: the loaded system prompt contains language covering instruction category 5 ("report confidence level as part of response")
- [ ] `test_load_prompt_stored_as_separate_file_not_inline` — REQ-601: the prompt loader reads from a file path (not a hardcoded string constant in source) — verified by asserting the loader accepts a configurable path argument
- [ ] `test_render_prompt_changing_prompt_file_changes_output` — REQ-601: loading from a modified prompt file (different content at same path) produces a different rendered output without any code changes

### Known test gaps (to note in Phase D agent output)
- Prompt quality (whether the five instruction categories are semantically effective at reducing hallucination) is not machine-testable with unit tests.
- The exact strings used to detect instruction categories in `test_load_prompt_contains_instruction_*` tests depend on the prompt file wording — Phase D agent must read the prompt file at the documented path to write the assertion strings, but must NOT read `prompt_loader.py` source.
- Template engine identity (Jinja2, string.Template, custom) is not specified in the spec — the engineering guide must specify which engine is used before the Phase D agent can write the `{...}` boundary tests accurately.

### Pytest command
```bash
cd /home/juansync7/RAG && python -m pytest tests/retrieval/test_prompt_template_coverage.py -v
# Expected: FAIL (new tests — implementation exists but these are new coverage tests)
# Phase E will confirm ALL PASS after full suite verification
```

---

## Module: Confidence Scoring Utilities

**Source:** `src/retrieval/confidence/scoring.py`
**Engineering Guide Section:** `docs/retrieval/RETRIEVAL_GENERATION_ENGINEERING_GUIDE.md` → Section 3: `src/retrieval/confidence/scoring.py`
**Phase 0 contracts:** `src/retrieval/confidence/types.py`
**FR coverage:** REQ-604, REQ-701
**Phase D test file:** `tests/retrieval/test_confidence_scoring_coverage.py`

### Isolation contract for this module's Phase D agent

Agent input (ONLY these):
1. Module section from `RETRIEVAL_GENERATION_ENGINEERING_GUIDE.md` for `src/retrieval/confidence/scoring.py` (Purpose, Error behavior, Test guide sub-sections)
2. Phase 0 contracts: `src/retrieval/confidence/types.py`
3. FR numbers: REQ-604, REQ-701

Must NOT receive: `src/retrieval/confidence/scoring.py`, any Phase A test files.

### Error behavior tests
(derived from engineering guide's "Error behavior" sub-section)

- [ ] `test_parse_llm_confidence_unparseable_response_defaults_to_0_5` — REQ-604: an LLM response that contains no recognizable confidence string (e.g., response is empty, or contains only unrelated text) returns the neutral default of `0.5`
- [ ] `test_parse_llm_confidence_malformed_confidence_string_defaults_to_0_5` — REQ-604: a response containing `"confidence: very confident"` (not one of high/medium/low) defaults to `0.5` without raising
- [ ] `test_compute_composite_invalid_weights_not_summing_to_1_raises_value_error` — REQ-701: constructing or calling the composite scorer with weights that do not sum to `1.0` (within floating-point tolerance) raises `ValueError` with a descriptive message
- [ ] `test_compute_composite_negative_weight_raises_value_error` — REQ-701: a negative weight value raises `ValueError`
- [ ] `test_compute_composite_signal_out_of_range_raises_or_clamps` — a signal value outside `[0.0, 1.0]` either raises `ValueError` or is silently clamped — Phase D agent must confirm behavior from engineering guide

### Boundary condition tests
(derived from engineering guide's "Test guide → Boundary conditions")

- [ ] `test_compute_composite_all_signals_zero_returns_0_0` — REQ-701: retrieval=0.0, llm=0.0, citation=0.0 with default weights (0.50/0.25/0.25) produces composite = 0.0
- [ ] `test_compute_composite_all_signals_one_returns_1_0` — REQ-701: retrieval=1.0, llm=1.0, citation=1.0 with default weights produces composite = 1.0
- [ ] `test_compute_composite_at_re_retrieve_threshold_0_50` — REQ-701: a composite exactly equal to `0.50` is computed correctly (used to verify boundary routing in engine.py)
- [ ] `test_compute_composite_at_return_threshold_0_70` — REQ-701: a composite exactly equal to `0.70` is computed correctly (used to verify boundary routing in engine.py)
- [ ] `test_parse_llm_confidence_high_maps_below_0_85` — REQ-604: `"high"` confidence string maps to a value ≤ 0.85 (downward correction applied — not 1.0)
- [ ] `test_parse_llm_confidence_medium_maps_to_mid_range` — REQ-604: `"medium"` confidence string maps to a value in the mid-range (e.g., 0.5–0.75); exact value confirmed from engineering guide
- [ ] `test_parse_llm_confidence_low_maps_to_below_medium` — REQ-604: `"low"` confidence string maps to a value strictly less than the `"medium"` mapping

### Behavior tests
(derived from engineering guide's "Test guide → Behaviors to test")

- [ ] `test_compute_composite_formula_matches_configured_weights` — REQ-701: composite = (retrieval × 0.50) + (llm × 0.25) + (citation × 0.25) when using default weights; verified with a known input set
- [ ] `test_compute_composite_changing_weights_changes_output` — REQ-701: changing the retrieval weight from 0.50 to 0.60 (and reducing another weight) produces a different composite score for the same signal values
- [ ] `test_compute_composite_weights_sum_to_1_0_validation` — REQ-701: the scorer enforces that configured weights sum to 1.0 — verified by asserting default weights pass validation
- [ ] `test_compute_composite_individual_signals_logged_alongside_composite` — REQ-701: the returned result or logged output includes all three individual signal values, not just the composite
- [ ] `test_parse_llm_confidence_case_insensitive` — REQ-604: `"High"`, `"HIGH"`, and `"high"` all map to the same numerical value
- [ ] `test_parse_llm_confidence_confidence_present_in_answer_sentence` — REQ-604: the parser correctly extracts confidence when the LLM response contains the confidence level embedded in a sentence (e.g., `"Based on the documents, my confidence is high."`)

### Known test gaps (to note in Phase D agent output)
- Citation coverage calculation (the citation signal) depends on fuzzy sentence-level matching between the answer and retrieved document text — the matching algorithm's boundary behavior (partial overlap, near-duplicate sentences) is difficult to test precisely without knowing the similarity threshold used.
- The exact downward correction mapping for `"high"` (e.g., 0.80 vs. 0.85) is not fixed in the spec — Phase D agent must read the engineering guide's documented mapping table, not the source file.

### Pytest command
```bash
cd /home/juansync7/RAG && python -m pytest tests/retrieval/test_confidence_scoring_coverage.py -v
# Expected: FAIL (new tests — implementation exists but these are new coverage tests)
# Phase E will confirm ALL PASS after full suite verification
```

---

## Module: Confidence Routing Engine

**Source:** `src/retrieval/confidence/engine.py`
**Engineering Guide Section:** `docs/retrieval/RETRIEVAL_GENERATION_ENGINEERING_GUIDE.md` → Section 3: `src/retrieval/confidence/engine.py`
**Phase 0 contracts:** `src/retrieval/confidence/types.py`, `src/retrieval/guardrails/types.py`
**FR coverage:** REQ-706, REQ-701
**Phase D test file:** `tests/retrieval/test_pipeline_routing_coverage.py`

### Isolation contract for this module's Phase D agent

Agent input (ONLY these):
1. Module section from `RETRIEVAL_GENERATION_ENGINEERING_GUIDE.md` for `src/retrieval/confidence/engine.py` (Purpose, Error behavior, Test guide sub-sections)
2. Phase 0 contracts: `src/retrieval/confidence/types.py`, `src/retrieval/guardrails/types.py`
3. FR numbers: REQ-706, REQ-701

Must NOT receive: `src/retrieval/confidence/engine.py`, any Phase A test files.

### Error behavior tests
(derived from engineering guide's "Error behavior" sub-section)

- [ ] `test_route_re_retrieve_attempt_exceeds_1_produces_block_not_loop` — REQ-706: when the routing engine is called with `re_retrieve_count=1` already set on the state and composite confidence is still in the 0.50–0.70 range, the engine routes to BLOCK rather than issuing a second re-retrieval
- [ ] `test_route_re_retrieve_count_never_exceeds_1` — REQ-706: the engine enforces at most one re-retrieval attempt — verified by asserting that the `re_retrieve_count` in the returned state never exceeds 1 after routing
- [ ] `test_route_does_not_raise_on_any_valid_composite_and_risk_combination` — the routing function handles all four routing table rows (>0.70/LOW, >0.70/HIGH, 0.50–0.70, <0.50) without raising exceptions

### Boundary condition tests
(derived from engineering guide's "Test guide → Boundary conditions")

- [ ] `test_route_composite_exactly_0_50_routes_to_re_retrieve` — REQ-706: composite score of exactly `0.50` with `re_retrieve_count=0` routes to re-retrieve (boundary is inclusive on the 0.50–0.70 range)
- [ ] `test_route_composite_exactly_0_70_routes_to_return` — REQ-706: composite score of exactly `0.70` routes to return (boundary is inclusive on the >0.70 return zone, or exclusive — Phase D agent must confirm from engineering guide)
- [ ] `test_route_composite_0_0_routes_to_block` — REQ-706: composite = 0.0 with any risk level routes to block and produces "Insufficient documentation found" message
- [ ] `test_route_composite_1_0_low_risk_routes_to_return` — REQ-706: composite = 1.0 with LOW risk routes to return answer without warning
- [ ] `test_route_composite_1_0_high_risk_routes_to_return_with_warning` — REQ-706: composite = 1.0 with HIGH risk routes to return but includes verification warning
- [ ] `test_route_composite_0_499_routes_to_block` — REQ-706: composite just below 0.50 routes to block, not re-retrieve

### Behavior tests
(derived from engineering guide's "Test guide → Behaviors to test")

- [ ] `test_route_high_risk_always_gets_verification_warning` — REQ-706: HIGH risk classification produces a verification warning in the routing result regardless of composite confidence level (0.0, 0.60, 1.0 — all with HIGH risk produce a warning)
- [ ] `test_route_low_risk_above_threshold_no_warning` — REQ-706: LOW risk with composite > 0.70 does NOT include a verification warning
- [ ] `test_route_medium_risk_above_threshold_no_warning` — REQ-706: MEDIUM risk with composite > 0.70 does NOT include a verification warning
- [ ] `test_route_block_produces_insufficient_documentation_message` — REQ-706: routing to BLOCK produces the exact string `"Insufficient documentation found"` (or as documented in engineering guide) in the returned result
- [ ] `test_route_re_retrieve_sets_broader_params_on_state` — REQ-706: when routing to re-retrieve, the returned state includes broadened search parameters (e.g., increased `search_limit` or relaxed `alpha`) — Phase D agent confirms parameter names from engineering guide
- [ ] `test_route_re_retrieve_increments_count_on_state` — REQ-706: the `re_retrieve_count` field in the returned state is incremented by 1 after a re-retrieve routing decision
- [ ] `test_route_second_retrieval_confidence_above_threshold_returns_answer` — REQ-706: if re-retrieval raises composite from 0.45 to 0.72, the engine routes to return; verified with two sequential routing calls on the same state

### Known test gaps (to note in Phase D agent output)
- The re-retrieval parameter broadening logic (what specifically changes in search parameters) may not be observable without integration test — unit test can only verify that the state reflects changed parameters, not that the broader search produces better results.
- The exact boundary condition for composite = 0.70 (inclusive vs. exclusive for the return zone) is ambiguous in the spec table — Phase D agent must confirm from the engineering guide and annotate the boundary test accordingly.

### Pytest command
```bash
cd /home/juansync7/RAG && python -m pytest tests/retrieval/test_pipeline_routing_coverage.py -v
# Expected: FAIL (new tests — implementation exists but these are new coverage tests)
# Phase E will confirm ALL PASS after full suite verification
```

---

## Module: Post-Generation Guardrail

**Source:** `src/retrieval/guardrails/post_generation.py`
**Engineering Guide Section:** `docs/retrieval/RETRIEVAL_GENERATION_ENGINEERING_GUIDE.md` → Section 3: `src/retrieval/guardrails/post_generation.py`
**Phase 0 contracts:** `src/retrieval/guardrails/types.py`, `src/retrieval/confidence/types.py`
**FR coverage:** REQ-701, REQ-702, REQ-703, REQ-704, REQ-705, REQ-706
**Phase D test file:** `tests/retrieval/test_post_generation_guardrail_coverage.py`

### Isolation contract for this module's Phase D agent

Agent input (ONLY these):
1. Module section from `RETRIEVAL_GENERATION_ENGINEERING_GUIDE.md` for `src/retrieval/guardrails/post_generation.py` (Purpose, Error behavior, Test guide sub-sections)
2. Phase 0 contracts: `src/retrieval/guardrails/types.py`, `src/retrieval/confidence/types.py`
3. FR numbers: REQ-701, REQ-702, REQ-703, REQ-704, REQ-705, REQ-706

Must NOT receive: `src/retrieval/guardrails/post_generation.py`, any Phase A test files.

### Error behavior tests
(derived from engineering guide's "Error behavior" sub-section)

- [ ] `test_guardrail_never_raises_returns_post_guardrail_result` — REQ-701–REQ-706: the guardrail function does not raise any exception for any valid input combination — always returns a `PostGuardrailResult` typed result
- [ ] `test_guardrail_pii_detection_failure_defaults_to_no_redaction_with_warning` — REQ-703: if the PII detection sub-step fails internally (e.g., NER model unavailable), the guardrail falls back to returning the answer unredacted and logs a warning, rather than raising or blocking the answer
- [ ] `test_guardrail_citation_coverage_calculation_failure_defaults_to_low_coverage` — REQ-702: if citation coverage computation fails, the guardrail defaults to low coverage (conservative, not neutral) — Phase D agent confirms exact fallback from engineering guide
- [ ] `test_guardrail_empty_answer_string_does_not_raise` — REQ-704: an empty answer string passes through all guardrail steps without raising

### Boundary condition tests
(derived from engineering guide's "Test guide → Boundary conditions")

- [ ] `test_guardrail_answer_with_no_citations_all_sentences_flagged` — REQ-702: an answer with zero citations (citation coverage = 0.0) results in all factual sentences being flagged as ungrounded
- [ ] `test_guardrail_answer_with_100_percent_citation_coverage_no_flags` — REQ-702: an answer where every sentence is grounded in a retrieved chunk produces citation coverage = 1.0 and no ungrounded-sentence flags
- [ ] `test_guardrail_empty_answer_passes_sanitization_unchanged` — REQ-704: empty string input to output sanitization returns an empty string (no artifact insertion)
- [ ] `test_guardrail_answer_with_all_pii_types_all_redacted` — REQ-703: an answer containing one email, one phone number, one SSN/employee ID, and one person name has all four types redacted to their typed placeholders
- [ ] `test_guardrail_answer_with_no_pii_unchanged` — REQ-703: an answer containing no PII passes through the redaction step without modification
- [ ] `test_guardrail_composite_exactly_0_50_triggers_re_retrieve` — REQ-706: composite = 0.50 produced by the guardrail's confidence calculation routes to re-retrieve (boundary test matching engine.py contract)
- [ ] `test_guardrail_composite_exactly_0_70_routes_to_return` — REQ-706: composite = 0.70 routes to return

### Behavior tests
(derived from engineering guide's "Test guide → Behaviors to test")

- [ ] `test_guardrail_email_redaction_john_smith_at_company` — REQ-703: answer `"Contact john.smith@company.com for details"` is redacted to `"Contact [EMAIL] for details"`
- [ ] `test_guardrail_phone_redaction_replaces_with_phone_placeholder` — REQ-703: answer containing a phone number pattern (e.g., `555-867-5309`) is redacted to `[PHONE]`
- [ ] `test_guardrail_ssn_redaction_replaces_with_ssn_placeholder` — REQ-703: answer containing an SSN pattern (e.g., `123-45-6789`) is redacted to `[SSN]` or equivalent typed placeholder
- [ ] `test_guardrail_person_name_redaction_replaces_with_person_placeholder` — REQ-703: answer containing a recognized person name is redacted to `[PERSON]`
- [ ] `test_guardrail_redactions_logged_for_audit` — REQ-703: each PII redaction produces an audit log entry identifying the redaction type and position (confirmed from engineering guide — Phase D agent must verify log mechanism)
- [ ] `test_guardrail_system_prompt_substring_stripped_from_answer` — REQ-704: if the generated answer contains a substring from the system prompt (e.g., `"Answer ONLY from the provided documents"`), that substring is stripped from the output
- [ ] `test_guardrail_document_marker_stripped_from_answer` — REQ-704: an answer containing `"--- Document 3 ---"` has that internal marker stripped before being returned
- [ ] `test_guardrail_unsubstituted_template_variable_stripped_from_answer` — REQ-704: an answer containing `{context}` (an unsubstituted template variable) has that artifact stripped
- [ ] `test_guardrail_high_risk_numerical_claim_not_in_docs_flagged` — REQ-705: HIGH risk answer containing `"The voltage is 3.3V"` where no retrieved document contains `"3.3V"` is flagged in the result
- [ ] `test_guardrail_high_risk_numerical_claim_with_exact_quote_match_not_flagged` — REQ-705: HIGH risk answer with a numerical claim that appears verbatim in a retrieved document is NOT flagged
- [ ] `test_guardrail_low_risk_numerical_claim_not_subject_to_additional_filtering` — REQ-705: LOW risk answer with an unsupported numerical claim is NOT flagged (additional filtering only applies to HIGH risk)
- [ ] `test_guardrail_high_risk_answer_includes_verification_warning` — REQ-705/REQ-706: any HIGH risk answer that passes routing includes `"VERIFY BEFORE IMPLEMENTATION"` (or the documented equivalent) in the final output
- [ ] `test_guardrail_all_six_routing_outcomes_reachable` — REQ-706: by varying composite confidence and risk level inputs, all routing outcomes (return/LOW, return+warning/HIGH, re-retrieve, block) are reachable through the guardrail

### Known test gaps (to note in Phase D agent output)
- Person NER detection accuracy depends on an external NER model — unit tests can only verify that a well-known person name (e.g., `"John Smith"`) triggers redaction; model accuracy for ambiguous names is not unit-testable.
- System prompt leak detection is heuristic (substring matching) — tests can only cover exact substring matches, not semantic paraphrasing of system prompt content.
- Citation coverage fuzzy matching threshold: sentence-level grounding tests are sensitive to the similarity metric and threshold — Phase D agent must confirm the threshold from the engineering guide before writing boundary assertions.

### Pytest command
```bash
cd /home/juansync7/RAG && python -m pytest tests/retrieval/test_post_generation_guardrail_coverage.py -v
# Expected: FAIL (new tests — implementation exists but these are new coverage tests)
# Phase E will confirm ALL PASS after full suite verification
```

---

## Module: Observability Tracing

**Source:** `src/retrieval/observability/tracing.py`
**Engineering Guide Section:** `docs/retrieval/RETRIEVAL_GENERATION_ENGINEERING_GUIDE.md` → Section 3: `src/retrieval/observability/tracing.py`
**Phase 0 contracts:** `src/retrieval/observability/types.py`
**FR coverage:** REQ-801, REQ-802, REQ-803
**Phase D test file:** `tests/retrieval/test_observability_coverage.py`

### Isolation contract for this module's Phase D agent

Agent input (ONLY these):
1. Module section from `RETRIEVAL_GENERATION_ENGINEERING_GUIDE.md` for `src/retrieval/observability/tracing.py` (Purpose, Error behavior, Test guide sub-sections)
2. Phase 0 contracts: `src/retrieval/observability/types.py`
3. FR numbers: REQ-801, REQ-802, REQ-803

Must NOT receive: `src/retrieval/observability/tracing.py`, any Phase A test files.

### Error behavior tests
(derived from engineering guide's "Error behavior" sub-section)

- [ ] `test_tracing_failure_does_not_crash_pipeline` — REQ-801: if the tracing write operation fails (e.g., trace store is unavailable), the pipeline continues and returns a result — tracing is best-effort and must not propagate exceptions to the caller
- [ ] `test_tracing_failure_logs_warning_not_error` — REQ-801: a tracing failure produces a WARNING-level log entry, not an ERROR or exception that would interrupt processing
- [ ] `test_start_trace_always_returns_trace_id` — REQ-801: `start_trace()` returns a non-empty trace ID string even if the underlying store is unavailable (may return a local ID that will not be persisted)

### Boundary condition tests
(derived from engineering guide's "Test guide → Boundary conditions")

- [ ] `test_trace_with_zero_stages_produces_valid_trace_object` — REQ-801: a trace that has no stage records (pipeline short-circuited before any stage ran) is a valid trace with a trace ID, risk level, and empty stage list
- [ ] `test_trace_with_all_seven_stages_produces_7_stage_records` — REQ-802: a trace populated with all 7 pipeline stages (query processing, pre-retrieval guardrail, retrieval, reranking, document formatting, generation, post-generation guardrail) contains exactly 7 stage records
- [ ] `test_trace_stage_latency_at_zero_ms` — REQ-802: a stage with measured latency of 0ms is recorded without error (boundary for timing)
- [ ] `test_trace_confidence_signal_at_0_0` — REQ-802: a stage with confidence = 0.0 is recorded correctly
- [ ] `test_trace_confidence_signal_at_1_0` — REQ-802: a stage with confidence = 1.0 is recorded correctly
- [ ] `test_alert_threshold_composite_confidence_exactly_at_0_60` — REQ-803: average composite confidence of exactly 0.60 does NOT trigger the below-0.60 alert (boundary is exclusive below 0.60)
- [ ] `test_alert_threshold_composite_confidence_just_below_0_60` — REQ-803: average composite confidence of 0.5999 triggers the below-0.60 alert

### Behavior tests
(derived from engineering guide's "Test guide → Behaviors to test")

- [ ] `test_every_trace_has_unique_trace_id` — REQ-801: two successive calls to `start_trace()` produce different trace ID strings
- [ ] `test_trace_includes_risk_level` — REQ-801: the trace object includes the risk level from the pre-retrieval guardrail classification
- [ ] `test_trace_retrievable_by_id` — REQ-801: a trace that has been finalized can be retrieved by its trace ID from the trace store
- [ ] `test_trace_query_processing_stage_captures_required_metrics` — REQ-802: the query processing stage record includes `reformulation_count`, `confidence_score`, and `action_taken` fields
- [ ] `test_trace_pre_retrieval_stage_captures_required_metrics` — REQ-802: the pre-retrieval guardrail stage record includes `validation_pass`, `risk_classification`, and `pii_detections` fields
- [ ] `test_trace_retrieval_stage_captures_required_metrics` — REQ-802: the retrieval stage record includes `search_latency`, `result_count`, `filter_hit_rate`, and `kg_expansion_terms` fields
- [ ] `test_trace_reranking_stage_captures_required_metrics` — REQ-802: the reranking stage record includes `score_min`, `score_max`, `score_mean`, and `top_1_score` fields
- [ ] `test_trace_document_formatting_stage_captures_required_metrics` — REQ-802: the document formatting stage record includes `chunk_count` and `version_conflicts_detected` fields
- [ ] `test_trace_generation_stage_captures_required_metrics` — REQ-802: the generation stage record includes `generation_latency`, `llm_confidence`, and `token_count` fields
- [ ] `test_trace_post_generation_stage_captures_required_metrics` — REQ-802: the post-generation guardrail stage record includes `composite_confidence`, `citation_coverage`, `pii_redactions`, and `routing_action` fields
- [ ] `test_trace_metrics_are_structured_not_embedded_in_log_strings` — REQ-802: stage metrics are returned as typed fields (key-value), not as formatted log message strings
- [ ] `test_alert_triggered_composite_confidence_below_0_60` — REQ-803: when average composite confidence over the configured window drops below 0.60, an alert record is generated with `metric_name`, `current_value`, `threshold`, and `time_window` fields
- [ ] `test_alert_triggered_re_retrieval_rate_exceeds_30_percent` — REQ-803: when re-retrieval rate exceeds 30% over the configured window, an alert is triggered
- [ ] `test_alert_not_triggered_when_below_threshold` — REQ-803: all metrics within normal bounds produce no alerts
- [ ] `test_alert_includes_metric_name_current_value_threshold_time_window` — REQ-803: a triggered alert record contains all four required fields: metric name, current value, threshold, and time window

### Known test gaps (to note in Phase D agent output)
- Alerting threshold testing requires simulating a sustained metric window (e.g., 100 queries over a rolling time period) — unit tests can only test the threshold evaluation logic in isolation with a pre-built metric window; sustained production behavior is not unit-testable.
- Trace store retrieval tests (`test_trace_retrievable_by_id`) may require a mock or in-memory trace store — if the engineering guide specifies an external store (e.g., PostgreSQL, Redis), this test requires a mock and is not a pure unit test.
- `test_tracing_failure_does_not_crash_pipeline` depends on the tracing write being wrapped in a try/except in the production code — if the engineering guide documents a different fault isolation mechanism, the test strategy must be adjusted.

### Pytest command
```bash
cd /home/juansync7/RAG && python -m pytest tests/retrieval/test_observability_coverage.py -v
# Expected: FAIL (new tests — implementation exists but these are new coverage tests)
# Phase E will confirm ALL PASS after full suite verification
```

---

## Module: Retry Wrapper

**Source:** `src/retrieval/retry.py`
**Engineering Guide Section:** `docs/retrieval/RETRIEVAL_GENERATION_ENGINEERING_GUIDE.md` → Section 3: `src/retrieval/retry.py`
**Phase 0 contracts:** none (retry is a decorator — no Phase 0 type file)
**FR coverage:** REQ-605, REQ-902
**Phase D test file:** `tests/retrieval/test_retry_logic_coverage.py`

### Isolation contract for this module's Phase D agent

Agent input (ONLY these):
1. Module section from `RETRIEVAL_GENERATION_ENGINEERING_GUIDE.md` for `src/retrieval/retry.py` (Purpose, Error behavior, Test guide sub-sections)
2. Phase 0 contracts: none
3. FR numbers: REQ-605, REQ-902

Must NOT receive: `src/retrieval/retry.py`, any Phase A test files.

### Error behavior tests
(derived from engineering guide's "Error behavior" sub-section)

- [ ] `test_retry_all_attempts_exhausted_returns_fallback_not_raises` — REQ-605: when all retry attempts fail (max_retries=3, all 3 fail), the wrapper calls the fallback function and returns its value rather than re-raising the last exception
- [ ] `test_retry_all_attempts_exhausted_fallback_called_exactly_once` — REQ-605: the fallback is called exactly once after exhausting all retries (not once per retry attempt)
- [ ] `test_retry_first_attempt_success_no_retry_no_fallback` — REQ-605: when the first call succeeds, no retry is attempted and the fallback is never called
- [ ] `test_retry_max_retries_0_no_retry_on_failure` — REQ-605: with `max_retries=0`, a failing call is not retried — falls back immediately after the first failure
- [ ] `test_retry_non_retryable_exception_does_not_retry` — REQ-902: if the wrapped function raises an exception type not in the retryable exceptions list, the wrapper re-raises immediately without retrying

### Boundary condition tests
(derived from engineering guide's "Test guide → Boundary conditions")

- [ ] `test_retry_max_retries_0_single_failure_calls_fallback` — REQ-605: `max_retries=0` means zero retry attempts — first failure immediately triggers fallback
- [ ] `test_retry_max_retries_1_one_retry_then_fallback` — REQ-605: `max_retries=1` allows exactly one retry attempt after the initial failure; if that retry also fails, fallback is called
- [ ] `test_retry_transient_failure_first_two_then_success` — REQ-605: a function that fails on attempts 1 and 2 but succeeds on attempt 3 (with default `max_retries=3`) returns the successful result without calling fallback
- [ ] `test_retry_transient_failure_exactly_at_max_retries` — REQ-605: with `max_retries=3`, a function that fails on all 3 retry attempts (4 total calls) triggers fallback — verified by counting mock call count
- [ ] `test_retry_backoff_first_interval_less_than_second` — REQ-605: the sleep duration between attempt 1→2 is strictly less than the sleep duration between attempt 2→3 (exponential backoff confirmed)

### Behavior tests
(derived from engineering guide's "Test guide → Behaviors to test")

- [ ] `test_retry_backoff_intervals_increase_exponentially` — REQ-605: with mocked time, sleep durations between retry attempts follow the configured exponential backoff formula (e.g., base × 2^n)
- [ ] `test_retry_backoff_capped_at_max_backoff` — REQ-605: with a configured `max_backoff` cap, the sleep duration never exceeds `max_backoff` regardless of retry attempt number
- [ ] `test_retry_count_equals_max_retries_before_fallback` — REQ-605: the number of times the wrapped function is called before fallback equals `1 (initial) + max_retries`
- [ ] `test_retry_configurable_max_retries` — REQ-605: the `max_retries` parameter is respected — changing from 3 to 5 produces 5 retry attempts before fallback
- [ ] `test_retry_configurable_base_backoff` — REQ-605: the `base_backoff` parameter is respected — changing the base interval changes the sleep durations (verified with mocked time)
- [ ] `test_retry_graceful_degradation_llm_unavailable` — REQ-902: when the LLM is unavailable (all retries return timeout), the fallback returns retrieved documents without synthesis (confirmed from engineering guide — Phase D agent verifies exact fallback behavior)
- [ ] `test_retry_fallback_return_value_passed_through_to_caller` — REQ-902: the return value of the fallback function is the return value of the decorated call — no swallowing or wrapping
- [ ] `test_retry_retry_count_logged_on_each_attempt` — REQ-605: each retry attempt produces a log entry indicating the attempt number and exception type (confirmed from engineering guide)

### Known test gaps (to note in Phase D agent output)
- Actual sleep timing is non-deterministic and cannot be verified in unit tests without mocking `time.sleep` — all backoff interval tests must use a mock. Phase D agent should assert the mock was called with the correct argument rather than measuring real elapsed time.
- The exact exponential backoff formula (base × 2^n vs. base × 2^(n-1) vs. other variants) is not specified in the spec — Phase D agent must read the engineering guide to determine the formula before writing the exponential verification test.
- Whether the fallback behavior for LLM unavailability (returning raw retrieved documents) is implemented in the retry wrapper itself or in the calling pipeline stage is ambiguous from the spec — Phase D agent must confirm the responsibility boundary from the engineering guide.

### Pytest command
```bash
cd /home/juansync7/RAG && python -m pytest tests/retrieval/test_retry_logic_coverage.py -v
# Expected: FAIL (new tests — implementation exists but these are new coverage tests)
# Phase E will confirm ALL PASS after full suite verification
```

---

## Phase D dispatch order

All Phase D tasks run in parallel (no dependencies between modules).

### Phase D gate (all must be complete before Phase E starts):
- [ ] Module: Document Formatter — spec review complete
- [ ] Module: Version Conflict Detection — spec review complete
- [ ] Module: Prompt Template Loader — spec review complete
- [ ] Module: Confidence Scoring Utilities — spec review complete
- [ ] Module: Confidence Routing Engine — spec review complete
- [ ] Module: Post-Generation Guardrail — spec review complete
- [ ] Module: Observability Tracing — spec review complete
- [ ] Module: Retry Wrapper — spec review complete

---

## Requirement-to-module coverage

| Spec Requirement | Covered by Module | Phase D Test File |
|------------------|-------------------|-------------------|
| REQ-501 | Document Formatter | `test_document_formatter_coverage.py` |
| REQ-502 | Version Conflict Detection | `test_version_conflicts_coverage.py` |
| REQ-503 | Document Formatter | `test_document_formatter_coverage.py` |
| REQ-601 | Prompt Template Loader | `test_prompt_template_coverage.py` |
| REQ-602 | Prompt Template Loader | `test_prompt_template_coverage.py` |
| REQ-604 | Confidence Scoring Utilities | `test_confidence_scoring_coverage.py` |
| REQ-605 | Retry Wrapper | `test_retry_logic_coverage.py` |
| REQ-701 | Confidence Scoring Utilities + Confidence Routing Engine | `test_confidence_scoring_coverage.py`, `test_pipeline_routing_coverage.py` |
| REQ-702 | Post-Generation Guardrail | `test_post_generation_guardrail_coverage.py` |
| REQ-703 | Post-Generation Guardrail | `test_post_generation_guardrail_coverage.py` |
| REQ-704 | Post-Generation Guardrail | `test_post_generation_guardrail_coverage.py` |
| REQ-705 | Post-Generation Guardrail | `test_post_generation_guardrail_coverage.py` |
| REQ-706 | Confidence Routing Engine + Post-Generation Guardrail | `test_pipeline_routing_coverage.py`, `test_post_generation_guardrail_coverage.py` |
| REQ-801 | Observability Tracing | `test_observability_coverage.py` |
| REQ-802 | Observability Tracing | `test_observability_coverage.py` |
| REQ-803 | Observability Tracing | `test_observability_coverage.py` |
| REQ-901 | Cross-module (latency) | Integration tests (not Phase D white-box) |
| REQ-902 | Retry Wrapper + Confidence Routing Engine | `test_retry_logic_coverage.py`, `test_pipeline_routing_coverage.py` |
| REQ-903 | All modules (config externalization) | Per-module coverage tests (config loading assertions in each test file) |
