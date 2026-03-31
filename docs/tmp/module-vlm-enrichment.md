### `src/ingest/embedding/nodes/vlm_enrichment.py` — Post-Chunking VLM Enrichment Node

**Purpose:**

This LangGraph node runs after `chunking_node` and replaces `![alt](src)` image placeholder patterns in chunk text with VLM-generated descriptions. It is the post-chunking VLM enrichment step for the `"external"` VLM mode. For `"disabled"` and `"builtin"` modes, the node is a no-op — it returns the chunk list unchanged and appends `"vlm_enrichment:skipped"` to the processing log.

The node exists as an always-present stage in the embedding DAG: the graph always includes it, and the mode check happens inside the node. This means the DAG topology is stable regardless of configuration. (FR-2201–FR-2209)

**How it works:**

`vlm_enrichment_node(state)` is the LangGraph node entry point:

1. Read `config.vlm_mode` from `state["runtime"].config`.
2. If `vlm_mode != "external"`: return immediately with `{"chunks": state.get("chunks", []), "processing_log": ...:skipped}`. This covers both `"disabled"` and `"builtin"` — the builtin mode's descriptions were already embedded in the `DoclingDocument` at parse time by SmolVLM.
3. If `vlm_mode == "external"`:
   - Initialize `figures_processed_count = 0` and an empty `result_chunks` list.
   - Iterate over every `chunk` in `state.get("chunks", [])`.
   - For each chunk, call `_enrich_chunk_external(chunk, config, figures_processed_count, source_uri=source_uri)`, which returns `(enriched_chunk, new_count)`.
   - Append `enriched_chunk` to `result_chunks`, update `figures_processed_count`.
   - Return `{"chunks": result_chunks, "processing_log": ...:external:ok}`.
   - On any outer exception: log the error and return the original unchanged chunks with `...:external:error`.

**`_enrich_chunk_external(chunk, config, figures_processed_count, source_uri)`:**
1. If `figures_processed_count >= config.vision_max_figures`: return the original chunk unchanged (budget exhausted).
2. Find all `![alt](src)` placeholders via `_find_image_placeholders(chunk.text)`.
3. If none found: return unchanged.
4. For each placeholder match:
   a. If `new_count >= config.vision_max_figures`: stop.
   b. Re-locate the placeholder in the current (possibly already modified) text by re-searching with `_IMAGE_REF_PATTERN`. If not found (already replaced), continue.
   c. Call `_extract_image_candidates(original_placeholder, source_path=..., max_figures=remaining_budget, max_image_bytes=...)` to resolve the image path and read its bytes.
   d. If no candidates (missing file, oversized, remote URL): continue, leave placeholder.
   e. Call `_describe_image(candidate, config)` via the vision support layer.
   f. On failure: log a warning, continue with original placeholder.
   g. On success: call `_replace_placeholder(current_text, recheck, description_text)` to replace the matched span. Increment `new_count`.
5. If `current_text == chunk.text`: return original object unchanged.
6. Otherwise: `copy.copy(chunk)` with `enriched.text = current_text` and return the copy.

**`_find_image_placeholders(chunk_text)`:** returns `list[re.Match]` using `_IMAGE_REF_PATTERN.finditer()` from `src/ingest/support/vision.py`.

**`_replace_placeholder(chunk_text, match, description)`:** replaces exactly the matched span — `chunk_text[:match.start()] + description + chunk_text[match.end():]`. Surrounding text is preserved byte-for-byte.

```python
# The re-scan loop after each replacement (from actual source):
# After replacing a placeholder, the text offsets for later matches shift.
# So each iteration re-scans from the known position of the original placeholder.
recheck = _IMAGE_REF_PATTERN.search(current_text, current_match_pos)
if recheck is None or recheck.group(0) != original_placeholder:
    continue
```

**Key design decisions:**

| Decision | Alternatives Considered | Why This Choice |
|----------|------------------------|-----------------|
| Node always present in DAG; mode check is internal no-op | Conditional DAG edge to skip node when `vlm_mode != "external"` | A stable DAG topology is simpler to reason about and test. Internal no-op avoids conditional graph wiring that would need to change if the mode changes at runtime. |
| Re-scan text after each replacement | Build all replacements up front, apply in reverse order | Applying in reverse order requires sorting matches by position. Re-scanning is simpler and handles edge cases where two placeholders are adjacent. |
| `copy.copy(chunk)` for enriched chunks | Mutate in-place; deep copy | Shallow copy preserves the metadata dict reference (acceptable since we only modify `text`). Deep copy would duplicate large metadata dicts unnecessarily. Mutation in-place could cause issues if the original chunk is referenced elsewhere. |
| Per-chunk failure is non-fatal (warning, preserve original) | Fatal error halts entire document on VLM failure | A single image's VLM failure should not prevent 49 other chunks from being embedded. The placeholder text still signals to the embedding model that a figure exists. |
| Respect `vision_max_figures` budget across all chunks | No per-document limit | External VLM calls have API cost and latency. A document with 50 figures could dominate pipeline time and cost without a limit. |

**Configuration:**

| Parameter | Type | Default | Valid Range / Options | Effect |
|-----------|------|---------|----------------------|--------|
| `config.vlm_mode` | `str` | `"disabled"` | `"disabled"`, `"builtin"`, `"external"` | Only `"external"` triggers actual VLM calls. All other values result in an immediate no-op. |
| `config.vision_max_figures` | `int` | `4` (from env) | Positive integer | Maximum number of image placeholders processed per document across all chunks. Once this count is reached, remaining placeholders are left unchanged. |
| `config.vision_max_image_bytes` | `int` | `3145728` (3 MB, from env) | Positive integer | Maximum image file size to pass to the VLM. Larger images are skipped. Effective minimum enforced internally: `max(16_384, config.vision_max_image_bytes)`. |
| `config.vision_timeout_seconds` | `int` | `60` (from env) | Positive integer | Timeout for each VLM API call, passed to the vision support layer. |
| `config.vision_max_tokens` | `int` | `220` (from env) | Positive integer | Maximum tokens in the VLM response, passed to the vision support layer. |

**Error behavior:**

`vlm_enrichment_node` never raises to its callers. All exceptions from `_enrich_chunk_external`, `_extract_image_candidates`, and `_describe_image` are caught and logged. The original chunk text is preserved on any failure.

The outer `except Exception` in `vlm_enrichment_node` catches unexpected errors (e.g., iteration failure) and returns the entire original chunk list unchanged, appending `"vlm_enrichment:external:error"` to the processing log.

Per-placeholder failures produce `logger.warning(...)` entries but no `errors` list additions — they are non-fatal by design (FR-2207).
