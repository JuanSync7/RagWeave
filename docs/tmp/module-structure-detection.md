### `src/ingest/doc_processing/nodes/structure_detection.py` — Structure Detection Node

**Purpose:**

This LangGraph node is the first processing stage for every document. It converts the raw file into markdown and extracts lightweight structural signals (figure references, heading count). When Docling parsing succeeds, it also captures the native `DoclingDocument` object and sets the `docling_document_available` routing flag in the pipeline state. Downstream conditional edges in the Phase 1 DAG read this flag to skip `text_cleaning_node` and `document_refactoring_node` for Docling-parsed documents — those nodes are redundant when a structured `DoclingDocument` is available. (FR-2003, FR-2011, FR-2013)

**How it works:**

`structure_detection_node` receives a `DocumentProcessingState` and returns a partial state update. Its logic:

1. Read `config.enable_docling_parser` from `state["runtime"].config`.

2. **Docling path** (if `enable_docling_parser` is `True`):
   - Call `parse_with_docling(Path(state["source_path"]), parser_model=..., artifacts_path=..., vlm_mode=config.vlm_mode)`.
   - On success: set `parsed_text = parsed.text_markdown`, `figures = parsed.figures`, `headings = parsed.headings`, `docling_doc = parsed.docling_document`, `docling_document_available = True`.
   - On exception in strict mode (`config.docling_strict = True`): return an error payload with `should_skip=True` to short-circuit the workflow. No further nodes run for this document.
   - On exception in non-strict mode: fall back to regex heuristics. `figures` and `headings` are extracted from `raw_text` using compiled regex patterns. `docling_document_available` stays `False`.

3. **Regex fallback** (if `enable_docling_parser` is `False`): same regex-based extraction, `docling_document_available` stays `False`.

4. Build the `structure` dict with `has_figures`, `figures` (capped at `_MAX_FIGURES = 32`), `heading_count`, `docling_enabled`, `docling_model`, and `docling_document_available`.

5. Build the return update dict: always includes `raw_text`, `structure`, `processing_log`. **Includes `docling_document` only if `docling_document_available` is `True`.** This conditional inclusion is deliberate — the key is absent from state for non-Docling documents, which `chunking_node` checks with `state.get("docling_document")`.

```python
# The conditional state key inclusion (from actual source):
update: dict[str, Any] = {
    "raw_text": parsed_text,
    "structure": structure,
    "processing_log": append_processing_log(state, "structure_detection:ok"),
}
if docling_document_available:
    update["docling_document"] = docling_doc
return update
```

The `_FIGURE_PATTERN` regex matches `"Figure N"` and `"Fig. N"` patterns (case-insensitive). The `_HEADING_PATTERN` regex matches markdown headings (`# text`) and numbered headings (`1.2 Title`).

**Key design decisions:**

| Decision | Alternatives Considered | Why This Choice |
|----------|------------------------|-----------------|
| Only include `docling_document` in the return dict when it was successfully produced | Always include the key with `None` as fallback | `state.get("docling_document")` returning `None` is ambiguous — did Docling fail, or was it never attempted? Absent key makes the absence unambiguous and lets `chunking_node` use a simple `is not None` check. |
| Store `docling_document_available` inside the `structure` dict (not as a top-level state key) | Add it as a direct TypedDict field on `DocumentProcessingState` | The `structure` dict already carries structural metadata (figures, headings, docling_enabled). Adding the routing flag here groups related signals. Adding it as a top-level state field would widen the public TypedDict contract for one internal routing value. |
| Non-strict mode falls back silently to regex | Non-strict mode retries with a simpler Docling configuration | Retry adds latency without a clear success probability. Regex fallback is deterministic and immediate. The document still gets processed, just with lower structural fidelity. |
| `_MAX_FIGURES = 32` cap on figures list | No cap; dynamic cap from config | A hardcoded cap prevents pathological documents (e.g., a 500-page PDF with 400 figures) from bloating state memory. 32 is sufficient for metadata display. |

**Configuration:**

| Parameter | Type | Default | Valid Range / Options | Effect |
|-----------|------|---------|----------------------|--------|
| `config.enable_docling_parser` | `bool` | `True` (from env) | `True` or `False` | When `False`, regex heuristics are used exclusively. `docling_document_available` is always `False`. |
| `config.docling_model` | `str` | `"docling-parse-v2"` | Any non-empty string | Passed to `parse_with_docling` as `parser_model` for telemetry. |
| `config.docling_artifacts_path` | `str` | `""` | Filesystem path or empty | Passed to `parse_with_docling` as `artifacts_path`. |
| `config.docling_strict` | `bool` | `True` (from env) | `True` or `False` | When `True`, a Docling parse failure returns `should_skip=True`, aborting the document. When `False`, falls back to regex. |
| `config.vlm_mode` | `str` | `"disabled"` | `"disabled"`, `"builtin"`, `"external"` | Passed to `parse_with_docling` as `vlm_mode`. `"builtin"` causes SmolVLM to run during `DocumentConverter.convert()`. |

**Error behavior:**

On Docling parse failure with `docling_strict=True`: returns `{"errors": ["docling_parse_failed:<source_name>:<exc>"], "should_skip": True, "processing_log": [...]}`. The orchestrator (`run_document_processing`) detects `should_skip=True` and stops the pipeline for this document.

On Docling parse failure with `docling_strict=False`: silently falls back to regex extraction. No error is added to state. The `processing_log` will not contain `"structure_detection:ok"` — it will contain `"structure_detection:failed"` only in the strict path.

This node does not raise exceptions to its callers. All errors are either captured into state or trigger the `should_skip` short-circuit.
