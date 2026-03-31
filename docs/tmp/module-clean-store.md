### `src/ingest/common/clean_store.py` — CleanDocumentStore

**Purpose:**

`CleanDocumentStore` is the persistent boundary between Phase 1 (Document Processing) and Phase 2 (Embedding Pipeline). It stores each document as up to three files: a clean markdown file (`.md`), a source identity metadata file (`.meta.json`), and — new in the Docling-native redesign — a serialized `DoclingDocument` JSON file (`.docling.json`). All writes are atomic (tmp-file-then-rename), preventing corrupt reads on failure. The `.docling.json` file uses a versioned envelope format for future migration safety. Phase 2 reads the `DoclingDocument` from this store to activate the `HybridChunker` path. (FR-2005, FR-2007, FR-2009)

**How it works:**

`CleanDocumentStore` is constructed with a `store_dir: Path`. The directory is created on first write.

**Key path helpers:**
- `_safe_key(source_key)` — sanitizes the key for filesystem use by replacing `/`, `:`, `..` with safe characters.
- `_md_path`, `_meta_path`, `_docling_path` — return the three file paths for a given source key.

**`write(source_key, text, meta, docling_document=None)`** — the primary write method:
1. Create `store_dir` if it doesn't exist.
2. Atomically write `text` to `{safe_key}.md` via a `.md.tmp` intermediate.
3. Atomically write `meta` (orjson-serialized) to `{safe_key}.meta.json` via a `.meta.json.tmp` intermediate.
4. If `docling_document is not None`, call `write_docling(source_key, docling_document)`. Failure of `write_docling` is logged as an error but does NOT roll back the already-committed `.md` and `.meta.json` files.

**`write_docling(source_key, docling_document)`** — writes the DoclingDocument:
1. Create `store_dir` if needed.
2. Serialize the document: `json.loads(docling_document.model_dump_json())` — converts the Pydantic model to a Python dict via JSON round-trip.
3. Wrap in envelope: `{"_schema_version": "docling-native-v1", "document": doc_dict}`.
4. Serialize envelope with `orjson.dumps(envelope)`.
5. Write to `{safe_key}.docling.json.tmp` (note: the tmp path is `path.with_suffix(".tmp")`, producing `{safe_key}.docling.tmp`).
6. `os.replace(tmp_path, path)` — atomic rename.
7. On any failure, delete the tmp file and re-raise `OSError` or `ValueError`.

**`read_docling(source_key)`** — reads and deserializes the DoclingDocument:
1. Read raw bytes from `{safe_key}.docling.json`.
2. Parse with `orjson.loads`.
3. Check `data["_schema_version"] == "docling-native-v1"`. If not, log a warning and return `None`.
4. Import `DoclingDocument` from `docling_core.types.doc` — lazily, to avoid a hard dependency.
5. Return `DoclingDocument.model_validate(data["document"])`.
6. On any exception (file not found, invalid JSON, deserialization failure), log a warning and return `None`. Never raises.

**`read(source_key)`** — reads clean text and metadata. Raises `FileNotFoundError` if the `.md` file does not exist.

**`delete(source_key)`** — removes all three files (`.md`, `.meta.json`, `.docling.json`). Missing files are silently ignored.

```python
# The atomic write pattern used for write_docling (from actual source):
tmp_path = path.with_suffix(".tmp")
try:
    doc_dict = json.loads(docling_document.model_dump_json())
    envelope = {"_schema_version": "docling-native-v1", "document": doc_dict}
    tmp_path.write_bytes(orjson.dumps(envelope))
    os.replace(tmp_path, path)
except (OSError, ValueError):
    tmp_path.unlink(missing_ok=True)
    raise
```

**Key design decisions:**

| Decision | Alternatives Considered | Why This Choice |
|----------|------------------------|-----------------|
| Versioned envelope `{"_schema_version": "docling-native-v1", "document": ...}` | Store raw `model_dump_json()` directly | The envelope allows future schema migrations: a future reader can detect the version and apply a migration function before passing the dict to `model_validate`. Without a version field, there is no way to distinguish old and new formats. |
| JSON round-trip (`json.loads(model_dump_json())`) rather than `model_dump()` | `model_dump()` directly; pickle; msgpack | `model_dump_json()` uses the Pydantic v2 JSON serializer which handles all custom Docling types correctly. `model_dump()` may return non-JSON-serializable objects. `orjson.dumps` on a raw Pydantic dump could silently coerce types. |
| `write_docling` failure does not roll back `.md`/`.meta.json` | Transactional write of all three files together | Rolling back the markdown write on DoclingDocument serialization failure would discard a successfully extracted clean document. The DoclingDocument failure is non-fatal — Phase 2 can fall back to markdown chunking. |
| `read_docling` never raises (logs and returns `None`) | Raise `ValueError` on deserialization failure | Phase 2 callers check for `None` and fall back gracefully. Raising would require callers to add try/except blocks, and the fallback behavior (use markdown chunking) is identical regardless of why the DoclingDocument is unavailable. |
| `docling-core` imported lazily inside `read_docling` | Top-level import | Keeps the module importable even when `docling-core` is not installed. Non-Docling deployments can use `CleanDocumentStore` for markdown/metadata storage without installing the full Docling stack. |

**Configuration:**

| Parameter | Type | Default | Valid Range / Options | Effect |
|-----------|------|---------|----------------------|--------|
| `store_dir` (constructor) | `Path` | None (required) | Any filesystem path | Directory where all three file types are stored. Created automatically on first write. |

The `persist_docling_document` flag is NOT checked inside `CleanDocumentStore` — callers pass `docling_document=None` to `write()` when persistence is disabled. The store itself is agnostic to that config decision.

**Error behavior:**

`write()` raises `OSError` if the atomic markdown/meta write fails. `write_docling()` failure within `write()` is caught and logged — it does not re-raise from `write()`.

`write_docling()` raises `OSError` on filesystem failure (write or rename) and `ValueError` if the document cannot be serialized. These propagate to callers when called directly. When called from `write()`, they are caught internally.

`read()` raises `FileNotFoundError` if the `.md` file does not exist.

`read_docling()` never raises. All failures return `None` with a logged warning.

`clean_hash()` raises `FileNotFoundError` if the `.md` file does not exist.
