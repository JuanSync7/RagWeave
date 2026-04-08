### `src/db/minio/store.py` — MinIO Page Image Storage (Visual Track Addition)

**Purpose:**

This section documents the two page-image functions added to the existing document store module as part of the visual embedding pipeline track: `store_page_images` and `delete_page_images`. These functions are additive extensions to a module that already handles document-level file storage (Markdown content under `docs/{source_key}/content.md`). Page image storage is kept in the same module because it shares the same MinIO client, bucket configuration, and error-handling conventions — adding a new key namespace (`pages/`) rather than a new abstraction layer. `store_page_images` serializes in-memory PIL-compatible image objects to JPEG and uploads them to MinIO under a structured key. `delete_page_images` removes all images for a document in bulk, used to clean up stale page data before re-ingesting an updated document.

---

**How it works:**

**`store_page_images`**

The function iterates over a list of `(page_number, image)` tuples. For each page, it constructs the object key using a fixed pattern:

```python
key = f"pages/{document_id}/{page_number:04d}.jpg"
```

Page numbers are 1-indexed and zero-padded to four digits (e.g., page 1 → `pages/<uuid>/0001.jpg`, page 42 → `pages/<uuid>/0042.jpg`). This ensures lexicographic sort order is consistent with page order for any document up to 9,999 pages.

The image is serialized to JPEG in memory using a `BytesIO` buffer rather than a temporary file on disk:

```python
buffer = io.BytesIO()
image.save(buffer, format="JPEG", quality=quality)
buffer.seek(0, 2)   # seek to end to measure length
length = buffer.tell()
buffer.seek(0)       # rewind before upload
```

The buffer length is measured by seeking to the end before rewinding to the start. This is required because `put_object` needs an explicit `length` parameter when the data source is a stream (MinIO does not auto-detect stream length). The buffer is then passed directly to `put_object` with `content_type="image/jpeg"`. On success, the key is appended to `stored_keys`. On any exception, a warning is logged and the loop continues to the next page. The function returns `stored_keys` — the list of MinIO object keys that were successfully uploaded (FR-403).

**`delete_page_images`**

The function constructs the document-level prefix:

```python
prefix = f"pages/{document_id}/"
```

It calls `list_objects` with `recursive=True` to enumerate all objects under that prefix, then removes each one individually with `remove_object`. A running count `deleted` tracks how many objects were removed. If listing fails, a warning is logged and the function returns 0. If an individual object removal fails, a warning is logged and the function returns the count accumulated up to that point (early exit on first per-object failure).

---

**Key design decisions:**

| Decision | Alternatives Considered | Why This Choice |
|----------|------------------------|-----------------|
| JPEG compression with configurable quality | PNG (lossless), WebP, fixed quality | JPEG is broadly supported and suitable for page images where minor compression artefacts are acceptable. Configurable quality (default 85) lets callers tune storage size vs. fidelity without code changes (FR-402). |
| In-memory `BytesIO` buffer instead of temp files | `tempfile.NamedTemporaryFile`, writing to disk then streaming | Avoids filesystem I/O and temp-file cleanup. `put_object` accepts any file-like object, making the buffer a direct drop-in with no intermediate state on disk. |
| Zero-padded 4-digit page number in key | No padding, 3-digit padding, hash-based key | Lexicographic sort in MinIO prefix listings naturally reflects page order. Four digits supports up to 9,999 pages while staying compact. |
| Per-page error isolation in `store_page_images` | Abort on first failure, batch error handling | A single corrupted or oversized page should not block all other pages from being stored. Callers can detect partial success by comparing the length of `stored_keys` to the input list (FR-401). |
| Early-exit on first per-object error in `delete_page_images` | Continue deleting remaining objects on failure | A removal failure may indicate a permission or connectivity issue that will affect subsequent removals too. Returning a partial count lets callers detect incomplete deletes and retry or surface an error, rather than masking a systemic problem. |
| Separate `pages/` prefix namespace from `docs/` | Subdirectory under the document key, combined prefix | Keeps page images independently listable and deletable without touching document content keys. Enables future per-namespace lifecycle policies (e.g., separate bucket or TTL). |

---

**Configuration:**

| Parameter | Type | Default | Effect |
|-----------|------|---------|--------|
| `client` | `minio.Minio` | (required) | The MinIO client instance used for all object operations. |
| `document_id` | `str` | (required) | UUID string identifying the document. Forms the second path segment of every key: `pages/{document_id}/`. |
| `pages` | `list[tuple[int, object]]` | (required) | List of `(page_number, image)` pairs. `page_number` is an integer (1-indexed). `image` must support `.save(buffer, format=..., quality=...)` (PIL/Pillow `Image` interface). |
| `quality` | `int` | `85` | JPEG compression quality passed to `image.save`. Range 1–95; higher values produce larger files with fewer artefacts (FR-402). |
| `bucket` | `str` | `MINIO_BUCKET` (module constant) | MinIO bucket name. Defaults to the shared bucket used by the rest of the document store. Override for testing or multi-bucket deployments. |

The `delete_page_images` function shares the `client`, `document_id`, and `bucket` parameters with the same semantics; it has no `quality` or `pages` parameters.

---

**Error behavior:**

**`store_page_images` — per-page isolation**

Each page upload is wrapped in its own `try/except`. If serialization or upload fails for a page, the exception is caught, a `WARNING`-level log entry is emitted (including `page_number`, `document_id`, and the exception), and the loop advances to the next page. The failed page's key is not added to `stored_keys`. The caller receives a list that may be shorter than the input `pages` list. To detect partial failure, compare `len(stored_keys)` to `len(pages)`. No exception is raised to the caller under any per-page failure scenario.

**`delete_page_images` — partial delete on per-object failure**

Prefix listing is wrapped in an outer `try/except`: if `list_objects` raises, a warning is logged and the function returns `0` immediately. Individual `remove_object` calls are wrapped in a per-object `try/except`: if removal fails, a warning is logged and the function returns the `deleted` count accumulated so far (early exit). This means the return value is the count of objects successfully deleted before the first failure, not a guarantee that all objects under the prefix were removed. Callers that require complete cleanup (for example, update-mode pre-storage cleanup per FR-405) should treat a returned count less than the expected number of pages as a soft error and surface it or retry.

In both functions, no exception propagates to the caller. All failures are communicated through the return value (shorter key list or lower deleted count) and the warning log.
