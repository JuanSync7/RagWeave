# [System/Subsystem Name] — Design Document

| Field | Value |
|-------|-------|
| **Document** | [Subsystem Name] Design Document |
| **Version** | [X.Y] |
| **Status** | Draft |
| **Spec Reference** | `[SPEC_FILENAME]` v[X.Y] ([FR range]) |
| **Companion Documents** | `[SPEC_FILENAME]`, `[SPEC_SUMMARY]`, `[IMPLEMENTATION_PLAN]` |
| **Created** | [Date] |
| **Last Updated** | [Date] |

| Version | Date | Changes |
|---------|------|---------|
| 0.1 | [Date] | Initial draft |

> **Document Intent.** This document provides a technical design with task decomposition
> and contract-grade code appendix for the [subsystem name] specified in `[SPEC_FILENAME]`.
> Every task references the requirements it satisfies. Part B contract entries are consumed
> verbatim by the companion implementation plan (`[IMPLEMENTATION_PLAN]`).

---

# Part A: Task-Oriented Overview

## Phase 1 — [Phase Name]

[1-2 sentence description of this phase's goal.]

### Task 1.1: [Descriptive Task Name]

**Description:** [What to build. 1-2 sentences. Focus on the deliverable.]

**Requirements Covered:** REQ-xxx, REQ-yyy, REQ-zzz

**Dependencies:** None

**Complexity:** S / M / L

**Subtasks:**
1. [Specific, actionable step]
2. [Specific, actionable step]
3. [Specific, actionable step]

<!-- Optional fields — include when they add value -->
<!-- **Risks:** [What could go wrong] → [Mitigation] -->
<!-- **Testing Strategy:** [Unit / Integration / E2E — brief approach] -->

---

### Task 1.2: [Descriptive Task Name]

**Description:** [What to build.]

**Requirements Covered:** REQ-xxx

**Dependencies:** [Task reference or "None"]

**Complexity:** S / M / L

**Subtasks:**
1. [Step 1]
2. [Step 2]
3. [Step 3]

---

## Phase 2 — [Phase Name]

[1-2 sentence description of this phase's goal.]

### Task 2.1: [Descriptive Task Name]

**Description:** [What to build.]

**Requirements Covered:** REQ-xxx, REQ-yyy

**Dependencies:** Task 1.1

**Complexity:** M

**Subtasks:**
1. [Step 1]
2. [Step 2]
3. [Step 3]

---

<!-- Continue with Phase 3, 4, ... N -->

---

## Task Dependency Graph

```
Phase 1 ([Phase Name])
├── Task 1.1: [Name] ──────────────────────┐
├── Task 1.2: [Name]                        │
│                                            │
Phase 2 ([Phase Name])                      │
├── Task 2.1: [Name] ◄── Task 1.1 ─────────┘  [CRITICAL]
├── Task 2.2: [Name] ◄── Task 2.1              [CRITICAL]

Critical path: Task 1.1 → 2.1 → 2.2
```

---

## Task-to-Requirement Mapping

| Task | Requirements Covered |
|------|---------------------|
| 1.1 [Task Name] | REQ-xxx, REQ-yyy |
| 1.2 [Task Name] | REQ-zzz |
| 2.1 [Task Name] | REQ-xxx, REQ-yyy |

<!-- VERIFY: Every REQ from the spec appears in at least one row above -->

---

# Part B: Code Appendix

## B.1: [State Schema — Contract]

[Description of the shared state flowing through the system.]

**Tasks:** Task 1.1, Task 1.2, Task 2.1
**Requirements:** REQ-xxx through REQ-yyy
**Type:** Contract (exact — copied to implementation plan Phase 0)

```python
from __future__ import annotations
from typing import Any, TypedDict


class ExampleState(TypedDict, total=False):
    """Shared state flowing through the pipeline."""

    # Populated by Task 1.1
    source_path: str                    # Input file path
    source_key: str                     # Deterministic ID: SHA-256(path)[:24] (REQ-101)
    source_hash: str                    # SHA-256 of file content (REQ-102)

    # Populated by Task 1.2
    processed_text: str                 # Cleaned output (REQ-201)
    confidence: float                   # 0.0-1.0 quality score (REQ-202)

    # Cross-cutting
    errors: list[dict[str, Any]]
    timings: dict[str, float]
```

**Key design decisions:**
- TypedDict with `total=False` allows nodes to populate fields incrementally
- Every field tagged with requirement ID for traceability

---

## B.2: [Exception Types — Contract]

[Exception hierarchy for the system.]

**Tasks:** Task 1.1, Task 1.2, Task 2.1
**Requirements:** REQ-xxx
**Type:** Contract (exact — copied to implementation plan Phase 0)

```python
class SystemError(Exception):
    """Base exception for all system errors."""


class ValidationError(SystemError):
    """Raised when input validation fails (REQ-105)."""


class ProcessingError(SystemError):
    """Raised when processing fails (REQ-201)."""

    def __init__(self, message: str, stage: str, cause: Exception | None = None):
        super().__init__(message)
        self.stage = stage
        self.cause = cause
```

**Key design decisions:**
- Single base exception enables catch-all at orchestration layer
- Per-stage exceptions preserve error context for debugging

---

## B.3: [Function Stubs — Contract]

[Node/component function signatures.]

**Tasks:** Task 1.1, Task 2.1
**Requirements:** REQ-xxx, REQ-yyy
**Type:** Contract (exact — copied to implementation plan Phase 0)

```python
from example_types import ExampleState


def ingestion_node(state: ExampleState) -> dict:
    """Ingest source document: detect format, extract text, compute hash.

    Args:
        state: Pipeline state containing 'config' and 'source_path'.

    Returns:
        Dict with keys: source_key, source_hash, format, raw_text.

    Raises:
        ValidationError: If source file is missing or format unknown.
    """
    raise NotImplementedError("Task B-1.1")
```

**Key design decisions:**
- Plain functions, not classes — shared resources injected via config
- Stubs point to their Phase B task for traceability

---

## B.4: [Pipeline Graph — Pattern]

[Illustrative workflow/pipeline definition.]

**Tasks:** Task 1.2
**Requirements:** REQ-xxx
**Type:** Pattern (illustrative — shows approach, not exact contract)

```python
from langgraph.graph import StateGraph, END


def build_graph(config) -> StateGraph:
    """Construct the processing DAG."""
    graph = StateGraph(ExampleState)

    graph.add_node("ingestion", ingestion_node)
    graph.add_node("processing", processing_node)

    graph.set_entry_point("ingestion")
    graph.add_edge("ingestion", "processing")
    graph.add_edge("processing", END)

    return graph
```

**Key design decisions:**
- Static topology — disabled stages are unreachable, not removed
- Single entry and exit point simplifies observability

---

<!-- Continue with B.5, B.6, ... B.N -->
<!-- Contract entries: complete and exact, every field tagged -->
<!-- Pattern entries: 50-120 lines, illustrative, self-contained -->
