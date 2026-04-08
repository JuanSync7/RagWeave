### `src/ingest/support/docling.py` — Docling Page Image Extraction (Visual Track Addition)

**Purpose:**

This module is an additive extension to the existing Docling parsing integration. The base module converts documents to markdown for ingestion; the visual track addition extends it to also extract per-page PIL images during the same parse pass.

Two fields are added to `DoclingParseResult`: `page_images` (a list of `PIL.Image` objects, one per extracted page) and `page_count` (the total number of pages in the source document). A new `generate_page_images` boolean parameter gates this extraction in `parse_with_docling`.

Page image extraction must happen at parse time — not afterward — because Docling's `generate_page_images` option must be set on `PdfPipelineOptions` **before** `convert()` is called. The rendered page images exist only in memory as part of the `ConversionResult` and are not persisted in the serialized `DoclingDocument` JSON. Re-running conversion purely to get images would be expensive and architecturally undesirable. By gating on `enable_visual_embedding` in `IngestionConfig` (FR-107), the cost (VRAM, compute) is incurred only when the visual track is active.

After parse, the extracted images flow into `EmbeddingPipelineState["page_images"]` and are consumed by the downstream `visual_embedding_node`.

---

**How it works:**

1. **`generate_page_images` parameter added to `parse_with_docling`.**
   The function signature gains a new keyword argument `generate_page_images: bool = False` (FR-107). When `False`, no page extraction logic runs; `page_images` stays empty and `page_count` stays 0.

2. **`PdfPipelineOptions` configured before conversion.**
   When `generate_page_images=True`, `PdfPipelineOptions(generate_page_images=True)` is constructed and passed to the Docling converter before `convert()` is called. This is the only point at which page rendering can be activated — the option is consumed at converter construction time and cannot be injected post-hoc.

3. **`_extract_page_images_from_result` tries two access strategies.**
   After `convert()` returns, the private helper `_extract_page_images_from_result(conv_result)` attempts to locate page image data:
   - **Strategy 1:** `conv_result.pages` — iterates the top-level pages list/dict on the `ConversionResult`, accessing `.image.pil_image` on each page item.
   - **Strategy 2:** `conv_result.document.pages` — falls back to page items on the embedded `DoclingDocument` object, using the same `.image.pil_image` access pattern.

4. **Each image converted to RGB.**
   For every successfully accessed page image, `image.convert("RGB")` is called to normalize the color space (FR-204). Individual page failures (missing image attribute, conversion error) are caught, a warning is logged, and that page is skipped without raising.

5. **`page_count` set regardless of extraction success.**
   The helper returns a `(page_images_list, page_count)` tuple. `page_count` reflects the total pages found in the document structure, even if some or all individual page image conversions failed (FR-205). The caller assigns both into the `DoclingParseResult`.

The `DoclingParseResult` field additions introduced by this extension are:

```python
@dataclass
class DoclingParseResult:
    text_markdown: str
    has_figures: bool
    figures: list[str]
    headings: list[str]
    parser_model: str
    docling_document: Any = None          # docling_core.types.doc.DoclingDocument
    page_images: list[Any] = field(default_factory=list)  # FR-201, FR-204
    page_count: int = 0                   # FR-205
```

---

**Key design decisions:**

| Decision | Alternatives Considered | Why This Choice |
|----------|------------------------|-----------------|
| Gate extraction behind `generate_page_images=False` default | Always extract page images during every parse | VRAM and compute cost should only be paid when the visual track is active. Leaving the default `False` makes the visual track opt-in with zero regression for existing callers. |
| Extract images during the Docling parse pass | Extract images in a separate post-parse step using a different renderer | Docling's `generate_page_images` flag must be set on `PdfPipelineOptions` before `convert()`. Page images are not persisted in the `DoclingDocument` JSON and cannot be reconstructed later without re-running the full conversion. |
| Two-strategy fallback in `_extract_page_images_from_result` | Single access path only | Docling's internal API has varied across versions. `conv_result.pages` and `conv_result.document.pages` expose the same data through different object paths. Using both strategies improves robustness across Docling releases without requiring a strict version pin. |
| Silent failure on image extraction (no exception raised) | Raise an exception when extraction fails | The text-track pipeline must not be blocked by image extraction failures. Page images are enrichment; the document's markdown content is the primary output. Logging a warning and returning `page_images=[]` lets the pipeline continue gracefully. |
| `page_count` always set, even on partial failure | Set `page_count` only when all images extracted successfully | Callers may need `page_count` for telemetry, logging, or downstream routing regardless of whether images are available. Tying `page_count` to extraction success would silently lose document structure information on partial failures. |

---

**Configuration:**

| Parameter | Type | Default | Effect |
|-----------|------|---------|--------|
| `generate_page_images` | `bool` | `False` | When `True`, sets `PdfPipelineOptions(generate_page_images=True)` before conversion and extracts `PIL.Image` (RGB) objects from each page of the `ConversionResult`. Derived from `IngestionConfig.enable_visual_embedding` (FR-107). When `False`, `page_images` is empty and `page_count` is 0. |

---

**Error behavior:**

Extraction failure is silent and non-blocking:

- **Full extraction failure** (neither access strategy yields images): `page_images=[]` is returned. `page_count` is still populated from the document structure. No exception is raised. The caller receives a fully valid `DoclingParseResult` with the complete markdown text intact.
- **Individual page failure** (one page's `.image.pil_image` is missing, or `image.convert("RGB")` raises): that page is skipped with a warning log. Remaining pages continue to be processed. The final `page_images` list contains only the successfully extracted pages.
- **`page_count` invariant**: `page_count` always reflects the total number of pages detected in the document, independent of how many images were successfully extracted. This ensures downstream telemetry and routing logic receives accurate document structure information even when image extraction is partial (FR-205).

This design ensures the text-track pipeline is never blocked or degraded by failures in the visual enrichment path.
