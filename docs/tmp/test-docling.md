### `src/ingest/support/docling.py` — Docling Page Image Extraction

**Module purpose:** Additive extension to the Docling parsing integration that optionally extracts per-page PIL images and page count from PDF conversion results, controlled by a `generate_page_images` flag.

**In scope:**
- `DoclingParseResult` dataclass extension: `page_images` (list[Any]) and `page_count` (int) fields
- `parse_with_docling()` new `generate_page_images: bool = False` parameter
- `PdfPipelineOptions(generate_page_images=True)` construction and injection before `convert()`
- `_extract_page_images_from_result()` dual-strategy image extraction (Strategy 1: `conv_result.pages`, Strategy 2: `conv_result.document.pages`)
- Per-image RGB conversion via `image.convert("RGB")`
- Per-page failure handling: WARNING log + skip, no exception propagation
- `page_count` derivation from document structure (independent of image extraction success)

**Out of scope:**
- Docling internals (`PdfPipelineOptions` implementation, `convert()` behavior)
- Downstream ColQwen2 VLM embedding consumption of page images
- Non-PDF document types
- Image persistence or serialization
- Markdown text extraction (existing baseline behavior, not modified)

---

#### Happy path scenarios

| Scenario | Input | Expected output |
|----------|-------|-----------------|
| Default (no images) | `parse_with_docling(path, generate_page_images=False)` | `page_images=[]`, `page_count=0`, `text_markdown` populated, existing fields unaffected |
| 10-page PDF with images enabled | `parse_with_docling(path, generate_page_images=True)` on 10-page PDF | `len(page_images) == 10`, `page_count == 10` |
| Page count matches image count | 10-page PDF, all pages accessible | `page_count == 10`, `len(page_images) == 10` |
| RGB normalization | PDF page image in RGBA mode, `generate_page_images=True` | Returned image has exactly 3 channels (RGB mode), no exception raised |
| RGB passthrough | PDF page image already in RGB mode | Image returned as-is with RGB mode, no double-conversion error |
| Baseline text track preserved | `generate_page_images=True` on valid PDF | `text_markdown`, `has_figures`, `figures`, `headings`, `parser_model` all populated as before |
| Strategy 1 extraction | `conv_result.pages` accessible with `.image.pil_image` | Images extracted via Strategy 1; Strategy 2 not invoked |
| Strategy 2 fallback extraction | `conv_result.pages` inaccessible or empty; `conv_result.document.pages` accessible | Images extracted via Strategy 2; same result shape as Strategy 1 |
| DoclingParseResult default fields | Instantiate `DoclingParseResult(text_markdown="x", ...)` without providing `page_images`/`page_count` | `page_images == []`, `page_count == 0` |

---

#### Error scenarios

| Error type | Trigger condition | Expected behavior |
|-----------|------------------|-------------------|
| Both strategies yield no images | `conv_result.pages` and `conv_result.document.pages` both inaccessible or empty | `page_images=[]`, `page_count` still set from document structure, no exception raised |
| Single page `.image` attribute missing | One page in `conv_result.pages` lacks `.image` or `.image.pil_image` | That page skipped, WARNING logged, remaining pages returned, `len(page_images) < page_count` allowed |
| RGB conversion failure on one page | `image.convert("RGB")` raises for one page | That page skipped, WARNING logged, other pages continue unaffected |
| Full image extraction failure | All pages fail `.image.pil_image` access | `page_images=[]`, `page_count` reflects total pages, `text_markdown` unaffected, no exception to caller |
| `page_count` independent of image failures | 10-page PDF, 3 pages fail extraction | `page_count == 10`, `len(page_images) == 7` |
| `generate_page_images=True` on non-PDF | Non-PDF file passed with flag enabled | Behavior follows existing Docling `convert()` behavior; `page_images=[]`, `page_count=0` (no crash guarantee from this module) |

---

#### Boundary conditions

- **FR-201**: Exactly 10 images extracted for a 10-page PDF (not 9, not 11) — validates off-by-one in page iteration
- **FR-204 (RGBA handling)**: An image in RGBA mode (4 channels) must be converted to RGB (3 channels) before inclusion in `page_images`; resulting image must have `mode == "RGB"` and exactly 3 channels
- **FR-205 (`page_count` invariant)**: `page_count` must equal total document pages regardless of how many images were successfully extracted; it must never be derived from `len(page_images)`
- **Default field initialization**: `DoclingParseResult` constructed without `page_images` and `page_count` must use `field(default_factory=list)` so different instances do not share the same list object
- **Zero-page document**: Document with 0 pages — `page_images=[]`, `page_count=0`, no exception
- **Single-page document**: 1-page PDF — `len(page_images) == 1` (or 0 on failure), `page_count == 1`
- **`generate_page_images=False` is a complete no-op**: `PdfPipelineOptions` with image generation must NOT be constructed when flag is False; existing behavior must be identical

---

#### Integration points

- **Called by**: `src/ingest/embedding/nodes/vlm_enrichment.py` (visual track) indirectly via the ingest pipeline, which invokes `parse_with_docling()` with `generate_page_images=True` when `IngestionConfig.enable_visual_embedding=True`
- **Calls into**: Docling `DocumentConverter.convert()`, `PdfPipelineOptions`, PIL `Image.convert()`
- **Returns**: `DoclingParseResult` dataclass — callers access `.page_images` (list of PIL Image objects) and `.page_count` (int) for downstream VLM embedding
- **Config gate**: `IngestionConfig.generate_page_images` (FR-107) controls whether this extension activates; when False, result is indistinguishable from pre-extension baseline
- **Text track decoupling**: `text_markdown` and all existing fields must remain valid and complete even when image extraction fails entirely

---

#### Known test gaps

- **Live PDF conversion not tested**: Tests should mock `DocumentConverter.convert()` to avoid filesystem and Docling runtime dependencies; actual PDF rendering fidelity is out of scope for unit tests
- **Strategy 1 vs. Strategy 2 distinction in same Docling version**: Both strategies may succeed simultaneously in some Docling versions; test must explicitly mock one path unavailable to verify fallback
- **RGBA source image provenance**: Tests use synthetically constructed RGBA PIL images; real Docling RGBA output may differ in edge cases (e.g., transparency masks)
- **Concurrent/thread-safety of `page_images` list**: Not tested; list construction is sequential in the current design
- **Non-PDF page count behavior**: `page_count` derivation for DOCX or HTML inputs is not specified and not tested
- **Warning log content**: Tests verify WARNING is emitted but do not assert log message text (avoids brittleness)

---

#### Agent isolation contract (include verbatim in write-module-tests dispatch)

> **Agent isolation contract:** This agent receives ONLY:
> 1. This module test spec section
> 2. Phase 0 contract files (for import surface only)
>
> **Must NOT receive:** Source implementation files, other modules' test specs, or the engineering guide directly.
