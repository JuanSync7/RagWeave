### `src/ingest/support/docling.py` — Docling Parse Adapter

**Purpose:**

This module provides the ingestion pipeline's interface to the Docling document parser. It exports `DoclingParseResult` (the normalized output dataclass), `parse_with_docling` (the main parsing function), `ensure_docling_ready` (a pre-flight readiness check), and `warmup_docling_models` (model artifact download). The module decouples the rest of the ingestion pipeline from Docling's internal API — no other module imports from `docling` directly. After the Docling-Native Chunking redesign, `DoclingParseResult` carries the native `DoclingDocument` object alongside the existing markdown export, and `parse_with_docling` accepts a `vlm_mode` parameter to optionally activate Docling's integrated SmolVLM at parse time. (FR-2001, FR-2211)

**How it works:**

**`DoclingParseResult` dataclass** has six fields:
- `text_markdown: str` — the full document as markdown, exported via `document.export_to_markdown()`
- `has_figures: bool` — whether Docling detected any picture items
- `figures: list[str]` — lightweight labels like `"Figure 1"`, `"Figure 2"` for telemetry
- `headings: list[str]` — heading text extracted from the markdown via regex
- `parser_model: str` — the parser model identifier, for logging
- `docling_document: Any` — the native `DoclingDocument` object (type `Any` to avoid a hard `docling-core` import at module load time). `None` only in error recovery paths.

**`parse_with_docling` function** takes a file path, `parser_model`, optional `artifacts_path`, and `vlm_mode`. Its steps:

1. Lazily import `DocumentConverter` from `docling` — this keeps module-level imports cheap and avoids crashing at import time when Docling is not installed.
2. Build `converter_kwargs` — if `artifacts_path` is non-empty, pass it to the constructor.
3. If `vlm_mode == "builtin"`: lazily import `PdfPipelineOptions`, `PictureDescriptionVlmEngineOptions`, and `PdfFormatOption`. Build a `PdfPipelineOptions` with `do_picture_description=True` and `picture_description_options=PictureDescriptionVlmEngineOptions.from_preset("smolvlm")`. Add this as `format_options={InputFormat.PDF: PdfFormatOption(...)}` to `converter_kwargs`. If this import fails (SmolVLM not installed), log a warning and proceed without picture description — the parse still succeeds, just without VLM enrichment. Construct `DocumentConverter(**converter_kwargs)`.
4. If `vlm_mode != "builtin"`: construct `DocumentConverter(**converter_kwargs)` without picture description options (existing behavior).
5. Call `converter.convert(str(source_path))`. On failure, raise `RuntimeError`.
6. Extract `result.document` (the `DoclingDocument`). If `None` or missing `export_to_markdown`, raise `RuntimeError`.
7. Call `document.export_to_markdown()`. If the result is empty, raise `RuntimeError`.
8. Build `figures` list from `document.pictures`, `headings` list via `_extract_headings_from_markdown()`.
9. Return `DoclingParseResult` with `docling_document=document`.

**`warmup_docling_models` function** downloads Docling model artifacts (layout model, TableFormer). The `with_smolvlm: bool = False` parameter controls whether SmolVLM artifacts are also downloaded. Validates that the layout and tableformer directories exist after download.

**`_extract_headings_from_markdown`** is a private helper that scans markdown line-by-line for lines starting with `#` and returns the heading text.

```python
# The core conditional in parse_with_docling for builtin VLM:
if vlm_mode == "builtin":
    try:
        pipeline_options = PdfPipelineOptions()
        pipeline_options.do_picture_description = True
        pipeline_options.picture_description_options = (
            PictureDescriptionVlmEngineOptions.from_preset("smolvlm")
        )
        converter_kwargs["format_options"] = {
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
        }
    except (ImportError, Exception) as exc:
        logger.warning("vlm_mode='builtin' requested but SmolVLM setup failed (%s); "
                       "proceeding without picture description.", exc)
```

**Key design decisions:**

| Decision | Alternatives Considered | Why This Choice |
|----------|------------------------|-----------------|
| `docling_document: Any` type (not `Optional[DoclingDocument]`) | Import `DoclingDocument` from `docling-core` at module level | Using `Any` keeps `docling-core` as an optional runtime dependency. If Docling is not installed, the module still imports and the rest of the pipeline can run on the fallback path. A hard import would crash the entire system at startup. |
| Lazy import of Docling inside function bodies | Top-level import | Same rationale as above — Docling is optional. Lazy import provides a clear error message at call time rather than an obscure import failure at startup. |
| SmolVLM failure is non-fatal (warning, continues) | Fail with RuntimeError when SmolVLM cannot be configured | SmolVLM setup failure is an infrastructure issue, not a document issue. Falling back to a parse without picture description is better than failing the entire document. |
| `warmup_docling_models` accepts `with_smolvlm: bool` | Separate `warmup_smolvlm()` function | One entry point for all Docling model warmup reduces callers' cognitive load. The `with_smolvlm` flag keeps the download selective — SmolVLM artifacts are large and should only download when needed. |

**Configuration:**

| Parameter | Type | Default | Valid Range / Options | Effect |
|-----------|------|---------|----------------------|--------|
| `vlm_mode` (in `parse_with_docling`) | `str` | `"disabled"` | `"disabled"`, `"builtin"`, `"external"` | `"builtin"` activates SmolVLM at parse time via `PdfPipelineOptions.do_picture_description=True`. `"external"` and `"disabled"` leave picture description off. |
| `artifacts_path` (in `parse_with_docling`) | `str` | `""` | Filesystem path or empty string | When non-empty, passed as `DocumentConverter(artifacts_path=...)`. Controls where Docling looks for pre-downloaded model artifacts. |
| `with_smolvlm` (in `warmup_docling_models`) | `bool` | `False` | `True` or `False` | When `True`, SmolVLM model artifacts are downloaded in addition to layout and TableFormer models. Must be `True` before calling `parse_with_docling` with `vlm_mode="builtin"`. |

**Error behavior:**

`parse_with_docling` raises `RuntimeError` in these cases:
- Docling is not installed (`ImportError` wrapped in `RuntimeError`)
- `converter.convert()` raises any exception (wrapped in `RuntimeError` with the source path)
- `result.document` is `None` or lacks `export_to_markdown`
- `export_to_markdown()` returns an empty string

None of these are retried internally. Callers (`structure_detection_node`) catch `RuntimeError` and apply the non-strict fallback or propagate as a fatal error in strict mode.

`warmup_docling_models` raises `RuntimeError` if the Docling downloader is unavailable or if required model directories are absent after download. It does not catch `OSError` from `download_models`.

`ensure_docling_ready` raises `RuntimeError` if Docling is unavailable, if the artifacts path is non-empty and invalid, or if the test `DocumentConverter()` instantiation fails.
