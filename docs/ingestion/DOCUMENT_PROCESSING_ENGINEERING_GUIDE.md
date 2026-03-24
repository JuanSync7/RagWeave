> **Document type:** Post-implementation engineering reference
> **Companion spec:** `DOCUMENT_PROCESSING_SPEC.md`
> **Companion design:** `DOCUMENT_PROCESSING_DESIGN.md`
> **Source location:** `src/ingest/doc_processing/`, `src/ingest/pipeline/`, `src/ingest/clean_store.py`
> **Upstream:** DOCUMENT_PROCESSING_IMPLEMENTATION.md
> **Downstream:** DOCUMENT_PROCESSING_MODULE_TESTS.md
> **Last updated:** 2026-03-24

# Document Processing Pipeline -- Engineering Guide

---

## 1. System Overview

### Purpose

The Document Processing Pipeline (Phase 1) transforms raw source documents (PDF, DOCX, PPTX, XLSX, Markdown, HTML, RST, plain text) into clean, structured Markdown documents persisted to the Clean Document Store. Each persisted document serves as the sole input to the Embedding Pipeline (Phase 2). The two phases communicate exclusively through the Clean Document Store -- there is no in-memory handoff.

### Architecture Diagram

```text
                              IngestionConfig + Runtime
                                      |
                                      v
  Source File ──> pipeline/impl.py (ingest_file / ingest_directory)
                        |
                        |  Phase 1: Document Processing DAG
                        v
               ┌──────────────────────────────────────┐
               │ [1] document_ingestion                │
               │     Read file, compute SHA-256 hash   │
               └──────────────┬───────────────────────┘
                              │ (errors? ──> END)
                              v
               ┌──────────────────────────────────────┐
               │ [2] structure_detection               │
               │     Docling / regex structure cues    │
               └──────────────┬───────────────────────┘
                              │ (errors? ──> END)
                              │ (multimodal enabled
                              │  AND has_figures?)
                     ┌────────┴────────┐
                     v                 v
        ┌─────────────────┐   ┌───────────────┐
        │ [3] multimodal  │   │ (skip to [4]) │
        │     processing  │   └───────┬───────┘
        └────────┬────────┘           │
                 └──────────┬─────────┘
                            v
               ┌──────────────────────────────────────┐
               │ [4] text_cleaning                     │
               │     Boilerplate strip, normalize,     │
               │     inject figure notes               │
               └──────────────┬───────────────────────┘
                              │ (refactoring enabled?)
                     ┌────────┴────────┐
                     v                 v
        ┌─────────────────────┐   ┌──────┐
        │ [5] document        │   │ END  │
        │     refactoring     │   └──────┘
        └────────┬────────────┘
                 v
              ┌──────┐
              │ END  │
              └──────┘
                 │
                 v
        ┌─────────────────────────────────┐
        │      CleanDocumentStore          │
        │  {source_key}.md + .meta.json   │
        └─────────────────────────────────┘
                 │
                 v
          Phase 2: Embedding Pipeline
```

### Design Goals

1. **Fail-safe over fail-fast** -- When an LLM or VLM call fails, the pipeline falls back to deterministic alternatives rather than halting the batch.
2. **Configuration-driven behavior** -- Every optional stage (multimodal, refactoring, Docling) is toggled via `IngestionConfig` flags; no code changes are needed.
3. **Swappability over lock-in** -- External providers (LLM, VLM, structure detector) are behind configuration interfaces routed through LiteLLM.
4. **Context preservation over compression** -- Content restructuring never summarizes or removes information; numerical values and specifications are preserved exactly.
5. **Phase decoupling** -- Phase 1 and Phase 2 communicate only through the persistent Clean Document Store, enabling independent re-runs.

### Technology Choices

| Technology | Role | Rationale |
|------------|------|-----------|
| **LangGraph (StateGraph)** | DAG orchestration | Provides typed state propagation, conditional routing, and a compile-once/invoke-many execution model. |
| **LiteLLM Router** | LLM/VLM HTTP routing | Unified provider abstraction; model/provider changes require config, not code. |
| **Docling** | PDF/DOCX structure parsing | Extracts headings, tables, figures into markdown from complex binary formats. |
| **orjson** | JSON serialization | Fast, zero-copy JSON for manifest and metadata persistence. |
| **SHA-256** | Content hashing | Standard, collision-resistant hashing for idempotency and change detection. |

---

## 2. Architecture Decisions

### Decision: Two-Phase Pipeline Split with Persistent Boundary

**Context:** The original monolithic 13-node pipeline ran document processing and embedding in a single LangGraph invocation. This coupled extraction concerns with storage concerns, making it impossible to re-embed without re-processing.

**Options considered:**
1. Single 13-node DAG with in-memory state passing
2. Two-phase split with in-memory handoff between phases
3. Two-phase split with persistent boundary (Clean Document Store)

**Choice:** Option 3 -- Two-phase split with persistent Clean Document Store.

**Rationale:** Persisting the clean Markdown to disk between phases enables independent re-runs. The Embedding Pipeline can re-chunk and re-embed the corpus without re-running document extraction. The disk boundary also provides an auditable artifact for debugging extraction quality.

**Consequences:**
- *Positive:* Independent re-runs, auditable clean documents, simpler error recovery.
- *Negative:* Disk I/O overhead for every document (mitigated by atomic writes).
- *Watch for:* Store directory disk space growth in large corpus deployments.

---

### Decision: LangGraph TypedDict State (Not Dataclass)

**Context:** LangGraph requires a state schema for graph compilation. The state could be defined as a TypedDict or a dataclass/Pydantic model.

**Options considered:**
1. Python `TypedDict` with `total=False`
2. Pydantic `BaseModel`
3. Plain `dataclass`

**Choice:** Option 1 -- `TypedDict(total=False)`.

**Rationale:** LangGraph natively merges partial dictionary returns from nodes. Using `TypedDict(total=False)` allows each node to return only the fields it modifies, without needing to carry the full state. Pydantic would add validation overhead on every node return.

**Consequences:**
- *Positive:* Clean partial returns, no serialization overhead, native LangGraph compatibility.
- *Negative:* No runtime validation of field types -- errors surface as downstream `KeyError` or `TypeError`.
- *Watch for:* Typos in field names silently create new state keys.

---

### Decision: Module-Level Graph Compilation

**Context:** The LangGraph `StateGraph` must be compiled before invocation. Compilation can happen at call time or at module import time.

**Options considered:**
1. Compile on every `run_document_processing()` call
2. Compile once at module import (`_GRAPH = build_document_processing_graph()`)

**Choice:** Option 2 -- Module-level singleton `_GRAPH`.

**Rationale:** Graph compilation is pure and deterministic. Compiling once at import avoids repeated work during batch ingestion of hundreds of documents.

**Consequences:**
- *Positive:* Zero per-call compilation overhead.
- *Negative:* If node functions have import-time side effects, they trigger at module load.
- *Watch for:* Adding a node that requires runtime config would break this pattern.

---

### Decision: Idempotency Check Outside the DAG

**Context:** The idempotency check (comparing content hashes to decide whether to skip a file) could live inside the DAG as a first node, or outside the DAG in the orchestrator.

**Options considered:**
1. Idempotency node inside the DAG (as in the original 13-node pipeline)
2. Idempotency check in the orchestrator before DAG invocation

**Choice:** Option 2 -- Orchestrator-level check.

**Rationale:** The Document Processing DAG should always process when invoked. The skip decision depends on manifest state that the DAG should not need to know about. This keeps the DAG pure and the orchestrator responsible for skip logic.

**Consequences:**
- *Positive:* DAG is simpler and always runs to completion when invoked. `DocumentProcessingState` does not contain `should_skip` or `existing_hash`.
- *Negative:* The orchestrator (`pipeline/impl.py`) must handle all skip logic, making it more complex.
- *Watch for:* Callers who invoke `run_document_processing()` directly bypass idempotency.

---

### Decision: Atomic Writes in CleanDocumentStore

**Context:** Concurrent or interrupted writes could leave partial files in the store, causing the Embedding Pipeline to read corrupt data.

**Options considered:**
1. Direct write to target path
2. Write-to-temp-then-rename (atomic swap)

**Choice:** Option 2 -- Atomic write via `.tmp` file and `Path.replace()`.

**Rationale:** `Path.replace()` is atomic on POSIX filesystems. This guarantees that a reader always sees either the old complete file or the new complete file, never a partial write.

**Consequences:**
- *Positive:* No partial reads under any failure mode (crash, OOM, disk-full).
- *Negative:* Requires twice the disk space momentarily during writes.
- *Watch for:* Network filesystems (NFS/SMB) where `replace()` may not be atomic.

---

## 3. Module Reference

### `src/ingest/doc_processing/nodes/document_ingestion.py` -- Document Ingestion

**Purpose:** First node in the Phase 1 DAG. Reads the source file from disk using an encoding fallback chain (UTF-8, Latin-1, CP1252, UTF-8 with replacement) and computes the SHA-256 content hash. This node produces the `raw_text` that all downstream nodes consume and the `source_hash` used for idempotency by the orchestrator.

**How it works:**

1. Extract the source path from state:
```python
source_path = Path(state["source_path"])
```

2. Read file content using the encoding fallback chain:
```python
raw_text = read_text_with_fallbacks(source_path)
```
The `read_text_with_fallbacks` function (in `common/utils.py`) tries UTF-8, Latin-1, CP1252 in sequence, falling back to UTF-8 with replacement characters if all strict decodings fail.

3. Compute the SHA-256 hash of the raw file bytes:
```python
source_hash = sha256_path(source_path)
```

4. Return the partial state update:
```python
return {
    "raw_text": raw_text,
    "source_hash": source_hash,
    "processing_log": append_processing_log(state, "document_ingestion:ok"),
}
```

5. On any read failure, return an error payload that short-circuits the workflow:
```python
return {
    "errors": [f"read_failed:{source_path.name}:{exc}"],
    "processing_log": append_processing_log(state, "document_ingestion:failed"),
}
```

**Key design decisions:**

| Decision | Alternatives Considered | Why This Choice |
|----------|------------------------|-----------------|
| Hash raw bytes, not decoded text | Hash decoded text | Byte-level hash matches regardless of encoding used to decode, ensuring idempotency across runs even if fallback encoding changes. |
| No format-specific extractors in this node | Per-format extractor dispatch | Format-specific extraction (PDF, DOCX) is delegated to Docling in Node 2 or the read-text fallback. This node handles text-readable formats only; binary formats get raw-read here and proper parsing in structure_detection. |
| Error short-circuits via `errors` list | Raise exception | LangGraph conditional edges check `state.get("errors")` to route to END. This avoids exception propagation through the graph runtime. |

**Configuration:**

| Parameter | Type | Default | Effect |
|-----------|------|---------|--------|
| (none) | -- | -- | This node has no configuration knobs; it always runs. |

**Error behavior:**
- `Exception` during `read_text_with_fallbacks()`: returns `errors=["read_failed:{filename}:{exc}"]`. The workflow conditional edge routes to `END`, skipping all subsequent nodes.
- `Exception` during `sha256_path()`: not separately caught; propagates as an unhandled exception from the node. The orchestrator's outer `try/except` in `ingest_directory` catches this.

**Test guide:**
- **Behaviors to test:** Successful read of UTF-8 file; successful read of Latin-1 file; SHA-256 matches expected digest; processing_log contains `document_ingestion:ok` on success.
- **Mock requirements:** Mock `read_text_with_fallbacks` to inject encoding test data; mock `sha256_path` for deterministic hash assertions.
- **Boundary conditions:** Empty file (0 bytes); file with only replacement characters; very large file (memory boundary).
- **Error scenarios:** File not found (path does not exist); permission denied; file read produces only replacement characters.
- **Known test gaps:** Binary formats (PDF, DOCX) read as raw text here produce garbled `raw_text`; this is expected when Docling is enabled (Node 2 replaces it). Testing this coupling requires integration tests.

---

### `src/ingest/doc_processing/nodes/structure_detection.py` -- Structure Detection

**Purpose:** Second node in the Phase 1 DAG. Extracts lightweight structural signals (figure references and heading counts) from the document text. When Docling is enabled, this node parses the source file into markdown via Docling and derives structural signals from the parsed output. When Docling is disabled or fails (in non-strict mode), the node falls back to regex-based heuristics.

**How it works:**

1. Check whether Docling parsing is enabled:
```python
if config.enable_docling_parser:
```

2. When Docling is enabled, parse the source file:
```python
parsed = parse_with_docling(
    Path(state["source_path"]),
    parser_model=config.docling_model,
    artifacts_path=config.docling_artifacts_path,
)
parsed_text = parsed.text_markdown
figures = list(parsed.figures)
headings = list(parsed.headings)
```

3. When Docling fails in strict mode, return an error payload:
```python
if config.docling_strict:
    return {
        "errors": [f"docling_parse_failed:{state['source_name']}:{exc}"],
        "should_skip": True,
        "processing_log": append_processing_log(state, "structure_detection:failed"),
    }
```

4. When Docling is disabled or fails in non-strict mode, use regex heuristics:
```python
figures = re.findall(
    r"\b(?:Figure|Fig\.)\s*\d+[A-Za-z]?\b", raw_text, flags=re.IGNORECASE
)
headings = re.findall(
    r"^\s*(?:#{1,6}\s+.+|\d+(?:\.\d+)*\.?\s+[A-Z].+)$",
    raw_text, flags=re.MULTILINE,
)
```

5. Return the structure dictionary with signals:
```python
return {
    "raw_text": parsed_text,
    "structure": {
        "has_figures": bool(figures),
        "figures": figures[:32],
        "heading_count": len(headings),
        "docling_enabled": bool(config.enable_docling_parser),
        "docling_model": str(config.docling_model),
    },
    "processing_log": append_processing_log(state, "structure_detection:ok"),
}
```

**Key design decisions:**

| Decision | Alternatives Considered | Why This Choice |
|----------|------------------------|-----------------|
| Docling replaces `raw_text` with parsed markdown | Append parsed output as separate field | Downstream nodes (text_cleaning, refactoring) always operate on `raw_text`. Replacing it in-place avoids branching logic in every downstream node. |
| Figures list capped at 32 entries | No cap | Prevents excessive state size from documents with hundreds of figure references. The multimodal node has its own `vision_max_figures` cap for VLM calls. |
| Regex fallback on Docling failure (non-strict) | Skip structure detection entirely | Regex heuristics provide useful signals (figure count, heading count) even without Docling. This supports the fail-safe design principle. |
| Strict mode returns `should_skip=True` | Strict mode raises exception | Returning a state field keeps error handling within LangGraph's conditional routing rather than requiring exception handling at the graph level. |

**Configuration:**

| Parameter | Type | Default | Effect |
|-----------|------|---------|--------|
| `enable_docling_parser` | bool | `RAG_INGESTION_DOCLING_ENABLED` | Enables Docling-based parsing. When false, only regex heuristics are used. |
| `docling_model` | str | `RAG_INGESTION_DOCLING_MODEL` | Docling parser model identifier. |
| `docling_artifacts_path` | str | `RAG_INGESTION_DOCLING_ARTIFACTS_PATH` | Directory for Docling model artifacts. |
| `docling_strict` | bool | `RAG_INGESTION_DOCLING_STRICT` | When true, Docling failure is fatal (returns error). When false, falls back to regex. |

**Error behavior:**
- Docling parse failure (strict mode): returns `errors=["docling_parse_failed:..."]` and `should_skip=True`. Workflow routes to END.
- Docling parse failure (non-strict mode): silently falls back to regex heuristics. No error in state; processing continues.
- Regex heuristics cannot fail -- they return empty lists on no matches.

**Test guide:**
- **Behaviors to test:** Docling-parsed markdown replaces raw_text; regex fallback produces correct figure/heading counts; strict mode produces error on Docling failure; non-strict mode falls back silently; figures list is capped at 32.
- **Mock requirements:** Mock `parse_with_docling` to return controlled `DoclingParseResult` or raise exceptions. No actual Docling models needed for unit tests.
- **Boundary conditions:** Document with 0 figures; document with 100+ figure references (cap test); document with no headings; markdown-only document (no Docling needed).
- **Error scenarios:** Docling import error (not installed); Docling returns empty markdown; Docling timeout.
- **Known test gaps:** Docling parse quality for complex PDFs requires integration tests with actual Docling models. Regex accuracy on edge-case heading formats (e.g., Roman numeral sections) is not covered by heuristics.

---

### `src/ingest/doc_processing/nodes/multimodal_processing.py` -- Multimodal Processing

**Purpose:** Third node (optional) in the Phase 1 DAG. Generates multimodal notes when figure references are detected and multimodal processing is enabled. Optionally enriches figure notes with VLM-generated captions, OCR text, and tags via the vision support module.

**How it works:**

1. Check preconditions (multimodal enabled AND figures detected):
```python
if not config.enable_multimodal_processing or not has_figures:
    return {
        "processing_log": append_processing_log(state, "multimodal_processing:skipped")
    }
```

2. Create baseline notes from figure references:
```python
figures = list(state["structure"].get("figures", []))
notes = [f"{figure}: referenced in text" for figure in figures]
```

3. When vision processing is enabled, call the VLM:
```python
if config.enable_vision_processing:
    vision_notes, described_count = generate_vision_notes(
        state["raw_text"],
        source_path=Path(state["source_path"]),
        config=config,
    )
    if vision_notes:
        notes = vision_notes + notes[len(vision_notes):]
```

4. Merge VLM telemetry into the structure dictionary:
```python
if config.enable_vision_processing:
    structure["vision_provider"] = config.vision_provider
    structure["vision_model"] = config.vision_model
    structure["vision_described_count"] = described_count
```

5. On VLM failure in strict mode, return an error payload:
```python
if config.vision_strict:
    return {
        "errors": [f"vision_processing_failed:{state['source_name']}:{exc}"],
        "should_skip": True,
        "processing_log": append_processing_log(state, "multimodal_processing:failed"),
    }
```

**Key design decisions:**

| Decision | Alternatives Considered | Why This Choice |
|----------|------------------------|-----------------|
| Baseline notes always created for all figures | Only create notes for VLM-described figures | Ensures every detected figure has at least a placeholder note (`"Figure N: referenced in text"`) even when VLM is disabled or fails. |
| VLM notes overlay baseline notes by index | Append VLM notes separately | `notes = vision_notes + notes[len(vision_notes):]` replaces the first N baseline notes with richer VLM descriptions while keeping remaining baseline notes intact. |
| VLM failure in non-strict mode is silent | Log warning | In non-strict mode, the node returns baseline notes without VLM enrichment. The `described_count` telemetry field records 0, signaling that VLM was attempted but failed. |
| This node is skipped entirely by the DAG router when preconditions are not met | Node always runs and checks internally | The workflow conditional edge in `workflow.py` checks `enable_multimodal_processing AND has_figures` before routing to this node. However, the node also checks internally as a defense-in-depth measure. |

**Configuration:**

| Parameter | Type | Default | Effect |
|-----------|------|---------|--------|
| `enable_multimodal_processing` | bool | `RAG_INGESTION_ENABLE_MULTIMODAL_PROCESSING` | Master switch for figure note generation. |
| `enable_vision_processing` | bool | `RAG_INGESTION_VISION_ENABLED` | Enables VLM calls for figure description. |
| `vision_provider` | str | `RAG_INGESTION_VISION_PROVIDER` | VLM provider identifier (metadata/logging only). |
| `vision_model` | str | `RAG_INGESTION_VISION_MODEL` | VLM model name (metadata/logging only). |
| `vision_timeout_seconds` | int | `RAG_INGESTION_VISION_TIMEOUT_SECONDS` | Timeout for each VLM call. |
| `vision_max_figures` | int | `RAG_INGESTION_VISION_MAX_FIGURES` | Maximum figures sent to VLM. |
| `vision_max_image_bytes` | int | `RAG_INGESTION_VISION_MAX_IMAGE_BYTES` | Maximum image size for VLM. |
| `vision_temperature` | float | `RAG_INGESTION_VISION_TEMPERATURE` | VLM sampling temperature. |
| `vision_max_tokens` | int | `RAG_INGESTION_VISION_MAX_TOKENS` | Maximum response tokens from VLM. |
| `vision_strict` | bool | `RAG_INGESTION_VISION_STRICT` | When true, VLM failure is fatal. |

**Error behavior:**
- VLM failure (strict mode): returns `errors=["vision_processing_failed:..."]` and `should_skip=True`. Workflow routes to END.
- VLM failure (non-strict mode): exception is silently caught; baseline notes are returned without VLM enrichment.
- `generate_vision_notes` returns empty list: no VLM candidates were found (e.g., markdown images could not be resolved); baseline notes are returned.

**Test guide:**
- **Behaviors to test:** Skipped when multimodal disabled; skipped when no figures; baseline notes created for all figures; VLM notes overlay baseline; strict mode error on VLM failure; non-strict mode silent fallback; `described_count` telemetry correctness.
- **Mock requirements:** Mock `generate_vision_notes` to return controlled VLM notes or raise exceptions. Mock `state["structure"]` to control figure presence.
- **Boundary conditions:** Zero figures; figures detected but no resolvable images (VLM returns empty); VLM returns fewer notes than figures; VLM returns more notes than expected.
- **Error scenarios:** VLM timeout; VLM returns invalid JSON; VLM API key missing.
- **Known test gaps:** End-to-end VLM quality (caption accuracy, OCR correctness) requires human evaluation or golden-set comparison, which is outside unit test scope.

---

### `src/ingest/doc_processing/nodes/text_cleaning.py` -- Text Cleaning

**Purpose:** Fourth node in the Phase 1 DAG. Normalizes the raw (or Docling-parsed) text by stripping boilerplate, normalizing Unicode and whitespace, converting headings to standard Markdown format, and stripping trailing short lines. Appends generated multimodal notes as a `## Figure Notes` section.

**How it works:**

1. Run the full cleaning pipeline on raw_text:
```python
cleaned = clean_document(state["raw_text"])
```
The `clean_document` function in `support/markdown.py` executes these stages in order:
- `strip_boilerplate()` -- removes headers, footers, signatures, copyright lines
- `normalize_unicode()` -- normalizes Unicode to NFC form
- `clean_whitespace()` -- collapses multiple spaces and newlines
- `normalize_headings_to_markdown()` -- converts wiki-style and numbered headings to `#` syntax
- `strip_trailing_short_lines()` -- removes dangling short lines at end of document
- `clean_whitespace()` -- final whitespace pass

2. If multimodal notes exist, append them as a Markdown section:
```python
if state["multimodal_notes"]:
    cleaned += "\n\n## Figure Notes\n" + "\n".join(
        f"- {note}" for note in state["multimodal_notes"]
    )
```

3. Return the cleaned text:
```python
return {
    "cleaned_text": cleaned,
    "processing_log": append_processing_log(state, "text_cleaning:ok"),
}
```

**Key design decisions:**

| Decision | Alternatives Considered | Why This Choice |
|----------|------------------------|-----------------|
| Figure notes appended as a `## Figure Notes` section at the end | Inline figure notes at original positions | The current implementation uses lightweight figure-reference detection, not positional extraction. Appending at the end ensures notes are always included without complex position mapping. |
| Cleaning delegates to `support/markdown.py` and `support/document.py` | Inline cleaning logic in the node | Keeps the node thin (a few lines). The cleaning logic is reusable and testable independently. |
| No error handling in this node | Try/catch around cleaning | `clean_document` is a deterministic function over strings. It cannot fail (empty input produces empty output). If `multimodal_notes` is missing, the state default `[]` from `impl.py` prevents `KeyError`. |

**Configuration:**

| Parameter | Type | Default | Effect |
|-----------|------|---------|--------|
| (none directly) | -- | -- | This node has no configuration knobs. The cleaning behavior is controlled by the static patterns in `support/document.py`. |

**Error behavior:**
- This node does not raise exceptions. `clean_document` handles all edge cases (empty text, malformed Unicode) gracefully.
- If `state["multimodal_notes"]` is an empty list, no `## Figure Notes` section is appended.

**Test guide:**
- **Behaviors to test:** Boilerplate is stripped; Unicode is normalized; headings are converted to Markdown; whitespace is collapsed; figure notes are appended when present; no figure notes section when `multimodal_notes` is empty; processing_log contains `text_cleaning:ok`.
- **Mock requirements:** Mock `clean_document` if testing the node in isolation. For integration tests, use real `clean_document` with known input/output pairs.
- **Boundary conditions:** Empty raw_text; text with only boilerplate (produces empty cleaned_text); text with hundreds of multimodal notes; Unicode edge cases (zero-width joiners, combining characters).
- **Error scenarios:** None -- this node is designed to never fail.
- **Known test gaps:** The boilerplate patterns in `support/document.py` are heuristic and may not match all real-world boilerplate formats. Testing pattern coverage requires a corpus of real documents.

---

### `src/ingest/doc_processing/nodes/document_refactoring.py` -- Document Refactoring

**Purpose:** Fifth node (optional) in the Phase 1 DAG. Optionally rewrites the cleaned text through an LLM-based refactoring pass to make paragraphs self-contained for retrieval. When refactoring is disabled or the LLM response is empty, the cleaned text passes through unchanged.

**How it works:**

1. Check if refactoring is enabled:
```python
if not config.enable_document_refactoring:
    return {
        "refactored_text": state["cleaned_text"],
        "processing_log": append_processing_log(state, "document_refactoring:skipped"),
    }
```

2. Build the LLM prompt (truncated to first 10,000 characters):
```python
prompt = 'Return {"refactored_text":"..."} for:\n' + state["cleaned_text"][:10000]
```

3. Call the LLM via the JSON helper:
```python
response = _llm_json(prompt, config, 900)
```
The `_llm_json` function in `support/llm.py`:
- Returns `{}` if `config.enable_llm_metadata` is False
- Sends a system message `"Return JSON only."` and the user prompt
- Routes through `LiteLLM` via `get_llm_provider().json_completion()`
- Returns `{}` on any exception (fail-safe)

4. Extract the refactored text with fallback:
```python
refactored_text = str(response.get("refactored_text", "")).strip()
return {
    "refactored_text": refactored_text or state["cleaned_text"],
    "processing_log": append_processing_log(state, "document_refactoring:ok"),
}
```

**Key design decisions:**

| Decision | Alternatives Considered | Why This Choice |
|----------|------------------------|-----------------|
| Input truncated to 10,000 characters | Send full document | LLM context windows have token limits. Truncation ensures the prompt fits within typical model limits. Documents exceeding 10K chars are only partially refactored. |
| Single-pass refactoring (no self-correcting loop) | Iterative refactoring with fact-check validation (as specified in FR-503/504/505) | The current implementation is a simplified v1 that sends one LLM call. The spec's self-correcting loop with fact-check and completeness validation is not yet implemented. |
| Fallback to `cleaned_text` when LLM returns empty/fails | Raise error on LLM failure | Supports the fail-safe principle. An empty LLM response or failed call results in the original cleaned text being used, which is always safe. |
| `_llm_json` returns `{}` when `enable_llm_metadata` is False | Separate check before calling | This means refactoring can be "enabled" in config but still produce no refactored text if `enable_llm_metadata` is False. The fallback to `cleaned_text` handles this gracefully. |

**Configuration:**

| Parameter | Type | Default | Effect |
|-----------|------|---------|--------|
| `enable_document_refactoring` | bool | `RAG_INGESTION_ENABLE_DOCUMENT_REFACTORING` | Master switch. When false, cleaned_text passes through unchanged. |
| `enable_llm_metadata` | bool | `RAG_INGESTION_LLM_ENABLED` | Must be true for the LLM call to execute. When false, `_llm_json` returns `{}`. |
| `llm_temperature` | float | `RAG_INGESTION_LLM_TEMPERATURE` | Sampling temperature for refactoring. |
| `llm_timeout_seconds` | int | `RAG_INGESTION_LLM_TIMEOUT_SECONDS` | LLM call timeout. |
| `llm_model` | str | `RAG_INGESTION_LLM_MODEL` | Model identifier (metadata only; routing via LiteLLM). |

**Error behavior:**
- LLM call failure: `_llm_json` catches all exceptions and returns `{}`. The node falls back to `cleaned_text`.
- LLM returns malformed JSON: `parse_json_object` in `common/utils.py` handles this; `_llm_json` returns `{}`.
- LLM returns JSON without `refactored_text` key: `response.get("refactored_text", "")` returns empty string; fallback to `cleaned_text` activates.
- This node never returns an `errors` payload. All failures are silently absorbed.

**Test guide:**
- **Behaviors to test:** Skipped when `enable_document_refactoring` is False (returns cleaned_text); LLM response used when non-empty; fallback to cleaned_text when LLM returns empty; fallback when LLM fails; processing_log contains correct status.
- **Mock requirements:** Mock `_llm_json` to return controlled responses. No actual LLM calls needed for unit tests.
- **Boundary conditions:** Empty cleaned_text (produces empty prompt); cleaned_text exactly 10,000 characters; cleaned_text exceeding 10,000 characters (truncation test); LLM returns `{"refactored_text": ""}` (empty string triggers fallback).
- **Error scenarios:** LLM timeout; LLM returns non-JSON response; LLM returns JSON with wrong schema.
- **Known test gaps:** Refactoring quality (self-containedness, fact preservation) requires human evaluation or golden-set comparison. The spec's self-correcting loop (FR-503/504/505) and completeness threshold (FR-508) are not yet implemented, so those behaviors cannot be tested.

---

### `src/ingest/clean_store.py` -- Clean Document Store

**Purpose:** Persistent store for clean Markdown documents that serves as the boundary between Phase 1 (Document Processing) and Phase 2 (Embedding Pipeline). Stores each document as two files: `{source_key}.md` (clean Markdown text) and `{source_key}.meta.json` (source identity metadata). All writes are atomic via write-to-temp-then-rename.

**How it works:**

1. Source keys are sanitized for filesystem safety:
```python
def _safe_key(self, source_key: str) -> str:
    return source_key.replace("/", "_").replace(":", "_").replace("..", "__")
```

2. Atomic write ensures no partial reads:
```python
def write(self, source_key: str, text: str, meta: dict) -> None:
    self._dir.mkdir(parents=True, exist_ok=True)
    tmp_md = md_path.with_suffix(".md.tmp")
    tmp_meta = meta_path.with_suffix(".meta.json.tmp")
    try:
        tmp_md.write_text(text, encoding="utf-8")
        tmp_meta.write_bytes(orjson.dumps(meta))
        tmp_meta.replace(meta_path)
        tmp_md.replace(md_path)
    except Exception:
        tmp_md.unlink(missing_ok=True)
        tmp_meta.unlink(missing_ok=True)
        raise
```

3. Read returns both text and metadata:
```python
def read(self, source_key: str) -> tuple[str, dict]:
    text = md_path.read_text(encoding="utf-8")
    meta = orjson.loads(meta_path.read_bytes()) if meta_path.exists() else {}
    return text, meta
```

4. Clean hash computes SHA-256 of stored Markdown:
```python
def clean_hash(self, source_key: str) -> str:
    return hashlib.sha256(md_path.read_bytes()).hexdigest()
```

5. Delete removes both files:
```python
def delete(self, source_key: str) -> None:
    self._md_path(source_key).unlink(missing_ok=True)
    self._meta_path(source_key).unlink(missing_ok=True)
```

6. List keys scans for `.md` files:
```python
def list_keys(self) -> list[str]:
    return [p.stem for p in self._dir.glob("*.md") if p.suffix == ".md"]
```

**Key design decisions:**

| Decision | Alternatives Considered | Why This Choice |
|----------|------------------------|-----------------|
| Two files per document (.md + .meta.json) | Single JSON file with embedded text | Separate Markdown file enables direct human inspection and `diff` against source. The metadata is a small companion envelope. |
| Atomic write via `.tmp` + `replace()` | SQLite, direct write | POSIX `replace()` is atomic. Avoids database dependency. Simple and correct. |
| Source key sanitization replaces `/`, `:`, `..` | URL-encode or hash the key | Simple character replacement preserves readability while preventing path traversal. The resulting filenames are human-inspectable. |
| `list_keys()` returns `p.stem` from `.md` glob | Track keys in an index file | Scanning the directory is simple and always consistent with actual files. No risk of stale index. |
| Meta file can be missing on read (returns `{}`) | Fail if meta file missing | Forward-compatible: allows stores created before the metadata envelope was added to still be readable. |

**Configuration:**

| Parameter | Type | Default | Effect |
|-----------|------|---------|--------|
| `clean_store_dir` | str | `"data/clean_store"` | Directory for the store. Set on `IngestionConfig`. Empty string disables persistent storage. |

**Error behavior:**
- `write()` failure: both temp files are cleaned up. The exception re-raises to the caller. No partial state is left in the store.
- `read()` on missing key: raises `FileNotFoundError` with a message identifying the missing source_key.
- `clean_hash()` on missing key: raises `FileNotFoundError`.
- `exists()` on missing key: returns `False` (does not raise).
- `delete()` on missing key: no-op (`missing_ok=True`).

**Test guide:**
- **Behaviors to test:** Write creates both files; read returns correct text and metadata; exists returns True after write and False before; clean_hash matches expected SHA-256; delete removes both files; list_keys returns all stored keys; atomic write cleans up on failure.
- **Mock requirements:** Use `tmp_path` fixture (pytest) for isolated filesystem. No mocks needed -- this module is pure filesystem I/O.
- **Boundary conditions:** Source key with special characters (`/`, `:`, `..`); empty text; very large text (multi-MB); empty metadata dict; concurrent writes to same key (test atomicity).
- **Error scenarios:** Write to read-only directory; disk full during write (verify temp cleanup); read from non-existent store directory.
- **Known test gaps:** Atomicity on network filesystems (NFS/SMB) where `Path.replace()` may not be atomic. Testing this requires a networked test environment.

---

### `src/ingest/doc_processing/workflow.py` + `src/ingest/doc_processing/state.py` -- DAG Topology and State

**Purpose:** `workflow.py` defines the 5-node LangGraph `StateGraph` topology with conditional routing edges. `state.py` defines `DocumentProcessingState`, the TypedDict contract that flows through the graph. Together, they form the structural backbone of the Phase 1 pipeline.

**How it works:**

1. The `StateGraph` is built with five nodes:
```python
graph = StateGraph(DocumentProcessingState)
graph.add_node("document_ingestion", document_ingestion_node)
graph.add_node("structure_detection", structure_detection_node)
graph.add_node("multimodal_processing", multimodal_processing_node)
graph.add_node("text_cleaning", text_cleaning_node)
graph.add_node("document_refactoring", document_refactoring_node)
```

2. Entry point is always `document_ingestion`:
```python
graph.set_entry_point("document_ingestion")
```

3. After `document_ingestion`, short-circuit to END on errors:
```python
graph.add_conditional_edges(
    "document_ingestion",
    lambda state: "end" if state.get("errors") else "structure_detection",
    {"structure_detection": "structure_detection", "end": END},
)
```

4. After `structure_detection`, route based on errors and multimodal conditions:
```python
graph.add_conditional_edges(
    "structure_detection",
    lambda state: "end" if state.get("errors") else (
        "multimodal_processing"
        if (
            state["runtime"].config.enable_multimodal_processing
            and state.get("structure", {}).get("has_figures")
        )
        else "text_cleaning"
    ),
    {"multimodal_processing": "multimodal_processing",
     "text_cleaning": "text_cleaning", "end": END},
)
```

5. After `text_cleaning`, route to refactoring or END:
```python
graph.add_conditional_edges(
    "text_cleaning",
    lambda state: (
        "document_refactoring"
        if state["runtime"].config.enable_document_refactoring
        else "end"
    ),
    {"document_refactoring": "document_refactoring", "end": END},
)
```

6. `DocumentProcessingState` defines the typed contract:
```python
class DocumentProcessingState(TypedDict, total=False):
    runtime: Runtime
    source_path: str
    source_name: str
    source_uri: str
    source_key: str
    source_id: str
    source_hash: str
    connector: str
    source_version: str
    raw_text: str
    structure: Dict[str, Any]
    multimodal_notes: List[str]
    cleaned_text: str
    refactored_text: Optional[str]
    errors: List[str]
    processing_log: List[str]
```

**Key design decisions:**

| Decision | Alternatives Considered | Why This Choice |
|----------|------------------------|-----------------|
| Conditional edges use lambda functions, not named functions | Named router functions | Routing logic is simple (2-3 conditions each). Lambdas keep routing visible in the graph definition. |
| Error check uses `state.get("errors")` (truthy check) | Explicit `len(state.get("errors", [])) > 0` | An empty list is falsy. A non-empty list is truthy. This is idiomatic Python and sufficient for routing. |
| Multimodal node has both DAG-level and node-level skip checks | Only DAG-level | Defense-in-depth: the node's internal check guards against being invoked incorrectly (e.g., in testing or by a modified graph). |
| `refactored_text` is `Optional[str]` | Always `str` | Explicitly signals when refactoring was skipped (`None`) vs. refactoring produced empty output (empty string). The orchestrator uses `phase1.get("refactored_text") or phase1.get("cleaned_text", "")` to handle both. |

**Configuration:**

| Parameter | Type | Default | Effect |
|-----------|------|---------|--------|
| `enable_multimodal_processing` | bool | env | Controls whether the multimodal node is reachable in the DAG. |
| `enable_document_refactoring` | bool | env | Controls whether the refactoring node is reachable in the DAG. |

**Error behavior:**
- Errors from any node populate `state["errors"]`. All conditional edges after `document_ingestion` and `structure_detection` check for errors and route to END.
- After `text_cleaning`, there is no error check -- the cleaning node never fails, and refactoring failures are absorbed by `_llm_json`.

**Test guide:**
- **Behaviors to test:** Graph compiles without error; happy path traverses all 5 nodes; errors after document_ingestion short-circuit; errors after structure_detection short-circuit; multimodal node skipped when disabled or no figures; refactoring node skipped when disabled; `DocumentProcessingState` accepts partial returns.
- **Mock requirements:** Mock all 5 node functions to return controlled state updates. The graph should be testable without real file I/O or LLM calls.
- **Boundary conditions:** All optional stages disabled (minimal path: ingest -> structure -> clean -> END); all optional stages enabled with figures (maximal path: all 5 nodes).
- **Error scenarios:** Errors from document_ingestion; errors from structure_detection (strict Docling failure); errors from multimodal_processing (strict VLM failure).
- **Known test gaps:** LangGraph version compatibility -- the conditional edge API may change across LangGraph versions.

---

### `src/ingest/pipeline/impl.py` -- Pipeline Orchestrator

**Purpose:** The top-level orchestrator that ties together Phase 1 (Document Processing), the Clean Document Store, and Phase 2 (Embedding Pipeline). Provides `ingest_file()` for single-file ingestion and `ingest_directory()` for batch directory ingestion with idempotency, manifest management, and optional mirror artifact persistence.

**How it works:**

1. `ingest_file()` runs Phase 1, persists to CleanDocumentStore, then runs Phase 2:
```python
phase1 = run_document_processing(
    runtime=runtime,
    source_path=str(source_path),
    source_name=source_name,
    ...
)
if phase1.get("errors"):
    return {"errors": phase1["errors"], ...}

clean_text = phase1.get("refactored_text") or phase1.get("cleaned_text", "")

if store is not None:
    store.write(source_key, clean_text, meta)
    clean_hash = store.clean_hash(source_key)

phase2 = run_embedding_pipeline(runtime=runtime, ..., clean_text=clean_text, ...)
```

2. `ingest_directory()` performs the full batch lifecycle:
   - Validates configuration via `verify_core_design()`
   - Ensures Docling and vision readiness
   - Loads and normalizes the manifest
   - Discovers source files matching configured extensions
   - Builds source identities via `_local_source_identity()`
   - Removes orphaned sources (in update mode)
   - Creates shared `Runtime` (embedder, weaviate client, KG builder)
   - Loops over sources: idempotency check, `ingest_file()`, manifest update
   - Persists KG and exports to Obsidian (optional)

3. Idempotency check in `ingest_directory()`:
```python
if update and previous_hash:
    current_hash = sha256_path(source_path)
    store_ok = (not config.clean_store_dir) or CleanDocumentStore(
        Path(config.clean_store_dir)
    ).exists(source["source_key"])
    if current_hash == previous_hash and store_ok:
        skipped += 1
        ...
        continue
```

4. Source identity generation for local filesystem:
```python
def _local_source_identity(path: Path, documents_root: Path) -> SourceIdentity:
    stat = resolved.stat()
    source_id = f"{stat.st_dev}:{stat.st_ino}"
    source_key = f"{_LOCAL_CONNECTOR}:{source_id}"
```

5. Manifest matching uses a priority chain:
```python
# source_key -> source_id -> source_uri -> legacy filename
```

**Key design decisions:**

| Decision | Alternatives Considered | Why This Choice |
|----------|------------------------|-----------------|
| `clean_text` prefers `refactored_text` over `cleaned_text` | Always use `cleaned_text` | When refactoring is enabled and produces output, the refactored text is higher quality (self-contained paragraphs). The `or` chain provides automatic fallback when refactoring is disabled or fails. |
| Manifest is saved after every successful file | Batch save at end | Incremental manifest saves provide crash recovery. If the process dies mid-batch, all completed files are recorded. |
| Source identity uses `dev:ino` (device + inode) | Use file path | Paths can change (rename, move); dev:ino is stable as long as the file exists on the same filesystem. This enables detecting renamed files. |
| Manifest matching falls back through 4 levels | Match on source_key only | Supports migration from older manifest formats where only filename was stored, and handles file renames gracefully. |
| Mirror artifacts are optional and controlled by `persist_refactor_mirror` | Always persist mirrors | Mirror files add disk overhead. Only needed when auditing refactoring quality. |
| Per-file error isolation via `try/except` in the loop | Let exceptions propagate | A single file failure should not halt batch ingestion of hundreds of files. Each failure is logged and counted. |

**Configuration:**

| Parameter | Type | Default | Effect |
|-----------|------|---------|--------|
| `clean_store_dir` | str | `"data/clean_store"` | CleanDocumentStore directory. Empty disables persistence. |
| `persist_refactor_mirror` | bool | `RAG_INGESTION_PERSIST_REFACTOR_MIRROR` | Write original/refactored mirror artifacts. |
| `mirror_output_dir` | str | `RAG_INGESTION_MIRROR_DIR` | Directory for mirror files. |
| `update_mode` | bool | `False` | Set automatically by `ingest_directory()` when `update=True`. |
| `export_processed` | bool | `False` | Write cleaned text to `PROCESSED_DIR`. |
| `build_kg` | bool | `True` | Create KnowledgeGraphBuilder in Runtime. |
| `fresh` (parameter) | bool | `True` | Delete existing collection before ingestion. |
| `update` (parameter) | bool | `False` | Enable incremental mode with manifest-based idempotency. |

**Error behavior:**
- `verify_core_design()` raises `ValueError` for invalid config (e.g., `chunk_overlap >= chunk_size`).
- `ensure_docling_ready()` raises `RuntimeError` if Docling is not installed or models are missing.
- `ensure_vision_ready()` raises `RuntimeError` if VLM is not reachable.
- Per-file failures: caught by `try/except` in the loop; error message added to `errors` list; file counted as `failed`; processing continues with next file.
- Phase 1 errors: returned early from `ingest_file()` with `stored_count=0`.

**Test guide:**
- **Behaviors to test:** `ingest_file()` returns correct error payload on Phase 1 failure; `ingest_file()` writes to CleanDocumentStore; `ingest_directory()` skips unchanged files in update mode; `ingest_directory()` removes orphaned sources; manifest is updated after each file; `verify_core_design()` catches invalid configs; source identity uses dev:ino.
- **Mock requirements:** Mock `run_document_processing`, `run_embedding_pipeline`, `get_weaviate_client`, `LocalBGEEmbeddings`, `KnowledgeGraphBuilder`, `ensure_docling_ready`, `ensure_vision_ready`, `load_manifest`, `save_manifest`, `sha256_path`. Mock filesystem stat for source identity tests.
- **Boundary conditions:** Empty directory (no files); single file; directory with unsupported file extensions; manifest with legacy entries; source key collision.
- **Error scenarios:** Phase 1 error for one file in a batch; Phase 2 error; unhandled exception in file processing; corrupted manifest; read-only output directory.
- **Known test gaps:** Weaviate client lifecycle (`with` block context manager); KnowledgeGraph save/export; concurrent directory access.

---

### Type and Schema Files (Brief Treatment)

#### `src/ingest/doc_processing/state.py` -- DocumentProcessingState

**Purpose:** Defines the LangGraph TypedDict state contract for the 5-node Document Processing DAG.

**Type definitions:**
- `DocumentProcessingState(TypedDict, total=False)` -- 16 fields, all optional (`total=False`), populated progressively as nodes complete.

**Key decisions:** Uses `TypedDict` (not Pydantic) for zero-overhead LangGraph integration. The `total=False` parameter allows partial state returns from each node.

#### `src/ingest/common/types.py` -- Shared Types and Configuration

**Purpose:** Defines the primary configuration dataclass (`IngestionConfig`), the runtime dependency container (`Runtime`), the full 13-node pipeline state (`IngestState`), and supporting types.

**Type definitions:**
- `IngestionConfig` -- 40+ configuration fields with defaults from environment/settings.
- `Runtime` -- holds `config`, `embedder`, `weaviate_client`, `kg_builder`.
- `IngestState(TypedDict)` -- the full 13-node state schema (superset of `DocumentProcessingState`).
- `IngestionDesignCheck` -- validation report with `ok`, `errors`, `warnings`.
- `IngestionRunSummary` -- batch result summary with `processed`, `skipped`, `failed`, etc.
- `PIPELINE_NODE_NAMES` -- ordered list of all 13 node names.

**Key decisions:** `IngestionConfig` uses a Python `dataclass` with defaults sourced from `config.settings`, enabling both environment-driven and programmatic configuration. LLM routing fields are retained for metadata logging but routing is handled by LiteLLM.

#### `src/ingest/doc_processing/__init__.py` -- Public API

**Purpose:** Thin facade that exports `run_document_processing` from `impl.py`.

**Exports:** `run_document_processing`

**Key decisions:** Single re-export keeps the import surface stable (`from src.ingest.doc_processing import run_document_processing`). Internal refactoring of `impl.py` does not break callers.

#### `src/ingest/pipeline/__init__.py` -- Pipeline Public API

**Purpose:** Thin facade that exports `ingest_file` and `ingest_directory` from `impl.py`.

**Exports:** `ingest_file`, `ingest_directory`

**Key decisions:** Same facade pattern as the doc_processing package. Callers import from the package, not the impl module.

#### `src/ingest/common/schemas.py` -- Shared Schema Contracts

**Purpose:** Defines lightweight, stable contracts used across the ingestion pipeline.

**Type definitions:**
- `ManifestEntry(TypedDict, total=False)` -- persisted manifest entry per source key.
- `SourceIdentity(TypedDict)` -- stable identity payload for source discovery.
- `ProcessedChunk` -- dataclass with `text` and `metadata` fields.

---

## 4. End-to-End Data Flow

### Scenario 1: Happy Path -- Markdown Document with Figures, Refactoring Enabled

**Input:** `documents/clock_spec.md` -- a Markdown file with 3 figure references and 5 headings.

**Config:** `enable_docling_parser=False`, `enable_multimodal_processing=True`, `enable_vision_processing=True`, `enable_document_refactoring=True`, `enable_llm_metadata=True`.

**Step-by-step:**

1. **Orchestrator** (`pipeline/impl.py`): `ingest_directory()` discovers the file, computes `source_id = "66305:12345678"`, `source_key = "local_fs:66305:12345678"`. Checks manifest -- no previous entry. Calls `ingest_file()`.

2. **`ingest_file()`**: Creates `CleanDocumentStore`, calls `run_document_processing()`.

3. **`run_document_processing()`** (`doc_processing/impl.py`): Seeds initial state:
```python
{
    "runtime": Runtime(...),
    "source_path": "/data/documents/clock_spec.md",
    "source_name": "clock_spec.md",
    "source_hash": "",
    "raw_text": "",
    "structure": {},
    "multimodal_notes": [],
    "cleaned_text": "",
    "refactored_text": None,
    "errors": [],
    "processing_log": [],
    ...
}
```

4. **Node 1 -- document_ingestion**: Reads the file (UTF-8), computes SHA-256. State gains:
```python
{"raw_text": "# Clock Spec\n...", "source_hash": "a3f9c2...", "processing_log": ["document_ingestion:ok"]}
```

5. **Routing**: `errors` is empty -> proceed to `structure_detection`.

6. **Node 2 -- structure_detection**: Docling is disabled. Regex finds 3 figure references and 5 headings. State gains:
```python
{
    "raw_text": "# Clock Spec\n...",  # unchanged (no Docling)
    "structure": {"has_figures": True, "figures": ["Figure 1", "Figure 2", "Figure 3"], "heading_count": 5, "docling_enabled": False, "docling_model": "..."},
    "processing_log": [..., "structure_detection:ok"]
}
```

7. **Routing**: No errors, `enable_multimodal_processing=True` AND `has_figures=True` -> route to `multimodal_processing`.

8. **Node 3 -- multimodal_processing**: Creates 3 baseline notes. VLM generates descriptions for 2 resolved images. State gains:
```python
{
    "multimodal_notes": ["Figure 1: Clock distribution network | tags=PLL, clock tree", "Figure 2: Timing diagram | text=setup=0.5ns | tags=timing", "Figure 3: referenced in text"],
    "structure": {..., "vision_provider": "ollama", "vision_model": "llava", "vision_described_count": 2},
    "processing_log": [..., "multimodal_processing:ok"]
}
```

9. **Node 4 -- text_cleaning**: Strips boilerplate, normalizes whitespace and headings. Appends figure notes:
```python
{
    "cleaned_text": "# Clock Spec\n\n## Overview\n...\n\n## Figure Notes\n- Figure 1: Clock distribution...\n- Figure 2: Timing diagram...\n- Figure 3: referenced in text",
    "processing_log": [..., "text_cleaning:ok"]
}
```

10. **Routing**: `enable_document_refactoring=True` -> route to `document_refactoring`.

11. **Node 5 -- document_refactoring**: Sends first 10K chars to LLM. Receives refactored text with self-contained paragraphs:
```python
{
    "refactored_text": "# Clock Specification\n\nThe clock distribution network described in this document...",
    "processing_log": [..., "document_refactoring:ok"]
}
```

12. **Back in `ingest_file()`**: `clean_text = refactored_text` (non-None, non-empty). Writes to CleanDocumentStore:
    - `data/clean_store/local_fs_66305_12345678.md`
    - `data/clean_store/local_fs_66305_12345678.meta.json`

13. **Phase 2**: `run_embedding_pipeline()` chunks, embeds, and stores vectors.

14. **Manifest update**: Source key added with content_hash, chunk_count, summary, keywords.

---

### Scenario 2: Error/Fallback Path -- PDF with Docling Failure (Non-Strict)

**Input:** `documents/legacy_spec.pdf` -- a scanned PDF with no text layer.

**Config:** `enable_docling_parser=True`, `docling_strict=False`, `enable_multimodal_processing=True`, `enable_vision_processing=False`, `enable_document_refactoring=False`.

**Step-by-step:**

1. **Node 1 -- document_ingestion**: Reads the PDF as raw bytes (fallback to replacement characters). SHA-256 computed. `raw_text` contains garbled binary/replacement characters.

2. **Node 2 -- structure_detection**: Docling attempts to parse the PDF. Docling raises an exception (e.g., unsupported format or corrupted file). Because `docling_strict=False`, the node falls back to regex heuristics. Regex finds 0 figures and 0 headings in the garbled text:
```python
{
    "structure": {"has_figures": False, "figures": [], "heading_count": 0, ...},
    "processing_log": [..., "structure_detection:ok"]
}
```

3. **Routing**: No errors, `has_figures=False` -> skip multimodal, route to `text_cleaning`.

4. **Node 4 -- text_cleaning**: Cleaning strips boilerplate patterns. Garbled text may be mostly stripped:
```python
{"cleaned_text": "[minimal content or empty]", "processing_log": [..., "text_cleaning:ok"]}
```

5. **Routing**: `enable_document_refactoring=False` -> route to END.

6. **Back in `ingest_file()`**: `clean_text = cleaned_text` (refactored_text is None). CleanDocumentStore writes the minimal content. Phase 2 processes whatever text remains.

---

### Scenario 3: Edge Case -- All Optional Stages Skipped

**Input:** `documents/simple_notes.txt` -- plain text file with no figures or complex structure.

**Config:** `enable_docling_parser=False`, `enable_multimodal_processing=False`, `enable_document_refactoring=False`.

**Step-by-step:**

1. **Node 1 -- document_ingestion**: Reads the text file. SHA-256 computed. `processing_log: ["document_ingestion:ok"]`.

2. **Node 2 -- structure_detection**: Regex finds 0 figures, some headings. `structure: {"has_figures": False, ...}`.

3. **Routing**: `enable_multimodal_processing=False` -> skip to `text_cleaning`.

4. **Node 4 -- text_cleaning**: Cleans whitespace and normalizes headings. No figure notes (multimodal_notes is `[]`). `processing_log: [..., "text_cleaning:ok"]`.

5. **Routing**: `enable_document_refactoring=False` -> route to END.

6. **Result**: The pipeline traversed only 3 of 5 nodes: `document_ingestion` -> `structure_detection` -> `text_cleaning`. The `processing_log` is `["document_ingestion:ok", "structure_detection:ok", "text_cleaning:ok"]`.

---

## 5. Configuration Reference

### Document Processing Configuration (IngestionConfig)

#### Core Pipeline Controls

| Parameter | Type | Default | Module | Effect |
|-----------|------|---------|--------|--------|
| `enable_llm_metadata` | bool | `RAG_INGESTION_LLM_ENABLED` | document_refactoring | Master LLM switch. When false, `_llm_json` returns `{}`. |
| `enable_document_refactoring` | bool | `RAG_INGESTION_ENABLE_DOCUMENT_REFACTORING` | workflow, document_refactoring | When false, DAG routes around refactoring node. |
| `enable_multimodal_processing` | bool | `RAG_INGESTION_ENABLE_MULTIMODAL_PROCESSING` | workflow, multimodal_processing | When false, DAG routes around multimodal node. |
| `verbose_stage_logs` | bool | `RAG_INGESTION_VERBOSE_STAGE_LOGS` | shared (append_processing_log) | Emit stage messages to logger in addition to processing_log list. |

#### Docling Configuration

| Parameter | Type | Default | Module | Effect |
|-----------|------|---------|--------|--------|
| `enable_docling_parser` | bool | `RAG_INGESTION_DOCLING_ENABLED` | structure_detection | Enable Docling parsing. |
| `docling_model` | str | `RAG_INGESTION_DOCLING_MODEL` | structure_detection | Parser model identifier. |
| `docling_artifacts_path` | str | `RAG_INGESTION_DOCLING_ARTIFACTS_PATH` | structure_detection | Model artifacts directory. |
| `docling_strict` | bool | `RAG_INGESTION_DOCLING_STRICT` | structure_detection | Fatal on Docling failure when true. |
| `docling_auto_download` | bool | `RAG_INGESTION_DOCLING_AUTO_DOWNLOAD` | pipeline/impl (startup) | Download Docling models at startup. |

#### Vision / VLM Configuration

| Parameter | Type | Default | Module | Effect |
|-----------|------|---------|--------|--------|
| `enable_vision_processing` | bool | `RAG_INGESTION_VISION_ENABLED` | multimodal_processing | Enable VLM calls. |
| `vision_provider` | str | `RAG_INGESTION_VISION_PROVIDER` | multimodal_processing | VLM provider (metadata only). |
| `vision_model` | str | `RAG_INGESTION_VISION_MODEL` | multimodal_processing | VLM model (metadata only). |
| `vision_timeout_seconds` | int | `RAG_INGESTION_VISION_TIMEOUT_SECONDS` | multimodal_processing | VLM call timeout. |
| `vision_max_figures` | int | `RAG_INGESTION_VISION_MAX_FIGURES` | multimodal_processing | Max figures sent to VLM. |
| `vision_max_image_bytes` | int | `RAG_INGESTION_VISION_MAX_IMAGE_BYTES` | multimodal_processing | Max image size for VLM. |
| `vision_temperature` | float | `RAG_INGESTION_VISION_TEMPERATURE` | multimodal_processing | VLM sampling temperature. |
| `vision_max_tokens` | int | `RAG_INGESTION_VISION_MAX_TOKENS` | multimodal_processing | VLM max response tokens. |
| `vision_auto_pull` | bool | `RAG_INGESTION_VISION_AUTO_PULL` | pipeline/impl (startup) | Auto-pull VLM model. |
| `vision_strict` | bool | `RAG_INGESTION_VISION_STRICT` | multimodal_processing | Fatal on VLM failure when true. |

#### LLM Configuration

| Parameter | Type | Default | Module | Effect |
|-----------|------|---------|--------|--------|
| `llm_model` | str | `RAG_INGESTION_LLM_MODEL` | document_refactoring | LLM model (metadata only; routing via LiteLLM). |
| `llm_temperature` | float | `RAG_INGESTION_LLM_TEMPERATURE` | document_refactoring | LLM sampling temperature. |
| `llm_timeout_seconds` | int | `RAG_INGESTION_LLM_TIMEOUT_SECONDS` | document_refactoring | LLM call timeout. |

#### Storage and Output Configuration

| Parameter | Type | Default | Module | Effect |
|-----------|------|---------|--------|--------|
| `clean_store_dir` | str | `"data/clean_store"` | pipeline/impl | CleanDocumentStore directory. Empty disables. |
| `persist_refactor_mirror` | bool | `RAG_INGESTION_PERSIST_REFACTOR_MIRROR` | pipeline/impl | Write mirror artifacts. |
| `mirror_output_dir` | str | `RAG_INGESTION_MIRROR_DIR` | pipeline/impl | Mirror output directory. |
| `export_processed` | bool | `False` | pipeline/impl | Export cleaned text to PROCESSED_DIR. |

---

## 6. Integration Contracts

### Public Entry Points

#### `run_document_processing()` (Phase 1 Only)

**Location:** `src/ingest/doc_processing/__init__.py`

**Signature:**
```python
def run_document_processing(
    runtime: Runtime,
    source_path: str,
    source_name: str,
    source_uri: str,
    source_key: str,
    source_id: str,
    connector: str,
    source_version: str,
) -> DocumentProcessingState:
```

**Input contract:**
- `runtime` must contain a valid `IngestionConfig` and is threaded to all nodes.
- `source_path` must be an absolute path to an existing file on disk.
- All identity fields (`source_name`, `source_uri`, `source_key`, `source_id`, `connector`, `source_version`) are pass-through metadata stored in state.

**Output contract:**
- Returns a `DocumentProcessingState` dictionary.
- On success: `errors` is an empty list. `raw_text`, `cleaned_text` are populated. `refactored_text` is either a string or `None`. `processing_log` contains ordered stage completion entries.
- On failure: `errors` is a non-empty list. Downstream fields may be absent or empty.

#### `ingest_file()` (Phase 1 + Phase 2)

**Location:** `src/ingest/pipeline/__init__.py`

**Signature:**
```python
def ingest_file(
    source_path: Path,
    runtime: Runtime,
    source_name: str,
    source_uri: str,
    source_key: str,
    source_id: str,
    connector: str,
    source_version: str,
    existing_hash: str = "",
    existing_source_uri: str = "",
) -> dict:
```

**Output contract:**
```python
{
    "errors": list[str],          # non-empty on failure
    "stored_count": int,           # chunks stored in vector DB
    "metadata_summary": str,       # LLM-generated summary
    "metadata_keywords": list[str],# extracted keywords
    "processing_log": list[str],   # Phase 1 + Phase 2 logs
    "source_hash": str,            # SHA-256 of source file
    "clean_hash": str,             # SHA-256 of clean document
}
```

#### `ingest_directory()` (Full Batch)

**Location:** `src/ingest/pipeline/__init__.py`

**Signature:**
```python
def ingest_directory(
    documents_dir: Path,
    config: Optional[IngestionConfig] = None,
    fresh: bool = True,
    update: bool = False,
    obsidian_export: bool = False,
    selected_sources: Optional[list[Path]] = None,
) -> IngestionRunSummary:
```

**Output contract:**
```python
IngestionRunSummary(
    processed=int,          # files successfully processed
    skipped=int,            # files skipped (unchanged)
    failed=int,             # files that failed
    stored_chunks=int,      # total chunks stored
    removed_sources=int,    # orphaned sources removed
    errors=list[str],       # all error messages
    design_warnings=list[str],  # config validation warnings
)
```

---

## 7. Testing Guide

### Testability Map

| Module | Pure Logic | External Dependencies | Testability |
|--------|-----------|----------------------|-------------|
| document_ingestion.py | SHA-256, error formatting | File I/O (read_text_with_fallbacks) | High -- mock file reads |
| structure_detection.py | Regex heuristics | Docling (parse_with_docling) | High -- mock Docling |
| multimodal_processing.py | Note composition, overlay logic | VLM (generate_vision_notes) | High -- mock VLM |
| text_cleaning.py | Pure string transformation | None (delegates to support/markdown) | Very High -- no mocks needed |
| document_refactoring.py | Prompt construction, fallback | LLM (_llm_json) | High -- mock LLM |
| clean_store.py | All filesystem operations | Filesystem | Very High -- use tmp_path |
| workflow.py | Graph topology, routing logic | LangGraph | High -- mock node functions |
| pipeline/impl.py | Orchestration, manifest logic | Weaviate, embedder, KG, filesystem | Medium -- many mocks needed |

### Mock Boundaries

| Dependency | What to Mock | Why |
|-----------|-------------|-----|
| `read_text_with_fallbacks` | Return controlled text | Avoid real file I/O |
| `sha256_path` | Return deterministic hash | Ensure reproducible test assertions |
| `parse_with_docling` | Return `DoclingParseResult` or raise | Avoid Docling model dependency |
| `generate_vision_notes` | Return controlled notes or raise | Avoid VLM API dependency |
| `_llm_json` | Return controlled dict or `{}` | Avoid LLM API dependency |
| `get_weaviate_client` | Return mock context manager | Avoid Weaviate server dependency |
| `LocalBGEEmbeddings` | Return mock embedder | Avoid model loading |
| `KnowledgeGraphBuilder` | Return mock builder | Avoid graph construction |
| `load_manifest` / `save_manifest` | Use in-memory dict | Avoid manifest file I/O |

### Critical Test Scenarios (12)

1. **Happy path end-to-end**: UTF-8 text file with all stages enabled produces correct `processing_log` sequence and non-empty `cleaned_text`.
2. **Read failure short-circuit**: Non-existent source file produces `errors=["read_failed:..."]` and no downstream state.
3. **Docling strict failure**: Docling raises exception with `docling_strict=True` -- pipeline returns error and skips remaining stages.
4. **Docling non-strict fallback**: Docling raises exception with `docling_strict=False` -- regex heuristics produce structure, pipeline continues.
5. **Multimodal routing**: When `enable_multimodal_processing=True` and `has_figures=True`, multimodal node is invoked. When either is false, it is skipped.
6. **VLM strict failure**: VLM raises exception with `vision_strict=True` -- pipeline returns error.
7. **VLM non-strict fallback**: VLM raises exception with `vision_strict=False` -- baseline notes are returned.
8. **Refactoring disabled**: `enable_document_refactoring=False` -- `refactored_text` equals `cleaned_text`.
9. **LLM failure fallback**: LLM call fails -- `refactored_text` falls back to `cleaned_text`.
10. **CleanDocumentStore atomicity**: Interrupt during write does not leave partial files.
11. **Idempotency skip**: In update mode, unchanged source hash + existing clean store entry causes skip.
12. **Manifest migration**: Legacy manifest entry (keyed by filename) is matched via the fallback chain.

### State Invariants

- After successful completion: `len(processing_log) >= 3` (at least ingestion, structure, cleaning).
- If `errors` is non-empty: downstream fields (`cleaned_text`, `refactored_text`) may be empty.
- `source_hash` is a 64-character hex string when document_ingestion succeeds.
- `structure["has_figures"]` is always a `bool`.
- `multimodal_notes` is always a `list[str]` (empty if skipped).
- `refactored_text` is `None` when refactoring is skipped via the DAG route.

---

## 8. Operational Notes

### How to Run

**Full fresh ingestion:**
```python
from src.ingest.pipeline import ingest_directory
from pathlib import Path

result = ingest_directory(Path("documents/"), fresh=True)
print(f"Processed: {result.processed}, Skipped: {result.skipped}, Failed: {result.failed}")
```

**Incremental update:**
```python
result = ingest_directory(Path("documents/"), fresh=False, update=True)
```

**Single file ingestion (requires pre-built Runtime):**
```python
from src.ingest.pipeline import ingest_file
result = ingest_file(Path("documents/spec.pdf"), runtime, ...)
```

### Monitoring Signals

| Signal | Source | Interpretation |
|--------|--------|---------------|
| `processing_log` entries | Every node | Ordered stage completion. Look for `:failed` or `:skipped` suffixes. |
| `IngestionRunSummary.failed` | `ingest_directory()` | Non-zero indicates file-level failures. Check `errors` list. |
| `IngestionRunSummary.skipped` | `ingest_directory()` | High skip count in fresh mode suggests manifest corruption. |
| `design_warnings` | `verify_core_design()` | Config issues that may degrade quality (e.g., refactoring without LLM). |
| Logger `rag.ingest.pipeline` | `pipeline/impl.py` | `ingestion_start`, `ingestion_done`, `ingestion_failed`, `ingestion_skipped` messages. |
| Logger `rag.ingest.pipeline.stage` | `append_processing_log` | Per-stage verbose logging (when `verbose_stage_logs=True`). |

### Failure Modes and Debug Paths

| Failure Mode | Symptom | Debug Path |
|-------------|---------|------------|
| File read failure | `errors: ["read_failed:filename:..."]` | Check file path, permissions, encoding. Verify file exists and is readable. |
| Docling parse failure (strict) | `errors: ["docling_parse_failed:..."]` | Check Docling installation, model artifacts path, file format support. Try with `docling_strict=False`. |
| VLM failure (strict) | `errors: ["vision_processing_failed:..."]` | Check VLM model availability via `ensure_vision_ready()`. Verify API key and network connectivity. Try with `vision_strict=False`. |
| LLM failure (refactoring) | `refactored_text` equals `cleaned_text` | Check LLM availability, `enable_llm_metadata` flag. Review `_llm_json` debug logs. |
| Empty cleaned_text | `cleaned_text: ""` | Source file may be binary (PDF without Docling), empty, or entirely boilerplate. Check `raw_text` content. |
| Manifest corruption | `load_manifest()` logs warning, moves file to `.corrupt.*` | Manifest is automatically reset. Previous ingestion state is lost; run `fresh=True`. |
| Disk full during write | `CleanDocumentStore.write()` raises, temp files cleaned | Free disk space. Re-run ingestion. |
| Config validation failure | `ValueError` from `ingest_directory()` | Fix config (e.g., `chunk_overlap < chunk_size`). Check `verify_core_design()` errors. |

---

## 9. Known Limitations

### Explicit Scope Bounds

1. **Document refactoring is single-pass, not iterative.** The spec (FR-503) calls for a self-correcting loop with fact-check and completeness validation. The current implementation sends a single LLM call and accepts the result. The spec's validation loop (FR-504, FR-505, FR-508) is not yet implemented.

2. **Input text is truncated to 10,000 characters for refactoring.** Documents exceeding this limit are only partially refactored. The remainder passes through as cleaned text.

3. **No extraction confidence score.** The spec (FR-206) requires a 0.0-1.0 confidence score based on section tree depth, table completeness, and character density. The current implementation does not compute this score.

4. **No abbreviation auto-detection.** The spec (FR-205) requires detecting abbreviation definitions in document text. This is not implemented in the current structure_detection node.

5. **No review tier management.** The spec references review tiers (Fully/Partially/Self Reviewed) in the metadata envelope (FR-583). The current implementation does not assign or manage review tiers.

6. **Metadata envelope is incomplete.** The spec (FR-583) defines a required schema with `processing_timestamp`, `extraction_confidence`, `review_tier`, `section_tree_depth`, `table_count`, `figure_count`, `processing_flags`. The current `CleanDocumentStore.write()` receives a simplified metadata dict from the orchestrator that does not include all spec-required fields.

7. **Binary format extraction relies on Docling.** Without Docling enabled, PDF/DOCX files are read as raw text via the encoding fallback chain, producing garbled output. There are no standalone format-specific extractors for binary formats within the Document Processing DAG itself.

8. **No concurrent file processing.** `ingest_directory()` processes files sequentially in a loop. There is no parallelization.

9. **Figure notes are appended at the end, not at original positions.** The spec (FR-404) requires figure descriptions at the position where the figure originally appeared. The current implementation appends all figure notes as a `## Figure Notes` section at the end of the document.

10. **Regex figure detection captures references, not actual images.** The regex `r"\b(?:Figure|Fig\.)\s*\d+[A-Za-z]?\b"` detects textual references to figures, not embedded image elements. Actual image extraction for VLM processing requires Docling or markdown image parsing (handled in the vision support module).

---

## 10. Extension Guide

### Adding a New Processing Node

1. **Create the node function** in `src/ingest/doc_processing/nodes/new_node.py`:
```python
from src.ingest.doc_processing.state import DocumentProcessingState
from src.ingest.common.shared import append_processing_log

def new_node(state: DocumentProcessingState) -> dict:
    """Description of what this node does."""
    config = state["runtime"].config
    # ... processing logic ...
    return {
        "new_field": result,
        "processing_log": append_processing_log(state, "new_node:ok"),
    }
```

2. **Add the field to `DocumentProcessingState`** in `state.py`:
```python
class DocumentProcessingState(TypedDict, total=False):
    ...
    new_field: str  # or whatever type
```

3. **Register the node in `workflow.py`**:
```python
from src.ingest.doc_processing.nodes.new_node import new_node
graph.add_node("new_node", new_node)
```

4. **Wire the routing edges** in `workflow.py`. For example, to insert after text_cleaning and before document_refactoring:
```python
graph.add_edge("text_cleaning", "new_node")
graph.add_conditional_edges(
    "new_node",
    lambda state: "document_refactoring" if config_flag else "end",
    {...},
)
```

5. **Initialize the field in `impl.py`** (in the `initial_state` dict):
```python
initial_state: DocumentProcessingState = {
    ...
    "new_field": "",
}
```

6. **Add the node name to `PIPELINE_NODE_NAMES`** in `common/types.py`.

7. **Add configuration knob** to `IngestionConfig` in `common/types.py` if the node is optional.

### Adding a New Format Extractor

Format extraction is currently handled by:
- `read_text_with_fallbacks()` for text-based formats (in `common/utils.py`)
- Docling for binary formats (PDF, DOCX, PPTX, XLSX) via `parse_with_docling()`

To add a new format extractor:

1. **Create the extractor** in `src/ingest/support/new_format.py` with a function matching the pattern:
```python
def extract_new_format(source_path: Path) -> str:
    """Extract text from <format> files."""
    ...
    return extracted_text
```

2. **Integrate in document_ingestion or structure_detection** by checking the file extension and dispatching to the new extractor.

3. **Add the extension to `RAG_INGESTION_EXPORT_EXTENSIONS`** in `config/settings.py` so `ingest_directory()` discovers files with the new extension.

### Adding a New VLM Provider

VLM routing is handled entirely by LiteLLM. To add a new VLM provider:

1. **Configure the provider in LiteLLM** via the Router YAML config or `RAG_LLM_*` environment variables.
2. **Set the `vision` model alias** to point to the new provider/model.
3. **No code changes are needed.** The `generate_vision_notes()` function calls `get_llm_provider().vision_completion()` which routes through LiteLLM.

To add a provider that is not supported by LiteLLM:

1. **Implement the provider adapter** in `src/platform/llm/` following the existing provider interface.
2. **Register the adapter** with the LLM provider factory.
3. **Update the `vision` model alias** configuration.

---

## Appendix: Requirement Coverage

| Spec Requirement | Covered By (Module Section) | Coverage Notes |
|------------------|-----------------------------|---------------|
| FR-101 | `nodes/document_ingestion.py` -- Document Ingestion | Text-based formats via `read_text_with_fallbacks`. Binary formats require Docling (Node 2). |
| FR-102 | `pipeline/impl.py` -- Pipeline Orchestrator | File extension filtering via `RAG_INGESTION_EXPORT_EXTENSIONS`. |
| FR-103 | `nodes/document_ingestion.py` + `nodes/structure_detection.py` | Text conversion split: raw read in Node 1, Docling parse in Node 2. |
| FR-104 | `nodes/structure_detection.py` (via Docling) | PowerPoint extraction delegated to Docling. |
| FR-105 | `nodes/structure_detection.py` (via Docling) | Excel extraction delegated to Docling. |
| FR-106 | `nodes/document_ingestion.py` -- Document Ingestion | `sha256_path()` computes SHA-256 of source file bytes. |
| FR-107 | `pipeline/impl.py` -- Pipeline Orchestrator | `_local_source_identity()` generates deterministic `source_key` from `dev:ino`. |
| FR-108 | `nodes/document_ingestion.py` (via `read_text_with_fallbacks`) | UTF-8 -> Latin-1 -> CP1252 -> UTF-8 with replacement. |
| FR-109 | Not implemented | Domain vocabulary loading is not present in current source. |
| FR-110 | Partially covered | Architecture supports adding extractors, but no formal plugin interface exists. |
| FR-111 | `pipeline/impl.py` -- Pipeline Orchestrator | Controlled by `RAG_INGESTION_EXPORT_EXTENSIONS` (excludes `.log` by default). |
| FR-112 | `pipeline/impl.py` -- Pipeline Orchestrator | `_local_source_identity()` handles absolute paths; relative paths resolved via `Path.resolve()`. |
| FR-113 | Not implemented | SharePoint integration is planned for Phase 3. Connector abstraction (`connector` field in state) provides the extension point. |
| FR-201 | `nodes/structure_detection.py` -- Structure Detection | Heading extraction via Docling or regex. Full hierarchical tree is Docling-dependent. |
| FR-202 | `nodes/structure_detection.py` (via Docling) | Table extraction delegated to Docling. |
| FR-203 | `nodes/structure_detection.py` -- Structure Detection | Figure detection via Docling pictures or regex references. |
| FR-204 | `nodes/structure_detection.py` (via Docling) | Docling extracts figure images. Regex path does not export images. |
| FR-205 | Not implemented | Abbreviation auto-detection is not present in current source. |
| FR-206 | Not implemented | Extraction confidence score is not computed. |
| FR-207 | Not implemented | Low-confidence flagging depends on FR-206. |
| FR-208 | `nodes/structure_detection.py` -- Structure Detection | Docling vs. regex is configurable via `enable_docling_parser`. |
| FR-301 | `nodes/multimodal_processing.py` -- Multimodal Processing | VLM description via `generate_vision_notes()` in `support/vision.py`. |
| FR-302 | `workflow.py` -- DAG Topology | Conditional edge checks `has_figures` before routing to multimodal node. |
| FR-303 | `support/vision.py` (VLM prompt) | Prompt requests caption, visible_text, and tags. Quality depends on VLM model. |
| FR-304 | `support/vision.py` (VLM prompt) | Prompt does not request speculation. Enforcement depends on VLM model compliance. |
| FR-305 | Not implemented | VLM confidence score is not computed per description. |
| FR-306 | `support/vision.py` + LiteLLM | VLM provider swappable via LiteLLM configuration. |
| FR-307 | `nodes/multimodal_processing.py` -- Multimodal Processing | VLM failure in non-strict mode returns baseline notes (confidence implicit 0). |
| FR-401 | `nodes/text_cleaning.py` (via `clean_document`) | `clean_whitespace()` collapses spaces and newlines. |
| FR-402 | `nodes/text_cleaning.py` (via `strip_boilerplate`) | Boilerplate patterns in `support/document.py`. |
| FR-403 | `nodes/text_cleaning.py` (via `strip_boilerplate`) | Repeated header/footer detection via boilerplate patterns. |
| FR-404 | `nodes/text_cleaning.py` -- Text Cleaning | Figure notes appended as `## Figure Notes` section (not at original positions -- see Limitations). |
| FR-405 | `nodes/text_cleaning.py` (via Docling markdown output) | Table markdown preserved from Docling output or raw text. |
| FR-501 | `nodes/document_refactoring.py` -- Document Refactoring | LLM-based refactoring for self-contained paragraphs. |
| FR-502 | `workflow.py` + `nodes/document_refactoring.py` | Configurable via `enable_document_refactoring`. DAG routes around when disabled. |
| FR-503 | Not implemented | Self-correcting loop with iterations is not present. Single-pass only. |
| FR-504 | Not implemented | Fact-check validation per iteration is not present. |
| FR-505 | Not implemented | Completeness check per iteration is not present. |
| FR-506 | Partially covered | LLM prompt does not explicitly enforce all constraints. Depends on LLM compliance. |
| FR-507 | `nodes/document_refactoring.py` -- Document Refactoring | Fallback to `cleaned_text` when LLM returns empty or fails. |
| FR-508 | Not implemented | 80% completeness threshold is not present. |
| FR-509 | `pipeline/impl.py` -- Pipeline Orchestrator | Mirror artifacts written via `_write_refactor_mirror_artifacts()` when `persist_refactor_mirror=True`. |
| FR-510 | `common/shared.py` (`map_chunk_provenance`) | Provenance mapping with exact/fuzzy/paragraph fallback. Used in Phase 2 (Embedding Pipeline). |
| FR-511 | `common/shared.py` (`map_chunk_provenance`) | Provenance metadata includes `provenance_method` and `provenance_confidence`. |
| FR-581 | `clean_store.py` -- Clean Document Store | Markdown file written as `{safe_key}.md`. |
| FR-582 | `clean_store.py` -- Clean Document Store | Metadata envelope written as `{safe_key}.meta.json`. |
| FR-583 | Partially covered | Metadata contains `source_key`, `source_name`, `source_uri`, `source_id`, `connector`, `source_version`, `source_hash`. Missing: `processing_timestamp`, `extraction_confidence`, `review_tier`, `section_tree_depth`, `table_count`, `figure_count`, `processing_flags`. |
| FR-584 | `clean_store.py` + `pipeline/impl.py` | Clean text is the final output of all processing stages. |
| FR-585 | `nodes/text_cleaning.py` (via `normalize_headings_to_markdown`) | Headings converted to `#`/`##`/`###` Markdown syntax. |
| FR-586 | `clean_store.py` -- Clean Document Store | Atomic write via `.tmp` + `replace()`. On failure, temp files cleaned up, existing files preserved. |
| FR-587 | `clean_store.py` + `IngestionConfig.clean_store_dir` | Store directory configurable via `clean_store_dir`. |

---

## Companion Documents

| Document | Purpose | Relationship |
|----------|---------|-------------|
| DOCUMENT_PROCESSING_SPEC.md | Authoritative requirements specification | Source of FR numbers |
| DOCUMENT_PROCESSING_SPEC_SUMMARY.md | Executive summary | Stakeholder digest |
| DOCUMENT_PROCESSING_DESIGN.md | Task decomposition and code appendix | Original design |
| DOCUMENT_PROCESSING_IMPLEMENTATION.md | Six-phase implementation plan | Phase C produced this guide |
| **DOCUMENT_PROCESSING_ENGINEERING_GUIDE.md** (this document) | Post-implementation reference | Documents what was built |
| DOCUMENT_PROCESSING_MODULE_TESTS.md | Phase D white-box test plan | Derives tests from this guide |

**Flow:** Spec -> Spec Summary -> Design -> Implementation -> **Engineering Guide** -> Module Tests
