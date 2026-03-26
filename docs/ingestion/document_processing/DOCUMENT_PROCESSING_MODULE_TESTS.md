> **Document type:** Phase D white-box test plan
> **Companion spec:** `DOCUMENT_PROCESSING_SPEC.md`
> **Companion guide:** `DOCUMENT_PROCESSING_ENGINEERING_GUIDE.md`
> **Upstream:** DOCUMENT_PROCESSING_ENGINEERING_GUIDE.md
> **Last updated:** 2026-03-24

# Document Processing Pipeline — Phase D White-Box Test Plan

## Overview

This document specifies the Phase D white-box tests for the Document Processing Pipeline.
Phase D tests are derived from the engineering guide (not source code), targeting error behaviors,
boundary conditions, and test gaps not covered by Phase A spec tests.

**Skill:** `write-module-tests`

**Execution model:** All module test agents run in parallel, each in isolation.

**Expected outcome:** All Phase D tests FAIL on first run (they cover gaps not tested in Phase A).

---

## Module: Document Ingestion

### Agent Isolation Contract

> The Phase D test agent receives ONLY:
> 1. The module section from `DOCUMENT_PROCESSING_ENGINEERING_GUIDE.md` — Section: `src/ingest/doc_processing/nodes/document_ingestion.py`
> 2. Phase 0 contract files: `src/ingest/doc_processing/state.py`, `src/ingest/common/types.py`
> 3. FR numbers: FR-101 through FR-113
>
> Must NOT receive: Any source files (`src/ingest/doc_processing/nodes/`), any Phase A test files, the design doc.

### Input Sources

| Source | Path | Purpose |
|--------|------|---------|
| Engineering guide section | `DOCUMENT_PROCESSING_ENGINEERING_GUIDE.md` → `src/ingest/doc_processing/nodes/document_ingestion.py` | Error behavior, test guide sub-sections |
| Phase 0 contracts | `src/ingest/doc_processing/state.py` | DocumentProcessingState TypedDict |
| Phase 0 contracts | `src/ingest/common/types.py` | IngestionConfig, Runtime |
| Spec FR numbers | DOCUMENT_PROCESSING_SPEC.md | FR-101 through FR-113 |

### Output

- **Test file:** `tests/ingest/doc_processing/test_document_ingestion_coverage.py`

### Test Cases

**Error behavior tests** (derived from engineering guide Error behavior section):
- [ ] `test_document_ingestion_node_returns_error_when_source_path_missing` — FR-112: Given a non-existent `source_path`, the node returns an `errors` list containing a `read_failed:` prefixed entry and `processing_log` ending with `document_ingestion:failed`
- [ ] `test_document_ingestion_node_returns_error_when_file_unreadable` — FR-112: Given a `source_path` pointing to a file with no read permissions, the node returns an `errors` payload instead of raising an exception
- [ ] `test_document_ingestion_node_returns_error_when_read_text_with_fallbacks_raises` — FR-108: Given `read_text_with_fallbacks` raising an arbitrary exception (e.g., `OSError`), the node catches it and returns an `errors` list with the formatted error string

**Boundary condition tests** (derived from engineering guide Test guide section):
- [ ] `test_document_ingestion_node_handles_empty_file` — FR-103: Given a zero-byte source file, the node returns `raw_text` as an empty string and computes a valid SHA-256 hash (the hash of empty bytes: `e3b0c44...`)
- [ ] `test_document_ingestion_node_handles_very_large_file` — FR-103: Given a file exceeding typical memory assumptions (e.g., 50 MB text), the node still returns `raw_text` and `source_hash` without error
- [ ] `test_document_ingestion_node_handles_binary_content_with_replacement` — FR-108: Given `read_text_with_fallbacks` returning text with U+FFFD replacement characters (mocked), the node returns that text as `raw_text` without error
- [ ] `test_document_ingestion_node_handles_latin1_encoded_file` — FR-108: Given a file containing byte `\xb5` (invalid in UTF-8 alone), `read_text_with_fallbacks` decodes it via the latin-1 fallback to `µ`; the node returns the decoded text as `raw_text`
- [ ] `test_document_ingestion_node_handles_cp1252_bytes_via_latin1` — FR-108: Given a file containing bytes `\x93\x94` (CP1252 curly quotes), `read_text_with_fallbacks` decodes them via latin-1 without error (these bytes are valid latin-1 control chars); the node returns `raw_text` without raising

**Error scenario tests:**
- [ ] `test_document_ingestion_node_error_format_includes_filename_and_exception` — FR-112: The `errors` entry format is `read_failed:{filename}:{exception}`, verified by parsing the returned error string
- [ ] `test_document_ingestion_node_processing_log_records_ok_on_success` — FR-112: On successful read, `processing_log` contains an entry ending with `document_ingestion:ok`
- [ ] `test_document_ingestion_node_processing_log_records_failed_on_error` — FR-112: On read failure, `processing_log` contains an entry ending with `document_ingestion:failed`
- [ ] `test_document_ingestion_node_hash_is_deterministic` — FR-106: Given the same file content read twice, the returned `source_hash` values are identical
- [ ] `test_document_ingestion_node_hash_changes_on_content_change` — FR-106: Given two files with different content, the returned `source_hash` values differ
- [ ] `test_document_ingestion_node_hash_is_64_char_hex` — FR-106: The `source_hash` is a 64-character lowercase hexadecimal string

**Known gaps:**
- `GAP: Format-specific extraction (PDF, DOCX, PPTX, XLSX)` — FR-101, FR-103, FR-104, FR-105: The `document_ingestion_node` delegates format-specific extraction to `read_text_with_fallbacks`, which handles text-like formats. Binary format extraction (PDF, DOCX, PPTX, XLSX) is handled by the orchestrator's format routing, not this node. Testing binary extraction requires integration tests with the full orchestrator.
- `GAP: Domain vocabulary loading` — FR-109: Vocabulary loading is not performed in this node; it is an orchestrator-level concern. Cannot be tested at node isolation level.
- `GAP: Log file exclusion` — FR-111: File type filtering (`.log` exclusion) is an orchestrator-level concern, not handled by this node.

### Test File Template

```python
"""
Phase D white-box tests for document_ingestion_node.
Derived from: DOCUMENT_PROCESSING_ENGINEERING_GUIDE.md — Section: `src/ingest/doc_processing/nodes/document_ingestion.py`
FR coverage: FR-101, FR-103, FR-106, FR-108, FR-112
"""
import pytest
from src.ingest.doc_processing.state import DocumentProcessingState
from src.ingest.common.types import IngestionConfig, Runtime
```

### Verification

```bash
pytest tests/ingest/doc_processing/test_document_ingestion_coverage.py -v
```
Expected: FAIL (new coverage gaps)

---

## Module: Structure Detection

### Agent Isolation Contract

> The Phase D test agent receives ONLY:
> 1. The module section from `DOCUMENT_PROCESSING_ENGINEERING_GUIDE.md` — Section: `src/ingest/doc_processing/nodes/structure_detection.py`
> 2. Phase 0 contract files: `src/ingest/doc_processing/state.py`, `src/ingest/common/types.py`
> 3. FR numbers: FR-201 through FR-208
>
> Must NOT receive: Any source files (`src/ingest/doc_processing/nodes/`), any Phase A test files, the design doc.

### Input Sources

| Source | Path | Purpose |
|--------|------|---------|
| Engineering guide section | `DOCUMENT_PROCESSING_ENGINEERING_GUIDE.md` → `src/ingest/doc_processing/nodes/structure_detection.py` | Error behavior, test guide sub-sections |
| Phase 0 contracts | `src/ingest/doc_processing/state.py` | DocumentProcessingState TypedDict |
| Phase 0 contracts | `src/ingest/common/types.py` | IngestionConfig, Runtime |
| Spec FR numbers | DOCUMENT_PROCESSING_SPEC.md | FR-201 through FR-208 |

### Output

- **Test file:** `tests/ingest/doc_processing/test_structure_detection_coverage.py`

### Test Cases

**Error behavior tests** (derived from engineering guide Error behavior section):
- [ ] `test_structure_detection_node_returns_error_when_docling_strict_fails` — FR-208: Given `enable_docling_parser=True` and `docling_strict=True` and `parse_with_docling` raising an exception, the node returns an `errors` list with `docling_parse_failed:` prefix and sets `should_skip=True`
- [ ] `test_structure_detection_node_falls_back_to_regex_when_docling_nonstrict_fails` — FR-208: Given `enable_docling_parser=True` and `docling_strict=False` and `parse_with_docling` raising an exception, the node falls back to regex-based figure and heading extraction instead of returning an error
- [ ] `test_structure_detection_node_strict_failure_processing_log` — FR-208: On strict Docling failure, `processing_log` ends with `structure_detection:failed`

**Boundary condition tests** (derived from engineering guide Test guide section):
- [ ] `test_structure_detection_node_handles_empty_raw_text` — FR-201: Given `raw_text` as an empty string with Docling disabled, the node returns `structure` with `has_figures=False`, `figures=[]`, `heading_count=0`
- [ ] `test_structure_detection_node_handles_text_with_no_headings_or_figures` — FR-201: Given plain text with no markdown headings and no figure references, the node returns `heading_count=0` and `has_figures=False`
- [ ] `test_structure_detection_node_truncates_figures_to_32` — FR-203: Given text containing more than 32 figure references, the `structure["figures"]` list is truncated to exactly 32 entries
- [ ] `test_structure_detection_node_handles_none_raw_text` — FR-201: Given `raw_text` as `None` (if upstream error left it unset), verify graceful behavior (error or empty structure, not an unhandled exception)

**Error scenario tests:**
- [ ] `test_structure_detection_node_regex_detects_figure_variations` — FR-203: Given text with `Figure 1`, `Fig. 2`, `FIGURE 3a`, `fig. 4B`, the regex fallback detects all four figure references (case-insensitive)
- [ ] `test_structure_detection_node_regex_detects_markdown_headings` — FR-201: Given text with `# H1`, `## H2`, `### H3` headings, the regex fallback counts all three headings
- [ ] `test_structure_detection_node_regex_detects_numbered_headings` — FR-201: Given text with `1. INTRODUCTION` and `2.1 Supervised Learning`, the regex fallback detects both as headings
- [ ] `test_structure_detection_node_docling_disabled_uses_regex` — FR-208: Given `enable_docling_parser=False`, the node uses regex-based extraction and does not call `parse_with_docling`
- [ ] `test_structure_detection_node_docling_enabled_replaces_raw_text` — FR-208: Given `enable_docling_parser=True` and successful Docling parse, the returned `raw_text` is the Docling-generated markdown, not the original `raw_text`
- [ ] `test_structure_detection_node_structure_dict_schema` — FR-206: The returned `structure` dictionary contains exactly the keys: `has_figures`, `figures`, `heading_count`, `docling_enabled`, `docling_model`
- [ ] `test_structure_detection_node_processing_log_records_ok` — FR-201: On success, `processing_log` contains an entry ending with `structure_detection:ok`

**Known gaps:**
- `GAP: Extraction confidence score` — FR-206: The current implementation does not compute a numeric extraction confidence score (0.0-1.0) based on section tree depth, table completeness, text coherence, and character density. The `structure` dict captures signals (heading_count, has_figures) but does not aggregate them into a single confidence float. Test is provisional pending confidence score implementation.
- `GAP: Manual review flagging` — FR-207: Low-confidence flagging for manual review is not implemented in this node. The node does not set a `requires_manual_review` flag. Test is provisional pending flagging implementation.
- `GAP: Table extraction` — FR-202: The current regex fallback does not extract tables or table metadata. Table extraction is handled by Docling when enabled. Cannot test table extraction at node isolation level without Docling.
- `GAP: Abbreviation auto-detection` — FR-205: Abbreviation detection is not implemented in this node.

### Test File Template

```python
"""
Phase D white-box tests for structure_detection_node.
Derived from: DOCUMENT_PROCESSING_ENGINEERING_GUIDE.md — Section: `src/ingest/doc_processing/nodes/structure_detection.py`
FR coverage: FR-201, FR-203, FR-206, FR-207, FR-208
"""
import pytest
from unittest.mock import patch, MagicMock
from src.ingest.doc_processing.state import DocumentProcessingState
from src.ingest.common.types import IngestionConfig, Runtime
```

### Verification

```bash
pytest tests/ingest/doc_processing/test_structure_detection_coverage.py -v
```
Expected: FAIL (new coverage gaps)

---

## Module: Multimodal Processing

### Agent Isolation Contract

> The Phase D test agent receives ONLY:
> 1. The module section from `DOCUMENT_PROCESSING_ENGINEERING_GUIDE.md` — Section: `src/ingest/doc_processing/nodes/multimodal_processing.py`
> 2. Phase 0 contract files: `src/ingest/doc_processing/state.py`, `src/ingest/common/types.py`
> 3. FR numbers: FR-301 through FR-307
>
> Must NOT receive: Any source files (`src/ingest/doc_processing/nodes/`), any Phase A test files, the design doc.

### Input Sources

| Source | Path | Purpose |
|--------|------|---------|
| Engineering guide section | `DOCUMENT_PROCESSING_ENGINEERING_GUIDE.md` → `src/ingest/doc_processing/nodes/multimodal_processing.py` | Error behavior, test guide sub-sections |
| Phase 0 contracts | `src/ingest/doc_processing/state.py` | DocumentProcessingState TypedDict |
| Phase 0 contracts | `src/ingest/common/types.py` | IngestionConfig, Runtime |
| Spec FR numbers | DOCUMENT_PROCESSING_SPEC.md | FR-301 through FR-307 |

### Output

- **Test file:** `tests/ingest/doc_processing/test_multimodal_processing_coverage.py`

### Test Cases

**Error behavior tests** (derived from engineering guide Error behavior section):
- [ ] `test_multimodal_node_returns_error_when_vision_strict_fails` — FR-307: Given `enable_vision_processing=True` and `vision_strict=True` and `generate_vision_notes` raising an exception, the node returns an `errors` list with `vision_processing_failed:` prefix and sets `should_skip=True`
- [ ] `test_multimodal_node_swallows_exception_when_vision_nonstrict` — FR-307: Given `enable_vision_processing=True` and `vision_strict=False` and `generate_vision_notes` raising an exception, the node does not return an error payload — it continues with fallback text-only notes
- [ ] `test_multimodal_node_strict_failure_processing_log` — FR-307: On strict vision failure, `processing_log` ends with `multimodal_processing:failed`

**Boundary condition tests** (derived from engineering guide Test guide section):
- [ ] `test_multimodal_node_skipped_when_multimodal_disabled` — FR-302: Given `enable_multimodal_processing=False`, the node returns only a `processing_log` entry with `multimodal_processing:skipped` and no `multimodal_notes` key
- [ ] `test_multimodal_node_skipped_when_no_figures_detected` — FR-302: Given `enable_multimodal_processing=True` but `structure["has_figures"]=False`, the node returns only a `processing_log` entry with `multimodal_processing:skipped`
- [ ] `test_multimodal_node_handles_empty_figures_list` — FR-302: Given `structure["has_figures"]=True` but `structure["figures"]=[]`, the node produces an empty notes list (no crash)
- [ ] `test_multimodal_node_handles_missing_has_figures_key` — FR-302: Given a `structure` dict without the `has_figures` key, the node defaults to `False` via `.get("has_figures", False)` and skips processing
- [ ] `test_multimodal_node_handles_missing_figures_key` — FR-303: Given a `structure` dict with `has_figures=True` but no `figures` key, the node defaults to an empty list via `.get("figures", [])` and produces no notes

**Error scenario tests:**
- [ ] `test_multimodal_node_generates_text_only_notes_without_vision` — FR-301: Given `enable_multimodal_processing=True` and `enable_vision_processing=False` and figures detected, the node produces notes in the format `"{figure}: referenced in text"` for each figure
- [ ] `test_multimodal_node_vision_notes_replace_text_notes` — FR-301: Given successful `generate_vision_notes` returning VLM-generated notes, those notes replace the front of the text-only notes list (the overlap region)
- [ ] `test_multimodal_node_vision_notes_partial_replacement` — FR-301: Given `generate_vision_notes` returning fewer notes than figures, remaining figures retain their `referenced in text` fallback notes
- [ ] `test_multimodal_node_structure_updated_with_vision_telemetry` — FR-306: Given `enable_vision_processing=True`, the returned `structure` includes `vision_provider`, `vision_model`, and `vision_described_count` fields
- [ ] `test_multimodal_node_structure_not_updated_without_vision` — FR-306: Given `enable_vision_processing=False`, the returned `structure` does not include vision telemetry fields
- [ ] `test_multimodal_node_processing_log_records_ok` — FR-301: On success, `processing_log` contains an entry ending with `multimodal_processing:ok`

**Known gaps:**
- `GAP: VLM confidence score per description` — FR-305: The current implementation does not compute or return a per-figure confidence score alongside VLM-generated descriptions. Confidence scoring would require deeper integration with the VLM response parsing.
- `GAP: VLM description content validation` — FR-303, FR-304: The node does not validate that VLM descriptions include diagram type, labels, values, or that they exclude speculative content. This is a VLM prompt engineering concern, not testable at node level.

### Test File Template

```python
"""
Phase D white-box tests for multimodal_processing_node.
Derived from: DOCUMENT_PROCESSING_ENGINEERING_GUIDE.md — Section: `src/ingest/doc_processing/nodes/multimodal_processing.py`
FR coverage: FR-301, FR-302, FR-305, FR-306, FR-307
"""
import pytest
from unittest.mock import patch, MagicMock
from src.ingest.doc_processing.state import DocumentProcessingState
from src.ingest.common.types import IngestionConfig, Runtime
```

### Verification

```bash
pytest tests/ingest/doc_processing/test_multimodal_processing_coverage.py -v
```
Expected: FAIL (new coverage gaps)

---

## Module: Text Cleaning

### Agent Isolation Contract

> The Phase D test agent receives ONLY:
> 1. The module section from `DOCUMENT_PROCESSING_ENGINEERING_GUIDE.md` — Section: `src/ingest/doc_processing/nodes/text_cleaning.py`
> 2. Phase 0 contract files: `src/ingest/doc_processing/state.py`, `src/ingest/common/types.py`
> 3. FR numbers: FR-401 through FR-405
>
> Must NOT receive: Any source files (`src/ingest/doc_processing/nodes/`), any Phase A test files, the design doc.

### Input Sources

| Source | Path | Purpose |
|--------|------|---------|
| Engineering guide section | `DOCUMENT_PROCESSING_ENGINEERING_GUIDE.md` → `src/ingest/doc_processing/nodes/text_cleaning.py` | Error behavior, test guide sub-sections |
| Phase 0 contracts | `src/ingest/doc_processing/state.py` | DocumentProcessingState TypedDict |
| Phase 0 contracts | `src/ingest/common/types.py` | IngestionConfig, Runtime |
| Spec FR numbers | DOCUMENT_PROCESSING_SPEC.md | FR-401 through FR-405 |

### Output

- **Test file:** `tests/ingest/doc_processing/test_text_cleaning_coverage.py`

### Test Cases

**Error behavior tests** (derived from engineering guide Error behavior section):
- [ ] `test_text_cleaning_node_handles_clean_document_exception` — FR-401: Given `clean_document` raising an unexpected exception (e.g., `TypeError` on `None` input), verify whether the node propagates the exception or gracefully degrades (currently no try/except — expected to propagate)
- [ ] `test_text_cleaning_node_handles_none_raw_text` — FR-401: Given `state["raw_text"]` as `None` (upstream error), the node either raises a clear error or returns a meaningful error payload rather than an opaque traceback

**Boundary condition tests** (derived from engineering guide Test guide section):
- [ ] `test_text_cleaning_node_handles_empty_raw_text` — FR-401: Given `raw_text` as an empty string, the node returns `cleaned_text` as an empty string (or whitespace-only cleaned result) without error
- [ ] `test_text_cleaning_node_handles_empty_multimodal_notes` — FR-404: Given `multimodal_notes` as an empty list, the `cleaned_text` does not include a `## Figure Notes` section
- [ ] `test_text_cleaning_node_handles_whitespace_only_raw_text` — FR-401: Given `raw_text` as only whitespace/newlines, the `cleaned_text` is empty or whitespace-stripped
- [ ] `test_text_cleaning_node_handles_very_large_text` — FR-401: Given a `raw_text` string exceeding 1 MB, the node returns cleaned text without memory error

**Error scenario tests:**
- [ ] `test_text_cleaning_node_appends_figure_notes_section` — FR-404: Given `multimodal_notes` with two entries `["Figure 1: clock distribution", "Figure 2: power grid"]`, the `cleaned_text` ends with a `## Figure Notes` section containing `- Figure 1: clock distribution` and `- Figure 2: clock distribution` as bullet items
- [ ] `test_text_cleaning_node_figure_notes_format` — FR-404: The figure notes section uses the format `\n\n## Figure Notes\n- {note1}\n- {note2}` with proper markdown list syntax
- [ ] `test_text_cleaning_node_preserves_heading_hierarchy` — FR-401: Given `raw_text` with `# H1`, `## H2`, `### H3` markdown headings, the `cleaned_text` preserves the heading hierarchy through the `clean_document` pipeline
- [ ] `test_text_cleaning_node_removes_boilerplate` — FR-402: Given `raw_text` containing repeated boilerplate lines (e.g., `CONFIDENTIAL — Company Internal` appearing 10 times), the `cleaned_text` has the boilerplate reduced or removed
- [ ] `test_text_cleaning_node_normalizes_whitespace` — FR-401: Given `raw_text` with `5   consecutive   spaces`, the `cleaned_text` collapses them to single spaces
- [ ] `test_text_cleaning_node_processing_log_records_ok` — FR-401: On success, `processing_log` contains an entry ending with `text_cleaning:ok`

**Known gaps:**
- `GAP: Table ID marker integration` — FR-405: The current node does not integrate table markdown representations with `[TABLE tbl_xxx]` markers. The node delegates all cleaning to `clean_document()` and appends figure notes, but table integration is not handled at this level.
- `GAP: Figure ID positional insertion` — FR-404: Figure descriptions are appended at the end of the document (as a `## Figure Notes` section) rather than inserted at their original positions in the text stream. The spec requires in-line insertion at the figure's original position.
- `GAP: Configurable boilerplate patterns` — FR-402: The node delegates to `clean_document()` which calls `strip_boilerplate()`. Whether boilerplate patterns are configurable at runtime (vs. hardcoded) cannot be tested at node isolation level.

### Test File Template

```python
"""
Phase D white-box tests for text_cleaning_node.
Derived from: DOCUMENT_PROCESSING_ENGINEERING_GUIDE.md — Section: `src/ingest/doc_processing/nodes/text_cleaning.py`
FR coverage: FR-401, FR-402, FR-404
"""
import pytest
from unittest.mock import patch, MagicMock
from src.ingest.doc_processing.state import DocumentProcessingState
from src.ingest.common.types import IngestionConfig, Runtime
```

### Verification

```bash
pytest tests/ingest/doc_processing/test_text_cleaning_coverage.py -v
```
Expected: FAIL (new coverage gaps)

---

## Module: Document Refactoring

### Agent Isolation Contract

> The Phase D test agent receives ONLY:
> 1. The module section from `DOCUMENT_PROCESSING_ENGINEERING_GUIDE.md` — Section: `src/ingest/doc_processing/nodes/document_refactoring.py`
> 2. Phase 0 contract files: `src/ingest/doc_processing/state.py`, `src/ingest/common/types.py`
> 3. FR numbers: FR-501 through FR-511
>
> Must NOT receive: Any source files (`src/ingest/doc_processing/nodes/`), any Phase A test files, the design doc.

### Input Sources

| Source | Path | Purpose |
|--------|------|---------|
| Engineering guide section | `DOCUMENT_PROCESSING_ENGINEERING_GUIDE.md` → `src/ingest/doc_processing/nodes/document_refactoring.py` | Error behavior, test guide sub-sections |
| Phase 0 contracts | `src/ingest/doc_processing/state.py` | DocumentProcessingState TypedDict |
| Phase 0 contracts | `src/ingest/common/types.py` | IngestionConfig, Runtime |
| Spec FR numbers | DOCUMENT_PROCESSING_SPEC.md | FR-501 through FR-511 |

### Output

- **Test file:** `tests/ingest/doc_processing/test_document_refactoring_coverage.py`

### Test Cases

**Error behavior tests** (derived from engineering guide Error behavior section):
- [ ] `test_refactoring_node_falls_back_to_cleaned_text_when_llm_returns_empty` — FR-507: Given `_llm_json` returning `{"refactored_text": ""}` (empty string after strip), the node returns `state["cleaned_text"]` as the `refactored_text` (fail-safe fallback)
- [ ] `test_refactoring_node_falls_back_to_cleaned_text_when_llm_returns_no_key` — FR-507: Given `_llm_json` returning `{}` (no `refactored_text` key), the node falls back to `state["cleaned_text"]`
- [ ] `test_refactoring_node_falls_back_to_cleaned_text_when_llm_json_fails` — FR-507: Given `_llm_json` returning `{}` because the LLM call failed (LLM metadata disabled or exception caught internally), the node returns `state["cleaned_text"]`

**Boundary condition tests** (derived from engineering guide Test guide section):
- [ ] `test_refactoring_node_skipped_when_disabled` — FR-502: Given `enable_document_refactoring=False`, the node returns `refactored_text` equal to `state["cleaned_text"]` and `processing_log` contains `document_refactoring:skipped`
- [ ] `test_refactoring_node_no_llm_call_when_disabled` — FR-502: Given `enable_document_refactoring=False`, no LLM call is made (verify `_llm_json` is not invoked)
- [ ] `test_refactoring_node_handles_empty_cleaned_text` — FR-501: Given `cleaned_text` as an empty string and refactoring enabled, the node sends a truncated prompt and returns whatever the LLM returns (or the empty cleaned_text as fallback)
- [ ] `test_refactoring_node_truncates_prompt_to_10000_chars` — FR-501: Given `cleaned_text` longer than 10000 characters, the prompt sent to `_llm_json` contains only the first 10000 characters of the cleaned text
- [ ] `test_refactoring_node_handles_none_cleaned_text` — FR-501: Given `state["cleaned_text"]` as `None` (upstream error), verify behavior — currently would raise `TypeError` on string slicing; this is a boundary gap

**Error scenario tests:**
- [ ] `test_refactoring_node_returns_llm_refactored_text_on_success` — FR-501: Given `_llm_json` returning `{"refactored_text": "Refactored content here"}`, the node returns `refactored_text` equal to `"Refactored content here"`
- [ ] `test_refactoring_node_strips_whitespace_from_llm_response` — FR-501: Given `_llm_json` returning `{"refactored_text": "  text with spaces  "}`, the node strips leading/trailing whitespace before returning
- [ ] `test_refactoring_node_coerces_non_string_response_to_string` — FR-507: Given `_llm_json` returning `{"refactored_text": 42}` (non-string value), the node coerces it via `str()` and returns `"42"` (or falls back if result is empty after strip)
- [ ] `test_refactoring_node_processing_log_records_ok_on_success` — FR-501: On successful refactoring, `processing_log` contains an entry ending with `document_refactoring:ok`
- [ ] `test_refactoring_node_processing_log_records_skipped_when_disabled` — FR-502: When disabled, `processing_log` contains an entry ending with `document_refactoring:skipped`
- [ ] `test_refactoring_node_prompt_format` — FR-501: The prompt sent to `_llm_json` starts with `'Return {"refactored_text":"..."} for:\n'` followed by the truncated cleaned text
- [ ] `test_refactoring_node_max_tokens_is_900` — FR-501: The `_llm_json` call uses `max_tokens=900`

**Known gaps:**
- `GAP: Self-correcting loop` — FR-503: The current implementation performs a single LLM pass, not an iterative self-correcting loop with configurable maximum iterations. The spec requires `max_iterations` support with validation between iterations.
- `GAP: Fact-check validation` — FR-504: No fact-check validation is performed on the LLM response. The node accepts whatever the LLM returns (or falls back to cleaned_text on empty response).
- `GAP: Completeness check` — FR-505, FR-508: No completeness check is performed. There is no 80% completeness threshold rejection logic.
- `GAP: Refactoring constraints enforcement` — FR-506: The node does not enforce constraints against adding information, removing content, changing meaning, or altering numerical values. These are implicit in the LLM prompt but not validated.
- `GAP: Provenance mapping` — FR-510: No provenance mapping back to source-of-truth location is produced by this node.
- `GAP: Mirror artifact persistence` — FR-509: The node does not persist original and refactored mirror artifacts. Mirror persistence is handled by the orchestrator via `persist_refactor_mirror` config.
- `GAP: Citation resolution` — FR-511: Citation outputs resolving to original source references are not handled by this node.

### Test File Template

```python
"""
Phase D white-box tests for document_refactoring_node.
Derived from: DOCUMENT_PROCESSING_ENGINEERING_GUIDE.md — Section: `src/ingest/doc_processing/nodes/document_refactoring.py`
FR coverage: FR-501, FR-502, FR-507
"""
import pytest
from unittest.mock import patch, MagicMock
from src.ingest.doc_processing.state import DocumentProcessingState
from src.ingest.common.types import IngestionConfig, Runtime
```

### Verification

```bash
pytest tests/ingest/doc_processing/test_document_refactoring_coverage.py -v
```
Expected: FAIL (new coverage gaps)

---

## Module: Clean Document Store

### Agent Isolation Contract

> The Phase D test agent receives ONLY:
> 1. The module section from `DOCUMENT_PROCESSING_ENGINEERING_GUIDE.md` — Section: `src/ingest/clean_store.py`
> 2. Phase 0 contract files: `src/ingest/doc_processing/state.py`, `src/ingest/common/types.py`
> 3. FR numbers: FR-580 through FR-587
>
> Must NOT receive: Any source files (`src/ingest/doc_processing/nodes/`), any Phase A test files, the design doc.

### Input Sources

| Source | Path | Purpose |
|--------|------|---------|
| Engineering guide section | `DOCUMENT_PROCESSING_ENGINEERING_GUIDE.md` → `src/ingest/clean_store.py` | Error behavior, test guide sub-sections |
| Phase 0 contracts | `src/ingest/doc_processing/state.py` | DocumentProcessingState TypedDict |
| Phase 0 contracts | `src/ingest/common/types.py` | IngestionConfig, Runtime |
| Spec FR numbers | DOCUMENT_PROCESSING_SPEC.md | FR-580 through FR-587 |

### Output

- **Test file:** `tests/ingest/doc_processing/test_clean_store_coverage.py`

### Test Cases

**Error behavior tests** (derived from engineering guide Error behavior section):
- [ ] `test_clean_store_write_cleans_up_tmp_files_on_failure` — FR-586: Given a write that fails mid-operation (e.g., simulated disk-full via mock), the `.tmp` files are cleaned up and the exception is re-raised
- [ ] `test_clean_store_write_does_not_leave_partial_md_on_meta_failure` — FR-586: Given the metadata JSON write (`tmp_meta.write_bytes`) succeeding but the MD write failing, the tmp files are cleaned up (no partial state)
- [ ] `test_clean_store_write_does_not_leave_partial_meta_on_md_failure` — FR-586: Given the MD write succeeding but the meta tmp write failing, verify cleanup of both tmp files
- [ ] `test_clean_store_read_raises_file_not_found_for_missing_key` — FR-581: Given a `source_key` that does not exist in the store, `read()` raises `FileNotFoundError` with a descriptive message including the source key
- [ ] `test_clean_store_clean_hash_raises_file_not_found_for_missing_key` — FR-581: Given a `source_key` that does not exist, `clean_hash()` raises `FileNotFoundError`

**Boundary condition tests** (derived from engineering guide Test guide section):
- [ ] `test_clean_store_write_creates_directory_on_first_write` — FR-587: Given a `store_dir` that does not exist, the first `write()` call creates it (including parent directories)
- [ ] `test_clean_store_write_handles_empty_text` — FR-584: Given an empty string as `text`, the store writes a zero-byte `.md` file and a valid `.meta.json`
- [ ] `test_clean_store_write_handles_empty_metadata` — FR-582: Given an empty dict as `meta`, the store writes a valid `.meta.json` containing `{}`
- [ ] `test_clean_store_write_handles_unicode_text` — FR-584: Given text containing Unicode characters (e.g., `\u00b5`, emoji, CJK), the `.md` file is written as valid UTF-8
- [ ] `test_clean_store_read_returns_empty_meta_when_meta_file_missing` — FR-582: Given a `.md` file exists but the companion `.meta.json` is missing, `read()` returns the text and an empty dict for metadata
- [ ] `test_clean_store_list_keys_returns_empty_for_nonexistent_dir` — FR-587: Given a `store_dir` that does not exist, `list_keys()` returns an empty list
- [ ] `test_clean_store_safe_key_sanitizes_slashes` — FR-581: Given a `source_key` containing `/` characters, `_safe_key` replaces them with `_` for filesystem safety
- [ ] `test_clean_store_safe_key_sanitizes_colons` — FR-581: Given a `source_key` containing `:` characters (e.g., `local_fs:dev:ino`), `_safe_key` replaces them with `_`
- [ ] `test_clean_store_safe_key_sanitizes_double_dots` — FR-581: Given a `source_key` containing `..` (path traversal attempt), `_safe_key` replaces it with `__`

**Error scenario tests:**
- [ ] `test_clean_store_write_is_atomic_md_file` — FR-586: Given a successful write, the `.md` file content is complete (not a truncated tmp file) — verified by reading back and comparing
- [ ] `test_clean_store_write_is_atomic_meta_file` — FR-586: Given a successful write, the `.meta.json` content is valid JSON matching the input metadata
- [ ] `test_clean_store_write_overwrites_existing_entry` — FR-581: Given a `source_key` that already exists, a second `write()` overwrites both `.md` and `.meta.json` with new content
- [ ] `test_clean_store_exists_returns_true_for_existing_key` — FR-581: After `write()`, `exists(source_key)` returns `True`
- [ ] `test_clean_store_exists_returns_false_for_missing_key` — FR-581: Before any write for a key, `exists(source_key)` returns `False`
- [ ] `test_clean_store_clean_hash_matches_sha256_of_md_content` — FR-583: Given written content, `clean_hash()` returns the SHA-256 hex digest of the `.md` file bytes
- [ ] `test_clean_store_clean_hash_is_deterministic` — FR-583: Given the same content written twice (overwrite), `clean_hash()` returns the same hash both times
- [ ] `test_clean_store_delete_removes_both_files` — FR-586: After `delete(source_key)`, both `.md` and `.meta.json` files are removed
- [ ] `test_clean_store_delete_idempotent_for_missing_key` — FR-586: Calling `delete()` for a non-existent key does not raise an exception (uses `missing_ok=True`)
- [ ] `test_clean_store_list_keys_returns_all_stored_keys` — FR-581: After writing entries for keys `["key_a", "key_b", "key_c"]`, `list_keys()` returns all three keys
- [ ] `test_clean_store_list_keys_excludes_meta_json_files` — FR-581: `list_keys()` only returns stems from `.md` files, not `.meta.json` files
- [ ] `test_clean_store_roundtrip_write_read` — FR-581, FR-582: Given a write with specific text and metadata, `read()` returns the same text and metadata

**Known gaps:**
- `GAP: Metadata schema validation` — FR-583: The store does not validate that the metadata dict contains the required fields specified in FR-583 (source_key, source_path, source_hash, clean_hash, processing_timestamp, extraction_confidence, review_tier, section_tree_depth, table_count, has_figures, figure_count, processing_flags). Schema enforcement is the caller's responsibility.
- `GAP: Atomic ordering guarantee` — FR-586: The current implementation renames `.meta.json` first, then `.md`. If the process crashes between the two renames, a `.meta.json` could exist without its companion `.md` file. This window is extremely small but not zero.
- `GAP: Concurrent write safety` — FR-586: The store does not handle concurrent writes to the same `source_key`. Two concurrent writes could interleave tmp files. This is acceptable per assumption A-5 (sequential document processing).

### Test File Template

```python
"""
Phase D white-box tests for CleanDocumentStore.
Derived from: DOCUMENT_PROCESSING_ENGINEERING_GUIDE.md — Section: `src/ingest/common/clean_store.py`
FR coverage: FR-581, FR-582, FR-583, FR-584, FR-586, FR-587
"""
import pytest
import hashlib
from pathlib import Path
from src.ingest.common.clean_store import CleanDocumentStore
```

### Verification

```bash
pytest tests/ingest/doc_processing/test_clean_store_coverage.py -v
```
Expected: FAIL (new coverage gaps)

---

## Test Coverage Summary

| Module | FR Range | Error Tests | Boundary Tests | Error Scenario Tests | Known Gaps | Total |
|--------|----------|------------|----------------|---------------------|------------|-------|
| Document Ingestion | FR-101–113 | 3 | 5 | 6 | 3 | 14 |
| Structure Detection | FR-201–208 | 3 | 4 | 7 | 4 | 14 |
| Multimodal Processing | FR-301–307 | 3 | 5 | 6 | 2 | 14 |
| Text Cleaning | FR-401–405 | 2 | 4 | 6 | 3 | 12 |
| Document Refactoring | FR-501–511 | 3 | 5 | 7 | 7 | 15 |
| Clean Document Store | FR-580–587 | 5 | 9 | 12 | 3 | 26 |
| **Totals** | | **19** | **32** | **44** | **22** | **95** |

---

## Execution Plan

### Prerequisites
- [ ] Phase C complete: `DOCUMENT_PROCESSING_ENGINEERING_GUIDE.md` exists and is reviewed
- [ ] Phase 0 contracts available: `state.py`, `types.py`
- [ ] Phase A tests passing

### Parallel Execution
All 6 module test agents launch simultaneously. Each agent:
1. Reads ONLY its assigned engineering guide section + Phase 0 contracts + FR numbers
2. Writes test file following the template
3. Runs `pytest <test_file> -v` (expected: FAIL)
4. Returns: file path, test counts by category, known gaps, pytest output

### Phase D Gate
- [ ] All 6 test files created
- [ ] All test files reviewed
- [ ] `pytest tests/ingest/doc_processing/test_*_coverage.py -v` run
- [ ] Known gaps documented in comments
- [ ] Ready for Phase E (full suite)

---

## Companion Documents

| Document | Purpose | Relationship |
|----------|---------|-------------|
| DOCUMENT_PROCESSING_SPEC.md | Authoritative requirements specification | Source of FR numbers |
| DOCUMENT_PROCESSING_SPEC_SUMMARY.md | Executive summary | Stakeholder digest |
| DOCUMENT_PROCESSING_DESIGN.md | Task decomposition and code appendix | Original design |
| DOCUMENT_PROCESSING_IMPLEMENTATION.md | Six-phase implementation plan | Phase D is defined here |
| DOCUMENT_PROCESSING_ENGINEERING_GUIDE.md | Post-implementation reference | Source of test derivation |
| **DOCUMENT_PROCESSING_MODULE_TESTS.md** (this document) | Phase D white-box test plan | Test specifications |

**Flow:** Spec → Spec Summary → Design → Implementation → Engineering Guide → **Module Tests**
