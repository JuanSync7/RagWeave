### `src/db/minio/store.py` — MinIO Page Image Storage

**Module purpose:** Stores and deletes page image files in MinIO under the `pages/` key namespace, reusing the shared MinIO client and bucket conventions.

**In scope:**
- Key generation: `pages/{document_id}/{page_number:04d}.jpg` (1-indexed, zero-padded to 4 digits)
- Per-page JPEG serialization via `io.BytesIO` buffer (format=JPEG, configurable quality)
- `put_object` calls with correct `content_type="image/jpeg"` and byte-accurate `length`
- Per-page failure isolation: log WARNING and continue; no exception propagated to caller
- Listing objects under `pages/{document_id}/` prefix for deletion
- Per-object `remove_object` calls with early exit on first removal failure
- Listing failure path: log WARNING and return 0 immediately
- Return value semantics: `store_page_images` returns list of successfully stored keys; `delete_page_images` returns integer count of removed objects

**Out of scope:**
- Ordering relative to ColQwen2 model loading (caller/orchestrator responsibility — FR-403)
- Bucket creation or selection (bucket is a caller-provided or module-default constant)
- Deciding whether a partial store result is a fatal error (caller responsibility)
- Deciding whether a partial delete count is a fatal error (caller responsibility)
- Image acquisition or rendering (caller passes pre-rendered PIL images)

---

#### Happy path scenarios

| Scenario | Input | Expected output |
|----------|-------|-----------------|
| Store 10 pages, all succeed | `document_id="abc-123"`, 10 PIL images, default `quality=85` | Returns list of 10 keys: `["pages/abc-123/0001.jpg", ..., "pages/abc-123/0010.jpg"]`; `put_object` called 10 times with correct keys |
| Key format: page numbering is 1-indexed and zero-padded | `document_id="doc-1"`, 1 PIL image | First key is `"pages/doc-1/0001.jpg"` (not `0000.jpg`) |
| Key format: page 10 is zero-padded to 4 digits | `document_id="doc-1"`, 10 images | Last key is `"pages/doc-1/0010.jpg"` |
| Key format: page 1000 fits in 4-digit field | `document_id="doc-x"`, image for page 1000 | Key is `"pages/doc-x/1000.jpg"` |
| Store uses custom quality | `quality=50`, 1 image | `image.save` called with `quality=50` |
| Store uses default quality=85 | No `quality` arg, 1 image | `image.save` called with `quality=85` |
| Store uses custom bucket | `bucket="custom-bucket"`, 1 image | `put_object` called with `bucket="custom-bucket"` |
| `put_object` receives correct content_type | Any valid call | `content_type="image/jpeg"` passed to every `put_object` |
| `put_object` receives byte-accurate length | Any valid call | `length` equals `buffer.tell()` after `image.save` (i.e., after seek-to-end, before rewind) |
| Delete all 10 pages for a document | `document_id="abc-123"`, listing returns 10 objects | Returns `10`; `remove_object` called 10 times |
| Delete with custom bucket | `bucket="custom-bucket"` | `list_objects` and `remove_object` called with `"custom-bucket"` |
| Delete uses correct prefix | `document_id="abc-123"` | `list_objects` called with `prefix="pages/abc-123/"` and `recursive=True` |
| Delete zero pages (document had no pages) | listing returns 0 objects | Returns `0`; no `remove_object` calls |
| Store empty page list | `pages=[]` | Returns `[]`; `put_object` not called |

---

#### Error scenarios

| Error type | Trigger condition | Expected behavior |
|-----------|------------------|-------------------|
| Single page store failure | `put_object` raises exception for one page | That page's key is NOT in `stored_keys`; WARNING logged with page_number, document_id, exception; remaining pages continue; no exception raised to caller |
| All pages fail to store | `put_object` raises exception for every page | Returns `[]`; WARNING logged per page; no exception raised |
| First page fails, rest succeed | `put_object` raises on page 1 only | `stored_keys` has N-1 entries; page 1 key absent; function returns normally |
| Listing fails during delete | `list_objects` raises exception | WARNING logged; returns `0` immediately; no `remove_object` calls |
| First object removal fails | `remove_object` raises on first object | WARNING logged; returns `0` (early exit with current `deleted` count before increment) |
| Mid-sequence object removal fails | `remove_object` raises on object k of N | Returns `k-1` (count of successfully removed objects before failure); early exit |
| `image.save` raises for a page | `image.save` raises exception | That page skipped; WARNING logged; remaining pages processed; no exception raised |

---

#### Boundary conditions

- **FR-401 key pattern**: Page 1 produces `0001.jpg`; page 10 produces `0010.jpg`; page 9999 produces `9999.jpg`. Numbering is strictly 1-indexed (no `0000.jpg` key ever produced).
- **FR-402 JPEG validity**: Buffer passed to `put_object` must contain valid JPEG bytes (verifiable by opening with PIL after retrieval). Quality parameter must be forwarded accurately to `image.save`.
- **FR-404 namespace isolation**: All keys are under `pages/` prefix; no key begins with `documents/`. Verifiable by asserting the prefix of every key in `stored_keys`.
- **FR-405 re-ingestion idempotence**: After deleting old page images and storing new ones, only 8 keys exist for a document previously ingested with 10 pages. This boundary condition is owned by the caller (delete then store), but `delete_page_images` must return `10` for a complete prior-run cleanup, and `store_page_images` must return exactly 8 new keys.
- **Partial store detection**: `len(stored_keys) < len(pages)` is the only signal for partial failure. The module must never silently add extra keys or skip keys without logging.
- **Buffer rewind**: `buffer.seek(0)` must be called after `length = buffer.tell()` so MinIO client reads from the start. If not rewound, `put_object` receives 0 bytes — a regression-prone detail to cover.
- **Single-page document**: `pages` list with one element produces exactly one key (`0001.jpg`).

---

#### Integration points

- **Caller: visual embedding node (ingest pipeline)**
  - Passes: shared MinIO `client` instance, `document_id` string, list of `(page_number: int, image: PIL.Image.Image)` tuples, optional `quality` int, optional `bucket` string
  - Receives: `list[str]` of stored MinIO keys (used to populate page image metadata for ColQwen2)
  - Caller checks `len(stored_keys) == len(pages)` to detect partial upload before proceeding

- **Caller: cleanup/re-ingestion path**
  - Passes: shared MinIO `client` instance, `document_id` string, optional `bucket` string
  - Receives: `int` count of deleted objects
  - Caller treats `count < expected` as a soft error (logs or retries at its discretion)

- **MinIO client interface (mocked in tests)**
  - `client.put_object(bucket, key, data, length, content_type=...)`
  - `client.list_objects(bucket, prefix=..., recursive=True)` → iterable of objects with `.object_name`
  - `client.remove_object(bucket, object_name)`

---

#### Known test gaps

- **Real JPEG byte validation (FR-402 full coverage)**: Unit tests mock `image.save` and `put_object`, so they cannot verify that bytes captured in the buffer constitute a valid JPEG. An integration test with a real PIL image and a real or in-memory MinIO is needed to fully satisfy FR-402. Marked as integration-only.
- **File size range check (FR-402 30KB–300KB)**: Size bounds for "typical document pages at quality 85" depend on image content. Cannot be covered by unit tests with synthetic images. Requires a fixture set of representative document page images in an integration suite.
- **FR-403 ordering (out of scope for this module)**: Whether `store_page_images` completes before ColQwen2 model loading is an orchestration invariant owned by the calling node, not testable here.
- **Concurrent store calls**: Behavior when two calls with the same `document_id` run in parallel is not specified. No concurrency tests planned at unit level.
- **Object name attribute contract**: Tests assume `obj.object_name` is the correct attribute on objects returned by `list_objects`. If the MinIO SDK changes this attribute, tests must be updated. Covered by pinning the SDK version in `pyproject.toml`.

---

#### Agent isolation contract (include verbatim in write-module-tests dispatch)

> **Agent isolation contract:** This agent receives ONLY:
> 1. This module test spec section
> 2. Phase 0 contract files (for import surface only — do not infer behavior from stubs)
>
> **Must NOT receive:** Source implementation files (`src/`), Phase B implementation code,
> other modules' test specs, or the engineering guide directly.
