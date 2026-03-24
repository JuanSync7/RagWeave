# Ingestion Two-Phase Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the monolithic 13-node `src/ingest/` ingestion pipeline into two independent sub-packages (`doc_processing/` for nodes 1–5, `embedding/` for nodes 6–13) connected by a new `CleanDocumentStore`, with all docs updated and no stubs introduced.

**Architecture:** Phase 1 (`doc_processing/`) runs a 5-node LangGraph graph, returns `DocumentProcessingState`, and the orchestrator writes the clean text to `CleanDocumentStore`. Phase 2 (`embedding/`) reads from `CleanDocumentStore`, runs an 8-node LangGraph graph. The orchestrator in `pipeline/impl.py` coordinates both phases. `common/` and `support/` are shared unchanged.

**Tech Stack:** Python 3.11+, LangGraph `StateGraph`, `TypedDict`, `dataclasses`, `orjson`, `pytest`, existing `src.ingest.support.*` and `src.ingest.common.*` unchanged.

---

## File Map

### New files

| File | Responsibility |
|------|----------------|
| `src/ingest/clean_store.py` | `CleanDocumentStore` — atomic read/write of `{key}.md` + `{key}.meta.json` |
| `src/ingest/doc_processing/__init__.py` | Re-exports `run_document_processing` |
| `src/ingest/doc_processing/state.py` | `DocumentProcessingState` TypedDict |
| `src/ingest/doc_processing/workflow.py` | `build_document_processing_graph()` |
| `src/ingest/doc_processing/impl.py` | `run_document_processing(runtime, initial) -> DocumentProcessingState` |
| `src/ingest/doc_processing/nodes/__init__.py` | Empty |
| `src/ingest/doc_processing/nodes/document_ingestion.py` | Node 1 (migrated, `content_hash` → `source_hash`, skip logic removed) |
| `src/ingest/doc_processing/nodes/structure_detection.py` | Node 2 (migrated, state type updated) |
| `src/ingest/doc_processing/nodes/multimodal_processing.py` | Node 3 (migrated, state type updated) |
| `src/ingest/doc_processing/nodes/text_cleaning.py` | Node 4 (migrated, state type updated) |
| `src/ingest/doc_processing/nodes/document_refactoring.py` | Node 5 (migrated, state type updated) |
| `src/ingest/embedding/__init__.py` | Re-exports `run_embedding_pipeline` |
| `src/ingest/embedding/state.py` | `EmbeddingPipelineState` TypedDict |
| `src/ingest/embedding/workflow.py` | `build_embedding_graph()` |
| `src/ingest/embedding/impl.py` | `run_embedding_pipeline(runtime, initial) -> EmbeddingPipelineState` |
| `src/ingest/embedding/nodes/__init__.py` | Empty |
| `src/ingest/embedding/nodes/chunking.py` | Node 6 (migrated, state type updated) |
| `src/ingest/embedding/nodes/chunk_enrichment.py` | Node 7 (migrated, state type updated) |
| `src/ingest/embedding/nodes/metadata_generation.py` | Node 8 (migrated, state type updated) |
| `src/ingest/embedding/nodes/cross_reference_extraction.py` | Node 9 (migrated, state type updated) |
| `src/ingest/embedding/nodes/knowledge_graph_extraction.py` | Node 10 (migrated, state type updated) |
| `src/ingest/embedding/nodes/quality_validation.py` | Node 11 (migrated, state type updated) |
| `src/ingest/embedding/nodes/embedding_storage.py` | Node 12 (migrated, state type updated) |
| `src/ingest/embedding/nodes/knowledge_graph_storage.py` | Node 13 (migrated, state type updated) |
| `tests/ingest/test_clean_store.py` | Tests for `CleanDocumentStore` |
| `tests/ingest/test_two_phase_orchestrator.py` | Integration tests for `pipeline/impl.py` two-phase flow |

### Modified files

| File | Change |
|------|--------|
| `src/ingest/common/types.py` | Add `clean_store_dir: str` to `IngestionConfig`; deprecate `IngestState` with comment |
| `src/ingest/pipeline/impl.py` | Replace `_GRAPH = build_graph()` with two-phase orchestration |
| `src/ingest/pipeline/__init__.py` | Update imports if needed |
| `src/ingest/__init__.py` | Verify re-exports still correct |

### Deleted files

| File | Reason |
|------|--------|
| `src/ingest/nodes/` (entire directory) | All nodes migrated to sub-packages |
| `src/ingest/pipeline/workflow.py` | Replaced by `doc_processing/workflow.py` + `embedding/workflow.py` |

### Updated docs

| File | Change |
|------|--------|
| `src/ingest/README.md` | New directory structure |
| `src/ingest/doc_processing/README.md` | New |
| `src/ingest/embedding/README.md` | New |
| `src/ingest/pipeline/README.md` | Reflect workflow.py removal |
| `src/ingest/nodes/README.md` | Delete |
| `docs/ingestion/INGESTION_PIPELINE_ENGINEERING_GUIDE.md` | Update module map and import paths |
| `docs/ingestion/DOCUMENT_PROCESSING_IMPLEMENTATION.md` | Update file structure section |
| `docs/ingestion/EMBEDDING_PIPELINE_IMPLEMENTATION.md` | Update file structure section |

---

## Task 1 — Add `clean_store_dir` to `IngestionConfig`

**Files:**
- Modify: `src/ingest/common/types.py`

- [ ] **Step 1: Add the field**

  In `IngestionConfig`, after `mirror_output_dir`, add:

  ```python
  clean_store_dir: str = "data/clean_store"
  # Directory for CleanDocumentStore. Empty string disables persistent store.
  ```

- [ ] **Step 2: Verify import chain is intact**

  Run:
  ```
  python -c "from src.ingest.common.types import IngestionConfig; c = IngestionConfig(); print(c.clean_store_dir)"
  ```
  Expected: `data/clean_store`

- [ ] **Step 3: Commit**
  ```
  git add src/ingest/common/types.py
  git commit -m "feat(ingest): add clean_store_dir to IngestionConfig"
  ```

---

## Task 2 — Create `CleanDocumentStore`

**Files:**
- Create: `src/ingest/clean_store.py`
- Create: `tests/ingest/test_clean_store.py`

- [ ] **Step 1: Write failing tests**

  Create `tests/ingest/test_clean_store.py`:

  ```python
  """Tests for CleanDocumentStore atomic read/write."""
  import pytest
  from pathlib import Path
  from src.ingest.clean_store import CleanDocumentStore


  def test_write_and_read(tmp_path):
      store = CleanDocumentStore(tmp_path)
      store.write("key1", "hello world", {"source_name": "doc.pdf"})
      text, meta = store.read("key1")
      assert text == "hello world"
      assert meta["source_name"] == "doc.pdf"


  def test_exists_false_before_write(tmp_path):
      store = CleanDocumentStore(tmp_path)
      assert not store.exists("missing_key")


  def test_exists_true_after_write(tmp_path):
      store = CleanDocumentStore(tmp_path)
      store.write("key2", "content", {})
      assert store.exists("key2")


  def test_clean_hash_matches_content(tmp_path):
      import hashlib
      store = CleanDocumentStore(tmp_path)
      store.write("key3", "hello", {})
      expected = hashlib.sha256("hello".encode("utf-8")).hexdigest()
      assert store.clean_hash("key3") == expected


  def test_delete_removes_entry(tmp_path):
      store = CleanDocumentStore(tmp_path)
      store.write("key4", "bye", {})
      store.delete("key4")
      assert not store.exists("key4")


  def test_list_keys(tmp_path):
      store = CleanDocumentStore(tmp_path)
      store.write("a", "x", {})
      store.write("b", "y", {})
      assert set(store.list_keys()) == {"a", "b"}


  def test_read_raises_if_missing(tmp_path):
      store = CleanDocumentStore(tmp_path)
      with pytest.raises(FileNotFoundError):
          store.read("no_such_key")


  def test_write_is_atomic(tmp_path):
      """Interrupted write must not leave partial files."""
      store = CleanDocumentStore(tmp_path)
      store.write("key5", "content", {"x": 1})
      # Overwrite with new content — should not leave .tmp behind
      store.write("key5", "new content", {"x": 2})
      text, meta = store.read("key5")
      assert text == "new content"
      assert meta["x"] == 2
      assert not list(tmp_path.glob("*.tmp"))
  ```

- [ ] **Step 2: Run tests to verify they fail**

  ```
  pytest tests/ingest/test_clean_store.py -v
  ```
  Expected: `ImportError: cannot import name 'CleanDocumentStore'`

- [ ] **Step 3: Implement `CleanDocumentStore`**

  Create `src/ingest/clean_store.py`:

  ```python
  # @summary
  # Atomic persistent store for clean Markdown documents between pipeline phases.
  # Exports: CleanDocumentStore
  # Deps: orjson, hashlib, pathlib
  # @end-summary

  """CleanDocumentStore — atomic read/write of clean Markdown between pipeline phases."""

  from __future__ import annotations

  import hashlib
  import orjson
  from pathlib import Path


  class CleanDocumentStore:
      """Persistent store for clean Markdown output from Phase 1.

      Stores each document as two files:
        - ``{store_dir}/{source_key}.md``       — clean Markdown text
        - ``{store_dir}/{source_key}.meta.json`` — source identity metadata

      All writes are atomic: content is written to a ``.tmp`` file and
      then renamed into place, preventing partial reads on failure.

      Args:
          store_dir: Directory in which to store documents. Created on first write.
      """

      def __init__(self, store_dir: Path) -> None:
          self._dir = Path(store_dir)

      def _md_path(self, source_key: str) -> Path:
          safe_key = source_key.replace("/", "_").replace(":", "_")
          return self._dir / f"{safe_key}.md"

      def _meta_path(self, source_key: str) -> Path:
          safe_key = source_key.replace("/", "_").replace(":", "_")
          return self._dir / f"{safe_key}.meta.json"

      def write(self, source_key: str, text: str, meta: dict) -> None:
          """Atomically write clean text and metadata for a source key.

          Args:
              source_key: Stable source identifier.
              text: Clean Markdown text (output of Phase 1).
              meta: Source identity and provenance metadata dict.
          """
          self._dir.mkdir(parents=True, exist_ok=True)
          md_path = self._md_path(source_key)
          meta_path = self._meta_path(source_key)

          tmp_md = md_path.with_suffix(".md.tmp")
          tmp_meta = meta_path.with_suffix(".meta.json.tmp")

          try:
              tmp_md.write_text(text, encoding="utf-8")
              tmp_meta.write_bytes(orjson.dumps(meta))
              tmp_md.replace(md_path)
              tmp_meta.replace(meta_path)
          except Exception:
              tmp_md.unlink(missing_ok=True)
              tmp_meta.unlink(missing_ok=True)
              raise

      def read(self, source_key: str) -> tuple[str, dict]:
          """Read clean text and metadata for a source key.

          Args:
              source_key: Stable source identifier.

          Returns:
              Tuple of (clean_text, meta_dict).

          Raises:
              FileNotFoundError: If no entry exists for this key.
          """
          md_path = self._md_path(source_key)
          meta_path = self._meta_path(source_key)
          if not md_path.exists():
              raise FileNotFoundError(f"CleanDocumentStore: no entry for {source_key!r}")
          text = md_path.read_text(encoding="utf-8")
          meta = orjson.loads(meta_path.read_bytes()) if meta_path.exists() else {}
          return text, meta

      def exists(self, source_key: str) -> bool:
          """Return True if a clean document entry exists for this key."""
          return self._md_path(source_key).exists()

      def clean_hash(self, source_key: str) -> str:
          """Return the SHA-256 hash of the stored clean text.

          Args:
              source_key: Stable source identifier.

          Returns:
              Hex-encoded SHA-256 digest of the stored Markdown bytes.

          Raises:
              FileNotFoundError: If no entry exists for this key.
          """
          md_path = self._md_path(source_key)
          if not md_path.exists():
              raise FileNotFoundError(f"CleanDocumentStore: no entry for {source_key!r}")
          return hashlib.sha256(md_path.read_bytes()).hexdigest()

      def delete(self, source_key: str) -> None:
          """Remove the clean document entry for this key (both files).

          Args:
              source_key: Stable source identifier.
          """
          self._md_path(source_key).unlink(missing_ok=True)
          self._meta_path(source_key).unlink(missing_ok=True)

      def list_keys(self) -> list[str]:
          """Return all source keys currently stored.

          Returns:
              List of source_key strings with '/' and ':' restored from '_'.
          """
          if not self._dir.exists():
              return []
          keys = []
          for p in self._dir.glob("*.md"):
              if p.suffix == ".md" and not p.name.endswith(".md.tmp"):
                  # Reverse the safe_key transformation (best-effort, for listing)
                  keys.append(p.stem)
          return keys
  ```

- [ ] **Step 4: Run tests to verify they pass**

  ```
  pytest tests/ingest/test_clean_store.py -v
  ```
  Expected: All 8 tests PASS.

- [ ] **Step 5: Commit**
  ```
  git add src/ingest/clean_store.py tests/ingest/test_clean_store.py
  git commit -m "feat(ingest): add CleanDocumentStore with atomic read/write"
  ```

---

## Task 3 — Create Phase 1 State Contract

**Files:**
- Create: `src/ingest/doc_processing/__init__.py`
- Create: `src/ingest/doc_processing/state.py`
- Create: `src/ingest/doc_processing/nodes/__init__.py`

- [ ] **Step 1: Create package files**

  `src/ingest/doc_processing/__init__.py`:
  ```python
  """Document Processing Pipeline — Phase 1 of the two-phase ingestion pipeline."""
  from src.ingest.doc_processing.impl import run_document_processing

  __all__ = ["run_document_processing"]
  ```

  `src/ingest/doc_processing/nodes/__init__.py`:
  ```python
  """Phase 1 node implementations for the Document Processing Pipeline."""
  ```

- [ ] **Step 2: Create `DocumentProcessingState`**

  `src/ingest/doc_processing/state.py`:
  ```python
  # @summary
  # LangGraph TypedDict state contract for the Phase 1 Document Processing Pipeline.
  # Exports: DocumentProcessingState
  # Deps: src.ingest.common.types
  # @end-summary

  """State contract for the Document Processing Pipeline (Phase 1, nodes 1–5)."""

  from __future__ import annotations

  from typing import Any, Dict, List, Optional, TypedDict

  from src.ingest.common.types import Runtime


  class DocumentProcessingState(TypedDict, total=False):
      """Shared state flowing through the 5-node Document Processing DAG.

      Populated progressively as nodes complete. The orchestrator is responsible
      for the idempotency check (should_skip) BEFORE invoking this pipeline —
      these fields are not present in this state.

      Fields
      ------
      runtime : Runtime
          Shared runtime dependencies (config, embedder, weaviate, kg_builder).
      source_path : str
          Absolute path to the source file.
      source_name : str
          Display name (relative path or human-readable label).
      source_uri : str
          Stable URI for the source (e.g. file:///...).
      source_key : str
          Stable source identity key (e.g. local_fs:<dev>:<ino>).
      source_id : str
          OS-level stable identity (dev:inode).
      source_hash : str
          SHA-256 of source file bytes. Renamed from ``content_hash`` in IngestState.
      connector : str
          Connector identifier (e.g. ``local_fs``).
      source_version : str
          Source version string (mtime nanoseconds as string).
      raw_text : str
          Format-converted plain/markdown text from the source file.
      structure : dict
          Structure detection results: ``has_figures`` (bool), ``figures`` (list),
          ``heading_count`` (int), ``docling_enabled`` (bool), ``docling_model`` (str).
      multimodal_notes : list[str]
          Vision-generated notes for figures. Empty list if multimodal disabled.
      cleaned_text : str
          Boilerplate-stripped, unicode-normalised Markdown text.
      refactored_text : str | None
          LLM-rewritten text (self-contained paragraphs). None if refactoring disabled.
      errors : list[str]
          Error messages from any node. Non-empty triggers orchestrator failure path.
      processing_log : list[str]
          Stage completion log entries for observability.
      """

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

- [ ] **Step 3: Verify import works**
  ```
  python -c "from src.ingest.doc_processing.state import DocumentProcessingState; print('ok')"
  ```
  Expected: `ok`

- [ ] **Step 4: Commit**
  ```
  git add src/ingest/doc_processing/
  git commit -m "feat(ingest): add DocumentProcessingState and Phase 1 package scaffold"
  ```

---

## Task 4 — Create Phase 2 State Contract

**Files:**
- Create: `src/ingest/embedding/__init__.py`
- Create: `src/ingest/embedding/state.py`
- Create: `src/ingest/embedding/nodes/__init__.py`

- [ ] **Step 1: Create package files**

  `src/ingest/embedding/__init__.py`:
  ```python
  """Embedding Pipeline — Phase 2 of the two-phase ingestion pipeline."""
  from src.ingest.embedding.impl import run_embedding_pipeline

  __all__ = ["run_embedding_pipeline"]
  ```

  `src/ingest/embedding/nodes/__init__.py`:
  ```python
  """Phase 2 node implementations for the Embedding Pipeline."""
  ```

- [ ] **Step 2: Create `EmbeddingPipelineState`**

  `src/ingest/embedding/state.py`:
  ```python
  # @summary
  # LangGraph TypedDict state contract for the Phase 2 Embedding Pipeline.
  # Exports: EmbeddingPipelineState
  # Deps: src.ingest.common.types, src.ingest.common.schemas
  # @end-summary

  """State contract for the Embedding Pipeline (Phase 2, nodes 6–13)."""

  from __future__ import annotations

  from typing import Any, Dict, List, Optional, TypedDict

  from src.ingest.common.schemas import ProcessedChunk
  from src.ingest.common.types import Runtime


  class EmbeddingPipelineState(TypedDict, total=False):
      """Shared state flowing through the 8-node Embedding Pipeline DAG.

      Initial fields are populated by the orchestrator from CleanDocumentStore
      before the graph is invoked.

      Fields
      ------
      runtime : Runtime
          Shared runtime dependencies.
      source_key : str
          Stable source identity key.
      source_name : str
          Display name.
      source_uri : str
          Stable URI for the source.
      source_id : str
          OS-level stable identity.
      source_version : str
          Source version string.
      connector : str
          Connector identifier.
      raw_text : str
          The clean Markdown text read from CleanDocumentStore (used as raw_text
          for compatibility with chunking/enrichment nodes).
      cleaned_text : str
          Same as raw_text for Phase 2 entry point — the clean text is the input.
      refactored_text : str | None
          Stored refactored text from Phase 1, if present in CleanDocumentStore meta.
      clean_hash : str
          SHA-256 of the clean text (for change detection on Phase 2 re-runs).
      chunks : list[ProcessedChunk]
          Chunks produced by chunking_node (node 6).
      enriched_chunks : list[ProcessedChunk]
          Chunks with IDs and provenance from chunk_enrichment_node (node 7).
      metadata_summary : str
          LLM-generated document summary from metadata_generation_node (node 8).
      metadata_keywords : list[str]
          Extracted keywords from metadata_generation_node (node 8).
      cross_references : list[dict[str, str]]
          Pattern-matched cross-references from cross_reference_extraction_node (node 9).
      kg_triples : list[dict[str, Any]]
          Extracted KG triples (subject/predicate/object) from kg_extraction_node (node 10).
      stored_count : int
          Number of chunks successfully stored in Weaviate from embedding_storage_node (node 12).
      errors : list[str]
          Error messages from any node.
      processing_log : list[str]
          Stage completion log entries.
      """

      runtime: Runtime
      source_key: str
      source_name: str
      source_uri: str
      source_id: str
      source_version: str
      connector: str
      raw_text: str
      cleaned_text: str
      refactored_text: Optional[str]
      clean_hash: str
      chunks: List[ProcessedChunk]
      enriched_chunks: List[ProcessedChunk]
      metadata_summary: str
      metadata_keywords: List[str]
      cross_references: List[Dict[str, str]]
      kg_triples: List[Dict[str, Any]]
      stored_count: int
      errors: List[str]
      processing_log: List[str]
  ```

- [ ] **Step 3: Verify import works**
  ```
  python -c "from src.ingest.embedding.state import EmbeddingPipelineState; print('ok')"
  ```
  Expected: `ok`

- [ ] **Step 4: Commit**
  ```
  git add src/ingest/embedding/
  git commit -m "feat(ingest): add EmbeddingPipelineState and Phase 2 package scaffold"
  ```

---

## Task 5 — Migrate Phase 1 Nodes

**Files:**
- Create: `src/ingest/doc_processing/nodes/document_ingestion.py` (migrated + simplified)
- Create: `src/ingest/doc_processing/nodes/structure_detection.py` (migrated)
- Create: `src/ingest/doc_processing/nodes/multimodal_processing.py` (migrated)
- Create: `src/ingest/doc_processing/nodes/text_cleaning.py` (migrated)
- Create: `src/ingest/doc_processing/nodes/document_refactoring.py` (migrated)

For each node:
- Replace `from src.ingest.common.types import IngestState` with `from src.ingest.doc_processing.state import DocumentProcessingState`
- Change function signature type hint: `state: IngestState` → `state: DocumentProcessingState`
- For `document_ingestion.py` only: rename `content_hash` → `source_hash` in the returned dict, and remove the `should_skip`/`existing_hash` check entirely (see Step 1 below)
- All other business logic remains identical

- [ ] **Step 1: Migrate `document_ingestion.py`**

  Create `src/ingest/doc_processing/nodes/document_ingestion.py`:

  ```python
  # @summary
  # LangGraph node for source file read and SHA-256 hash computation (Phase 1).
  # Exports: document_ingestion_node
  # Deps: src.ingest.common.utils, src.ingest.common.shared, src.ingest.doc_processing.state
  # @end-summary

  """Document ingestion node — Phase 1."""

  from __future__ import annotations

  from pathlib import Path

  from src.ingest.common.utils import read_text_with_fallbacks, sha256_path
  from src.ingest.common.shared import append_processing_log
  from src.ingest.doc_processing.state import DocumentProcessingState


  def document_ingestion_node(state: DocumentProcessingState) -> dict:
      """Read source content and compute SHA-256 hash.

      The idempotency skip check is handled by the orchestrator before this
      node is invoked — this node does not read or write ``should_skip``.

      Args:
          state: Document processing pipeline state.

      Returns:
          Partial state update with ``raw_text``, ``source_hash``, and
          ``processing_log``. On read failure, returns an ``errors`` payload
          to short-circuit the workflow.
      """
      source_path = Path(state["source_path"])
      try:
          raw_text = read_text_with_fallbacks(source_path)
      except Exception as exc:
          return {
              "errors": [f"read_failed:{source_path.name}:{exc}"],
              "processing_log": append_processing_log(state, "document_ingestion:failed"),
          }
      source_hash = sha256_path(source_path)
      return {
          "raw_text": raw_text,
          "source_hash": source_hash,
          "processing_log": append_processing_log(state, "document_ingestion:ok"),
      }
  ```

- [ ] **Step 2: Migrate `structure_detection.py`**

  Copy `src/ingest/nodes/structure_detection.py` to `src/ingest/doc_processing/nodes/structure_detection.py`.
  Change:
  - `from src.ingest.common.types import IngestState` → `from src.ingest.doc_processing.state import DocumentProcessingState`
  - `def structure_detection_node(state: IngestState)` → `def structure_detection_node(state: DocumentProcessingState)`
  - Update `@summary` Deps line to reference `doc_processing.state`

- [ ] **Step 3: Migrate `multimodal_processing.py`**

  Copy `src/ingest/nodes/multimodal_processing.py` to `src/ingest/doc_processing/nodes/multimodal_processing.py`.
  Apply same import swap as Step 2.

- [ ] **Step 4: Migrate `text_cleaning.py`**

  Copy `src/ingest/nodes/text_cleaning.py` to `src/ingest/doc_processing/nodes/text_cleaning.py`.
  Apply same import swap as Step 2.

- [ ] **Step 5: Migrate `document_refactoring.py`**

  Copy `src/ingest/nodes/document_refactoring.py` to `src/ingest/doc_processing/nodes/document_refactoring.py`.
  Apply same import swap as Step 2.

- [ ] **Step 6: Verify all nodes importable**
  ```
  python -c "
  from src.ingest.doc_processing.nodes.document_ingestion import document_ingestion_node
  from src.ingest.doc_processing.nodes.structure_detection import structure_detection_node
  from src.ingest.doc_processing.nodes.multimodal_processing import multimodal_processing_node
  from src.ingest.doc_processing.nodes.text_cleaning import text_cleaning_node
  from src.ingest.doc_processing.nodes.document_refactoring import document_refactoring_node
  print('all Phase 1 nodes ok')
  "
  ```
  Expected: `all Phase 1 nodes ok`

- [ ] **Step 7: Commit**
  ```
  git add src/ingest/doc_processing/nodes/
  git commit -m "feat(ingest): migrate Phase 1 nodes to doc_processing/nodes/"
  ```

---

## Task 6 — Migrate Phase 2 Nodes

**Files:**
- Create all 8 files under `src/ingest/embedding/nodes/` (migrated from `src/ingest/nodes/`)

For each node:
- Replace `from src.ingest.common.types import IngestState` with `from src.ingest.embedding.state import EmbeddingPipelineState`
- Change function signature type hint: `state: IngestState` → `state: EmbeddingPipelineState`
- No business logic changes
- Update `@summary` Deps line

Nodes to migrate:
- `chunking.py`
- `chunk_enrichment.py`
- `metadata_generation.py`
- `cross_reference_extraction.py`
- `knowledge_graph_extraction.py`
- `quality_validation.py`
- `embedding_storage.py`
- `knowledge_graph_storage.py`

- [ ] **Step 1: Migrate all 8 nodes**

  For each node file, copy from `src/ingest/nodes/{name}.py` to `src/ingest/embedding/nodes/{name}.py` and apply the import swap described above.

- [ ] **Step 2: Verify all nodes importable**
  ```
  python -c "
  from src.ingest.embedding.nodes.chunking import chunking_node
  from src.ingest.embedding.nodes.chunk_enrichment import chunk_enrichment_node
  from src.ingest.embedding.nodes.metadata_generation import metadata_generation_node
  from src.ingest.embedding.nodes.cross_reference_extraction import cross_reference_extraction_node
  from src.ingest.embedding.nodes.knowledge_graph_extraction import knowledge_graph_extraction_node
  from src.ingest.embedding.nodes.quality_validation import quality_validation_node
  from src.ingest.embedding.nodes.embedding_storage import embedding_storage_node
  from src.ingest.embedding.nodes.knowledge_graph_storage import knowledge_graph_storage_node
  print('all Phase 2 nodes ok')
  "
  ```
  Expected: `all Phase 2 nodes ok`

- [ ] **Step 3: Commit**
  ```
  git add src/ingest/embedding/nodes/
  git commit -m "feat(ingest): migrate Phase 2 nodes to embedding/nodes/"
  ```

---

## Task 7 — Build Phase 1 Workflow and Impl

**Files:**
- Create: `src/ingest/doc_processing/workflow.py`
- Create: `src/ingest/doc_processing/impl.py`

- [ ] **Step 1: Create Phase 1 workflow**

  `src/ingest/doc_processing/workflow.py`:

  ```python
  # @summary
  # LangGraph StateGraph for the 5-node Document Processing Pipeline (Phase 1).
  # Exports: build_document_processing_graph
  # Deps: langgraph.graph, src.ingest.doc_processing.nodes.*, src.ingest.doc_processing.state
  # @end-summary

  """Phase 1 LangGraph workflow for document processing."""

  from __future__ import annotations

  from langgraph.graph import END, StateGraph

  from src.ingest.doc_processing.nodes.document_ingestion import document_ingestion_node
  from src.ingest.doc_processing.nodes.structure_detection import structure_detection_node
  from src.ingest.doc_processing.nodes.multimodal_processing import multimodal_processing_node
  from src.ingest.doc_processing.nodes.text_cleaning import text_cleaning_node
  from src.ingest.doc_processing.nodes.document_refactoring import document_refactoring_node
  from src.ingest.doc_processing.state import DocumentProcessingState


  def build_document_processing_graph():
      """Compile the Phase 1 Document Processing StateGraph.

      Routing:
      - After document_ingestion: short-circuit to END on errors.
      - After structure_detection: multimodal_processing if enabled + has_figures, else text_cleaning.
      - After text_cleaning: document_refactoring if enabled, else END.

      Returns:
          Compiled LangGraph graph accepting ``DocumentProcessingState``.
      """
      graph = StateGraph(DocumentProcessingState)
      graph.add_node("document_ingestion", document_ingestion_node)
      graph.add_node("structure_detection", structure_detection_node)
      graph.add_node("multimodal_processing", multimodal_processing_node)
      graph.add_node("text_cleaning", text_cleaning_node)
      graph.add_node("document_refactoring", document_refactoring_node)

      graph.set_entry_point("document_ingestion")
      graph.add_conditional_edges(
          "document_ingestion",
          lambda state: "end" if state.get("errors") else "structure_detection",
          {"structure_detection": "structure_detection", "end": END},
      )
      graph.add_conditional_edges(
          "structure_detection",
          lambda state: (
              "multimodal_processing"
              if (
                  state["runtime"].config.enable_multimodal_processing
                  and state.get("structure", {}).get("has_figures")
              )
              else "text_cleaning"
          ),
          {"multimodal_processing": "multimodal_processing", "text_cleaning": "text_cleaning"},
      )
      graph.add_edge("multimodal_processing", "text_cleaning")
      graph.add_conditional_edges(
          "text_cleaning",
          lambda state: (
              "document_refactoring"
              if state["runtime"].config.enable_document_refactoring
              else "end"
          ),
          {"document_refactoring": "document_refactoring", "end": END},
      )
      graph.add_edge("document_refactoring", END)
      return graph.compile()
  ```

- [ ] **Step 2: Create Phase 1 impl**

  `src/ingest/doc_processing/impl.py`:

  ```python
  # @summary
  # Phase 1 orchestrator: compiles and invokes the Document Processing LangGraph.
  # Exports: run_document_processing
  # Deps: src.ingest.doc_processing.workflow, src.ingest.doc_processing.state, src.ingest.common.types
  # @end-summary

  """Phase 1 runtime implementation for document processing."""

  from __future__ import annotations

  from src.ingest.common.types import Runtime
  from src.ingest.doc_processing.state import DocumentProcessingState
  from src.ingest.doc_processing.workflow import build_document_processing_graph

  _GRAPH = build_document_processing_graph()


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
      """Run the Phase 1 Document Processing pipeline for a single source file.

      The caller is responsible for the idempotency check before invoking this
      function. This function always runs the pipeline regardless of any prior
      state.

      Args:
          runtime: Shared runtime dependencies.
          source_path: Absolute path to the source file.
          source_name: Display name for the source.
          source_uri: Stable URI for the source.
          source_key: Stable source identity key.
          source_id: OS-level stable identity.
          connector: Connector identifier.
          source_version: Source version string (mtime nanoseconds).

      Returns:
          Final ``DocumentProcessingState`` after all nodes have run.
      """
      initial_state: DocumentProcessingState = {
          "runtime": runtime,
          "source_path": source_path,
          "source_name": source_name,
          "source_uri": source_uri,
          "source_key": source_key,
          "source_id": source_id,
          "connector": connector,
          "source_version": source_version,
          "source_hash": "",
          "raw_text": "",
          "structure": {},
          "multimodal_notes": [],
          "cleaned_text": "",
          "refactored_text": None,
          "errors": [],
          "processing_log": [],
      }
      return _GRAPH.invoke(initial_state)
  ```

- [ ] **Step 3: Verify graph compiles and invoke succeeds (dry run)**
  ```
  python -c "
  from src.ingest.doc_processing.workflow import build_document_processing_graph
  g = build_document_processing_graph()
  print('Phase 1 graph compiled ok:', g)
  "
  ```
  Expected: `Phase 1 graph compiled ok: ...`

- [ ] **Step 4: Commit**
  ```
  git add src/ingest/doc_processing/workflow.py src/ingest/doc_processing/impl.py
  git commit -m "feat(ingest): add Phase 1 workflow and impl"
  ```

---

## Task 8 — Build Phase 2 Workflow and Impl

**Files:**
- Create: `src/ingest/embedding/workflow.py`
- Create: `src/ingest/embedding/impl.py`

- [ ] **Step 1: Create Phase 2 workflow**

  `src/ingest/embedding/workflow.py`:

  ```python
  # @summary
  # LangGraph StateGraph for the 8-node Embedding Pipeline (Phase 2).
  # Exports: build_embedding_graph
  # Deps: langgraph.graph, src.ingest.embedding.nodes.*, src.ingest.embedding.state
  # @end-summary

  """Phase 2 LangGraph workflow for embedding and storage."""

  from __future__ import annotations

  from langgraph.graph import END, StateGraph

  from src.ingest.embedding.nodes.chunk_enrichment import chunk_enrichment_node
  from src.ingest.embedding.nodes.chunking import chunking_node
  from src.ingest.embedding.nodes.cross_reference_extraction import cross_reference_extraction_node
  from src.ingest.embedding.nodes.embedding_storage import embedding_storage_node
  from src.ingest.embedding.nodes.knowledge_graph_extraction import knowledge_graph_extraction_node
  from src.ingest.embedding.nodes.knowledge_graph_storage import knowledge_graph_storage_node
  from src.ingest.embedding.nodes.metadata_generation import metadata_generation_node
  from src.ingest.embedding.nodes.quality_validation import quality_validation_node
  from src.ingest.embedding.state import EmbeddingPipelineState


  def build_embedding_graph():
      """Compile the Phase 2 Embedding Pipeline StateGraph.

      Routing:
      - cross_reference_extraction: only if config.enable_cross_reference_extraction.
      - knowledge_graph_extraction: only if config.enable_knowledge_graph_extraction.
      - knowledge_graph_storage: only if config.enable_knowledge_graph_storage.

      Returns:
          Compiled LangGraph graph accepting ``EmbeddingPipelineState``.
      """
      graph = StateGraph(EmbeddingPipelineState)
      graph.add_node("chunking", chunking_node)
      graph.add_node("chunk_enrichment", chunk_enrichment_node)
      graph.add_node("metadata_generation", metadata_generation_node)
      graph.add_node("cross_reference_extraction", cross_reference_extraction_node)
      graph.add_node("knowledge_graph_extraction", knowledge_graph_extraction_node)
      graph.add_node("quality_validation", quality_validation_node)
      graph.add_node("embedding_storage", embedding_storage_node)
      graph.add_node("knowledge_graph_storage", knowledge_graph_storage_node)

      graph.set_entry_point("chunking")
      graph.add_edge("chunking", "chunk_enrichment")
      graph.add_edge("chunk_enrichment", "metadata_generation")
      graph.add_conditional_edges(
          "metadata_generation",
          lambda state: (
              "cross_reference_extraction"
              if state["runtime"].config.enable_cross_reference_extraction
              else "knowledge_graph_extraction"
          ),
          {
              "cross_reference_extraction": "cross_reference_extraction",
              "knowledge_graph_extraction": "knowledge_graph_extraction",
          },
      )
      graph.add_edge("cross_reference_extraction", "knowledge_graph_extraction")
      # knowledge_graph_extraction_node checks config.enable_knowledge_graph_extraction
      # internally and returns early if disabled — always run the node, no conditional edge.
      graph.add_edge("knowledge_graph_extraction", "quality_validation")
      graph.add_edge("quality_validation", "embedding_storage")
      graph.add_conditional_edges(
          "embedding_storage",
          lambda state: (
              "knowledge_graph_storage"
              if state["runtime"].config.enable_knowledge_graph_storage
              else "end"
          ),
          {"knowledge_graph_storage": "knowledge_graph_storage", "end": END},
      )
      graph.add_edge("knowledge_graph_storage", END)
      return graph.compile()
  ```

- [ ] **Step 2: Create Phase 2 impl**

  `src/ingest/embedding/impl.py`:

  ```python
  # @summary
  # Phase 2 orchestrator: compiles and invokes the Embedding Pipeline LangGraph.
  # Exports: run_embedding_pipeline
  # Deps: src.ingest.embedding.workflow, src.ingest.embedding.state, src.ingest.common.types
  # @end-summary

  """Phase 2 runtime implementation for the embedding pipeline."""

  from __future__ import annotations

  from typing import Optional

  from src.ingest.common.types import Runtime
  from src.ingest.embedding.state import EmbeddingPipelineState
  from src.ingest.embedding.workflow import build_embedding_graph

  _GRAPH = build_embedding_graph()


  def run_embedding_pipeline(
      runtime: Runtime,
      source_key: str,
      source_name: str,
      source_uri: str,
      source_id: str,
      connector: str,
      source_version: str,
      clean_text: str,
      clean_hash: str,
      refactored_text: Optional[str] = None,
  ) -> EmbeddingPipelineState:
      """Run the Phase 2 Embedding Pipeline for a single clean document.

      Args:
          runtime: Shared runtime dependencies.
          source_key: Stable source identity key.
          source_name: Display name for the source.
          source_uri: Stable URI for the source.
          source_id: OS-level stable identity.
          connector: Connector identifier.
          source_version: Source version string.
          clean_text: Clean Markdown text from CleanDocumentStore.
          clean_hash: SHA-256 of ``clean_text`` for change detection.
          refactored_text: LLM-refactored text from Phase 1, if available.

      Returns:
          Final ``EmbeddingPipelineState`` after all nodes have run.
      """
      initial_state: EmbeddingPipelineState = {
          "runtime": runtime,
          "source_key": source_key,
          "source_name": source_name,
          "source_uri": source_uri,
          "source_id": source_id,
          "connector": connector,
          "source_version": source_version,
          "raw_text": clean_text,
          "cleaned_text": clean_text,
          "refactored_text": refactored_text,
          "clean_hash": clean_hash,
          "chunks": [],
          "enriched_chunks": [],
          "metadata_summary": "",
          "metadata_keywords": [],
          "cross_references": [],
          "kg_triples": [],
          "stored_count": 0,
          "errors": [],
          "processing_log": [],
      }
      return _GRAPH.invoke(initial_state)
  ```

- [ ] **Step 3: Verify Phase 2 graph compiles**
  ```
  python -c "
  from src.ingest.embedding.workflow import build_embedding_graph
  g = build_embedding_graph()
  print('Phase 2 graph compiled ok:', g)
  "
  ```
  Expected: `Phase 2 graph compiled ok: ...`

- [ ] **Step 4: Commit**
  ```
  git add src/ingest/embedding/workflow.py src/ingest/embedding/impl.py
  git commit -m "feat(ingest): add Phase 2 workflow and impl"
  ```

---

## Task 9 — Rewrite Orchestrator (`pipeline/impl.py`)

**Files:**
- Modify: `src/ingest/pipeline/impl.py`

This is the most substantial change. The orchestrator replaces the single `_GRAPH.invoke()` call with a two-phase flow. All existing helper functions (`_local_source_identity`, `_mirror_file_stem`, `_write_refactor_mirror_artifacts`, `_normalize_manifest_entries`, `_find_manifest_entry`, `verify_core_design`, `ingest_directory`) remain — only `ingest_file` changes significantly, and the module-level `_GRAPH` import is removed.

- [ ] **Step 1: Update imports at top of `pipeline/impl.py`**

  Remove:
  ```python
  from src.ingest.pipeline.workflow import build_graph
  ```
  Remove the line:
  ```python
  _GRAPH = build_graph()
  ```

  Add:
  ```python
  from src.ingest.clean_store import CleanDocumentStore
  from src.ingest.doc_processing.impl import run_document_processing
  from src.ingest.embedding.impl import run_embedding_pipeline
  ```

- [ ] **Step 2: Replace `ingest_file` function**

  The new `ingest_file` function orchestrates both phases. Replace the existing `ingest_file` with:

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
      """Run the two-phase ingestion pipeline for a single source file.

      Phase 1 (Document Processing) extracts and cleans the document.
      Phase 2 (Embedding Pipeline) chunks, embeds, and stores vectors.
      The CleanDocumentStore persists Phase 1 output as the boundary.

      Args:
          source_path: Source file path.
          runtime: Runtime container with shared dependencies.
          source_name: Display name for the source.
          source_uri: Stable URI for the source.
          source_key: Stable source key used for idempotency.
          source_id: Stable identity for the source.
          connector: Connector identifier.
          source_version: Source version string.
          existing_hash: Previously stored content hash (for incremental updates).
          existing_source_uri: Previously stored URI (for incremental updates).

      Returns:
          Dict with keys: ``errors`` (list), ``stored_count`` (int),
          ``metadata_summary`` (str), ``metadata_keywords`` (list),
          ``processing_log`` (list), ``source_hash`` (str), ``clean_hash`` (str).
      """
      config = runtime.config
      clean_store_dir = config.clean_store_dir
      store = CleanDocumentStore(Path(clean_store_dir)) if clean_store_dir else None

      # ── Phase 1 ──────────────────────────────────────────────────────────
      phase1 = run_document_processing(
          runtime=runtime,
          source_path=str(source_path),
          source_name=source_name,
          source_uri=source_uri,
          source_key=source_key,
          source_id=source_id,
          connector=connector,
          source_version=source_version,
      )

      if phase1.get("errors"):
          return {
              "errors": phase1["errors"],
              "stored_count": 0,
              "metadata_summary": "",
              "metadata_keywords": [],
              "processing_log": phase1.get("processing_log", []),
              "source_hash": phase1.get("source_hash", ""),
              "clean_hash": "",
          }

      # Determine final clean text
      clean_text: str = phase1.get("refactored_text") or phase1.get("cleaned_text", "")

      # ── Persist to CleanDocumentStore ─────────────────────────────────────
      if store is not None:
          meta = {
              "source_key": source_key,
              "source_name": source_name,
              "source_uri": source_uri,
              "source_id": source_id,
              "connector": connector,
              "source_version": source_version,
              "source_hash": phase1.get("source_hash", ""),
              "refactored_text": phase1.get("refactored_text"),
          }
          store.write(source_key, clean_text, meta)
          clean_hash = store.clean_hash(source_key)
      else:
          import hashlib
          clean_hash = hashlib.sha256(clean_text.encode("utf-8")).hexdigest()

      # ── Write mirror artifacts (optional) ─────────────────────────────────
      if config.persist_refactor_mirror:
          source_identity = {
              "source_path": str(source_path),
              "source_name": source_name,
              "source_uri": source_uri,
              "source_key": source_key,
              "source_id": source_id,
              "connector": connector,
              "source_version": source_version,
          }
          _write_refactor_mirror_artifacts(source_identity, phase1, config)

      # ── Phase 2 ──────────────────────────────────────────────────────────
      phase2 = run_embedding_pipeline(
          runtime=runtime,
          source_key=source_key,
          source_name=source_name,
          source_uri=source_uri,
          source_id=source_id,
          connector=connector,
          source_version=source_version,
          clean_text=clean_text,
          clean_hash=clean_hash,
          refactored_text=phase1.get("refactored_text"),
      )

      return {
          "errors": phase2.get("errors", []),
          "stored_count": phase2.get("stored_count", 0),
          "metadata_summary": phase2.get("metadata_summary", ""),
          "metadata_keywords": phase2.get("metadata_keywords", []),
          "processing_log": phase1.get("processing_log", []) + phase2.get("processing_log", []),
          "source_hash": phase1.get("source_hash", ""),
          "clean_hash": clean_hash,
      }
  ```

- [ ] **Step 3: Update `ingest_directory` to handle the new result shape**

  The new `ingest_file` return dict no longer includes `should_skip`, `chunks`, `content_hash`, or `cleaned_text`. Apply ALL of the following changes to `ingest_directory` in `pipeline/impl.py`:

  **3a — Move the skip check into `ingest_directory` (before calling `ingest_file`)**

  Before calling `ingest_file`, add an early-exit for unchanged files. Insert after `previous_hash = ...` / `previous_uri = ...`:

  ```python
  # Idempotency check: skip if source unchanged and clean store entry exists
  if update and previous_hash:
      current_hash = sha256_path(source_path)
      store_ok = (not config.clean_store_dir) or CleanDocumentStore(
          Path(config.clean_store_dir)
      ).exists(source["source_key"])
      if current_hash == previous_hash and store_ok:
          skipped += 1
          if matched_key and matched_key != source["source_key"]:
              manifest.pop(matched_key, None)
          manifest[source["source_key"]] = {
              **matched_entry,
              "source": source["source_name"],
              "source_uri": source["source_uri"],
              "source_id": source["source_id"],
              "source_key": source["source_key"],
              "connector": source["connector"],
              "source_version": source["source_version"],
              "content_hash": previous_hash,
          }
          logger.info(
              "ingestion_skipped source=%s source_key=%s reason=unchanged",
              source["source_name"],
              source["source_key"],
          )
          continue
  ```

  **3b — Remove the `result["should_skip"]` branch** (lines ~450–470 in the original)

  Delete the entire `if result["should_skip"]: ... continue` block. The skip logic is now handled in 3a above.

  **3c — Fix `result["content_hash"]` references**

  Replace:
  ```python
  "content_hash": result["content_hash"],
  ```
  with:
  ```python
  "content_hash": result.get("source_hash", ""),
  ```
  (Appears in both the skip branch — now removed — and the success manifest update. Only the success manifest update remains after 3b.)

  **3d — Fix `len(result["chunks"])` references**

  Replace:
  ```python
  len(result["chunks"]),  # in the log line
  ...
  "chunk_count": len(result["chunks"]),  # in manifest
  ```
  with:
  ```python
  result.get("stored_count", 0),  # in the log line
  ...
  "chunk_count": result.get("stored_count", 0),  # in manifest
  ```

  **3e — Fix the `export_processed` block** (lines ~502–513)

  The `export_processed` block reads `result["cleaned_text"]` and `result["chunks"]`, neither of which is returned by the new `ingest_file`. Two options — pick one:

  **Option A (recommended): read clean text from CleanDocumentStore**

  Replace:
  ```python
  if config.export_processed:
      export_stem = ...
      (PROCESSED_DIR / ...).write_text(result["cleaned_text"], ...)
      chunk_payload = [...]
      (PROCESSED_DIR / ...).write_bytes(...)
  ```
  with:
  ```python
  if config.export_processed and config.clean_store_dir:
      _store = CleanDocumentStore(Path(config.clean_store_dir))
      if _store.exists(source["source_key"]):
          _clean_text, _ = _store.read(source["source_key"])
          export_stem = f"{source_path.stem}.{hashlib.sha1(source['source_key'].encode('utf-8')).hexdigest()[:8]}"
          PROCESSED_DIR.mkdir(exist_ok=True)
          (PROCESSED_DIR / f"{export_stem}.cleaned.md").write_text(_clean_text, encoding="utf-8")
  ```
  (Chunk export is dropped — chunks are embedded in Weaviate, not written to disk.)

  **3f — Remove duplicate `_write_refactor_mirror_artifacts` call**

  The new `ingest_file` already calls `_write_refactor_mirror_artifacts` internally (when `config.persist_refactor_mirror` is True). Remove the call in `ingest_directory`:
  ```python
  # REMOVE this block:
  if config.persist_refactor_mirror:
      _write_refactor_mirror_artifacts(source, result, config)
  ```

  **3g — Add `CleanDocumentStore` import at top of `pipeline/impl.py`** (already done in Step 1, verify it's there)

  **3h — Add `sha256_path` import** (already imported via `from src.ingest.common.utils import ... sha256_path`; verify it's in the imports).

- [ ] **Step 4: Verify module imports cleanly**
  ```
  python -c "from src.ingest.pipeline.impl import ingest_directory, ingest_file; print('pipeline impl ok')"
  ```
  Expected: `pipeline impl ok`

- [ ] **Step 5: Commit**
  ```
  git add src/ingest/pipeline/impl.py
  git commit -m "feat(ingest): rewrite orchestrator for two-phase pipeline"
  ```

---

## Task 10 — Delete Old Files

- [ ] **Step 1: Delete `src/ingest/nodes/` directory**
  ```
  rm -rf src/ingest/nodes/
  ```

- [ ] **Step 2: Delete `src/ingest/pipeline/workflow.py`**
  ```
  rm src/ingest/pipeline/workflow.py
  ```

- [ ] **Step 3: Verify no broken imports remain**
  ```
  python -c "from src.ingest.pipeline.impl import ingest_directory, ingest_file; print('ok')"
  python -c "from src.ingest import ingest_directory; print('public api ok')"
  ```
  Expected: Both print `ok`.

- [ ] **Step 4: Commit**
  ```
  git add -A
  git commit -m "refactor(ingest): remove old nodes/ and pipeline/workflow.py"
  ```

---

## Task 11 — Update Public API and `__init__.py` Files

**Files:**
- Modify: `src/ingest/__init__.py`
- Modify: `src/ingest/pipeline/__init__.py`

- [ ] **Step 1: Read and verify `src/ingest/__init__.py`**

  Read the file. Ensure it imports `ingest_directory` and `ingest_file` from `src.ingest.pipeline.impl` (or `src.ingest.pipeline`). No import should reference `src.ingest.nodes` or `src.ingest.pipeline.workflow`. Fix any broken imports.

- [ ] **Step 2: Read and verify `src/ingest/pipeline/__init__.py`**

  Ensure it re-exports:
  ```python
  from src.ingest.pipeline.impl import ingest_file, ingest_directory
  ```
  Nothing else is needed.

- [ ] **Step 3: Full import smoke test**
  ```
  python -c "
  from src.ingest import ingest_directory, ingest_file
  from src.ingest.pipeline import ingest_directory, ingest_file
  from src.ingest.doc_processing import run_document_processing
  from src.ingest.embedding import run_embedding_pipeline
  from src.ingest.clean_store import CleanDocumentStore
  print('all public API imports ok')
  "
  ```
  Expected: `all public API imports ok`

- [ ] **Step 4: Commit**
  ```
  git add src/ingest/__init__.py src/ingest/pipeline/__init__.py
  git commit -m "fix(ingest): update public API imports for two-phase structure"
  ```

---

## Task 12 — Write Integration Tests

**Files:**
- Create: `tests/ingest/test_two_phase_orchestrator.py`

- [ ] **Step 1: Write tests**

  Mock `run_document_processing` and `run_embedding_pipeline` at the module level in `pipeline.impl`
  — this is the correct approach because the compiled LangGraph graph objects bind nodes at
  import time, making per-node patches ineffective.

  `tests/ingest/test_two_phase_orchestrator.py`:

  ```python
  """Integration tests for the two-phase orchestrator in pipeline/impl.py."""
  import hashlib
  import pytest
  from pathlib import Path
  from unittest.mock import MagicMock, patch


  def _make_runtime(tmp_path, store_subdir="store"):
      from src.ingest.common.types import IngestionConfig, Runtime
      config = IngestionConfig(
          enable_multimodal_processing=False,
          enable_document_refactoring=False,
          enable_cross_reference_extraction=False,
          enable_knowledge_graph_extraction=False,
          enable_knowledge_graph_storage=False,
          enable_quality_validation=False,
          enable_docling_parser=False,
          enable_llm_metadata=False,
          persist_refactor_mirror=False,
          clean_store_dir=str(tmp_path / store_subdir),
      )
      return Runtime(
          config=config,
          embedder=MagicMock(),
          weaviate_client=MagicMock(),
          kg_builder=None,
      )


  def _phase1_result(doc: Path, cleaned="clean text"):
      """Return a fake DocumentProcessingState for a doc file."""
      return {
          "source_hash": hashlib.sha256(doc.read_bytes()).hexdigest(),
          "raw_text": doc.read_text(),
          "cleaned_text": cleaned,
          "refactored_text": None,
          "errors": [],
          "processing_log": ["document_ingestion:ok", "structure_detection:ok"],
          "structure": {"has_figures": False},
          "multimodal_notes": [],
      }


  def _phase2_result():
      return {
          "stored_count": 3,
          "metadata_summary": "A test document.",
          "metadata_keywords": ["test"],
          "errors": [],
          "processing_log": ["chunking:ok", "embedding_storage:ok"],
          "chunks": [],
          "kg_triples": [],
      }


  def test_ingest_file_returns_source_hash(tmp_path):
      """ingest_file must return source_hash in result dict."""
      doc = tmp_path / "test.txt"
      doc.write_text("Hello world document content.")
      runtime = _make_runtime(tmp_path)

      with patch("src.ingest.pipeline.impl.run_document_processing",
                 return_value=_phase1_result(doc)) as mock_p1, \
           patch("src.ingest.pipeline.impl.run_embedding_pipeline",
                 return_value=_phase2_result()):
          from src.ingest.pipeline.impl import ingest_file
          result = ingest_file(
              source_path=doc, runtime=runtime,
              source_name="test.txt", source_uri=doc.as_uri(),
              source_key="local_fs:test:1", source_id="test:1",
              connector="local_fs", source_version="12345",
          )

      assert "source_hash" in result
      assert len(result["source_hash"]) == 64
      assert result["errors"] == []
      assert result["stored_count"] == 3


  def test_ingest_file_writes_clean_store(tmp_path):
      """ingest_file must write Phase 1 clean text to CleanDocumentStore."""
      doc = tmp_path / "doc.txt"
      doc.write_text("Clean document text.")
      store_dir = tmp_path / "store"
      runtime = _make_runtime(tmp_path)
      runtime.config.clean_store_dir = str(store_dir)

      with patch("src.ingest.pipeline.impl.run_document_processing",
                 return_value=_phase1_result(doc, cleaned="Clean document text.")), \
           patch("src.ingest.pipeline.impl.run_embedding_pipeline",
                 return_value=_phase2_result()):
          from src.ingest.pipeline.impl import ingest_file
          ingest_file(
              source_path=doc, runtime=runtime,
              source_name="doc.txt", source_uri=doc.as_uri(),
              source_key="local_fs:test:2", source_id="test:2",
              connector="local_fs", source_version="99999",
          )

      from src.ingest.clean_store import CleanDocumentStore
      store = CleanDocumentStore(store_dir)
      assert store.exists("local_fs:test:2")
      text, meta = store.read("local_fs:test:2")
      assert text == "Clean document text."
      assert meta["source_key"] == "local_fs:test:2"


  def test_phase1_errors_skip_phase2(tmp_path):
      """If Phase 1 returns errors, ingest_file must not call Phase 2."""
      doc = tmp_path / "doc.txt"
      doc.write_text("x")
      runtime = _make_runtime(tmp_path)

      phase1_with_error = {
          "source_hash": "", "raw_text": "", "cleaned_text": "",
          "refactored_text": None, "structure": {}, "multimodal_notes": [],
          "errors": ["read_failed:doc.txt:some error"],
          "processing_log": ["document_ingestion:failed"],
      }

      with patch("src.ingest.pipeline.impl.run_document_processing",
                 return_value=phase1_with_error) as mock_p1, \
           patch("src.ingest.pipeline.impl.run_embedding_pipeline") as mock_p2:
          from src.ingest.pipeline.impl import ingest_file
          result = ingest_file(
              source_path=doc, runtime=runtime,
              source_name="doc.txt", source_uri=doc.as_uri(),
              source_key="local_fs:test:3", source_id="test:3",
              connector="local_fs", source_version="0",
          )

      assert result["errors"] == ["read_failed:doc.txt:some error"]
      assert result["stored_count"] == 0
      mock_p2.assert_not_called()


  def test_phase2_errors_propagate(tmp_path):
      """Errors from Phase 2 must appear in ingest_file result."""
      doc = tmp_path / "doc.txt"
      doc.write_text("some content")
      runtime = _make_runtime(tmp_path)

      phase2_with_error = {**_phase2_result(), "errors": ["embed_failed:weaviate_down"]}

      with patch("src.ingest.pipeline.impl.run_document_processing",
                 return_value=_phase1_result(doc)), \
           patch("src.ingest.pipeline.impl.run_embedding_pipeline",
                 return_value=phase2_with_error):
          from src.ingest.pipeline.impl import ingest_file
          result = ingest_file(
              source_path=doc, runtime=runtime,
              source_name="doc.txt", source_uri=doc.as_uri(),
              source_key="local_fs:test:4", source_id="test:4",
              connector="local_fs", source_version="1",
          )

      assert "embed_failed:weaviate_down" in result["errors"]
  ```

- [ ] **Step 2: Run tests**
  ```
  pytest tests/ingest/test_two_phase_orchestrator.py -v
  ```
  Expected: All 4 tests PASS.

- [ ] **Step 3: Commit**
  ```
  git add tests/ingest/test_two_phase_orchestrator.py
  git commit -m "test(ingest): add two-phase orchestrator integration tests"
  ```

---

## Task 13 — Update Documentation

**Files to update** (read each before editing — update only the structural/file-path sections):

- [ ] **Step 1: Update `src/ingest/README.md`**

  Replace the directory tree and module descriptions to reflect the new structure:
  `doc_processing/`, `embedding/`, `clean_store.py` exist; `nodes/` and `pipeline/workflow.py` are gone.

- [ ] **Step 2: Create `src/ingest/doc_processing/README.md`**

  Brief description of Phase 1: what it does, which nodes it contains, what it outputs (clean text to CleanDocumentStore).

- [ ] **Step 3: Create `src/ingest/embedding/README.md`**

  Brief description of Phase 2: what it does, which nodes it contains, inputs (from CleanDocumentStore), outputs (Weaviate vectors, KG triples).

- [ ] **Step 4: Update `src/ingest/pipeline/README.md`**

  Note that `workflow.py` has been removed; the orchestrator now calls `run_document_processing` and `run_embedding_pipeline` directly.

- [ ] **Step 5: Delete `src/ingest/nodes/README.md`**

  This directory no longer exists.

- [ ] **Step 6: Update `docs/ingestion/INGESTION_PIPELINE_ENGINEERING_GUIDE.md`**

  Find the module map / directory structure section and update paths from `nodes/` to `doc_processing/nodes/` and `embedding/nodes/`. Update import examples. Do not rewrite narrative sections.

- [ ] **Step 7: Update `docs/ingestion/DOCUMENT_PROCESSING_IMPLEMENTATION.md`**

  Find the File Structure section (around line 14) and update it to match the new `src/ingest/doc_processing/` layout.

- [ ] **Step 8: Update `docs/ingestion/EMBEDDING_PIPELINE_IMPLEMENTATION.md`**

  Find the File Structure section and update it to match the new `src/ingest/embedding/` layout.

- [ ] **Step 9: Commit**
  ```
  git add src/ingest/README.md src/ingest/doc_processing/README.md src/ingest/embedding/README.md
  git add src/ingest/pipeline/README.md docs/ingestion/
  git commit -m "docs(ingest): update all docs to reflect two-phase pipeline structure"
  ```

---

## Task 14 — Final Verification

- [ ] **Step 1: Run all ingestion tests**
  ```
  pytest tests/ingest/ -v
  ```
  Expected: All tests PASS, no ImportError, no NotImplementedError.

- [ ] **Step 2: Full import sweep**
  ```
  python -c "
  import src.ingest
  import src.ingest.pipeline
  import src.ingest.doc_processing
  import src.ingest.embedding
  import src.ingest.clean_store
  from src.ingest.doc_processing.workflow import build_document_processing_graph
  from src.ingest.embedding.workflow import build_embedding_graph
  g1 = build_document_processing_graph()
  g2 = build_embedding_graph()
  print('full import sweep: ok')
  print('Phase 1 graph:', g1)
  print('Phase 2 graph:', g2)
  "
  ```
  Expected: Both graphs print without errors.

- [ ] **Step 3: Verify no references to deleted modules remain**
  ```
  grep -r "from src.ingest.nodes" src/ tests/ --include="*.py"
  grep -r "from src.ingest.pipeline.workflow" src/ tests/ --include="*.py"
  grep -r "src.ingest.nodes" src/ tests/ --include="*.py"
  ```
  Expected: No output (zero matches).

- [ ] **Step 4: Final commit**
  ```
  git add -A
  git commit -m "chore(ingest): final cleanup and verification of two-phase refactor"
  ```
