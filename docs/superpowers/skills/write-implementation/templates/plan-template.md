# [Feature Name] — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** [One sentence describing what this builds]

**Architecture:** [2-3 sentences about approach]

**Tech Stack:** [Key technologies/libraries]

---

## File Structure

### Contracts (Phase 0)

```
src/[package]/
├── types.py              # CREATE — State TypedDicts, config dataclasses
├── schemas.py            # CREATE — Domain schemas (if needed)
├── exceptions.py         # CREATE — Custom exception types
├── shared.py             # CREATE — Pure utility functions (fully implemented)
└── nodes/
    ├── node_a.py         # CREATE — Stub with signature + NotImplementedError
    └── node_b.py         # CREATE — Stub with signature + NotImplementedError
```

### Source (Phase B — stubs become implementations)

```
src/[package]/
├── nodes/
│   ├── node_a.py         # MODIFY — Replace stub with implementation
│   └── node_b.py         # MODIFY — Replace stub with implementation
└── workflow.py            # MODIFY — Replace stub with implementation
```

### Tests (Phase A)

```
tests/[package]/
├── test_node_a.py        # CREATE
├── test_node_b.py        # CREATE
└── test_workflow.py       # CREATE
```

---

## Phase 0 — Contract Definitions

**Purpose:** Define all TypedDicts, dataclasses, function signatures, and exception types BEFORE any tests or implementation. Extracted from the design document's contract entries.

**Review gate:** Phase 0 output must be human-reviewed before Phase A begins.

---

### Task 0.1 — [State and Config Contracts]

**Files:**
- Create: `src/[package]/types.py`

- [ ] Step 1: Define [State TypedDict] with ALL fields:

```python
# Copied from design doc B.x contract entry
```

---

### Task 0.2 — [Exception Types]

**Files:**
- Create: `src/[package]/exceptions.py`

- [ ] Step 1: Define all exception classes:

```python
# Copied from design doc B.x contract entry
```

---

### Task 0.3 — [Function Stubs]

**Files:**
- Create: `src/[package]/nodes/node_a.py` (stub)
- Create: `src/[package]/nodes/node_b.py` (stub)

- [ ] Step 1: Create stubs with signatures + NotImplementedError:

```python
# Copied from design doc B.x contract entry
```

---

## Phase A — Tests (Isolated from Implementation)

**Agent isolation contract:** The test agent receives ONLY:
1. The spec requirements (FR numbers + acceptance criteria)
2. The contract files from Phase 0 (TypedDicts, signatures, exceptions)
3. The task description from the design document

**Must NOT receive:** Any implementation code, any pattern entries from the design doc's code appendix, any source files beyond Phase 0 stubs.

---

### Task A-X.Y — Tests for [Component Name]

**Agent input (ONLY these):**
- FR-xxx (brief description), FR-yyy (brief description) from spec
- `[TypedDict]` from `src/[package]/types.py` (Phase 0)
- `[function_name]` signature from `src/[package]/nodes/[file].py` (Phase 0 stub)
- Task X.Y description from design document

**Must NOT receive:** Any implementation code, any pattern entries from design doc Part B, any other test files.

**Files:**
- Create: `tests/[package]/test_[component].py`

- [ ] Step 1: Write tests covering:
  - [Test case derived from FR-xxx]
  - [Test case derived from FR-yyy]
  - [Edge case from spec acceptance criteria]

- [ ] Step 2: Run tests to confirm stubs produce expected failures:

```bash
pytest tests/[package]/test_[component].py -v
```

Expected: FAIL (NotImplementedError from stubs)

---

## Phase B — Implementation (Against Tests)

**Agent input per task:**
1. Task description from the design document
2. The specific test file from Phase A
3. Contract files from Phase 0
4. Spec requirements (FR numbers)

**Must NOT receive:** Test files for OTHER tasks.

---

### Task B-X.Y — Implement [Component Name]

**Agent input:**
- Task X.Y description + subtasks from design document
- `tests/[package]/test_[component].py` (from Phase A)
- `src/[package]/types.py` (Phase 0 contracts)
- FR-xxx, FR-yyy from spec

**Must NOT receive:** Other Phase A test files.

**Files:**
- Modify: `src/[package]/nodes/[file].py` (replace stub)

- [ ] Step 1: Implement [first subtask from design doc] (FR-xxx)
- [ ] Step 2: Implement [second subtask] (FR-yyy)
- [ ] Step 3: Run tests:

```bash
pytest tests/[package]/test_[component].py -v
```

Expected: ALL PASS

- [ ] Step 4: Commit

---

## Task Dependency Graph

```
Phase 0 (Contracts — all parallel, human-reviewed before Phase A)
├── Task 0.1: [Contracts]
├── Task 0.2: [Exceptions]
└── Task 0.3: [Stubs]
    │
    ▼ [REVIEW GATE]
    │
Phase A (Tests — all parallel)
├── Task A-X.Y: Tests for [Component]
└── Task A-X.Z: Tests for [Component]
    │
    ▼
Phase B (Implementation — follows dependency graph)
├── Task B-X.Y: [Component] ◄── dependencies     [CRITICAL]
└── Task B-X.Z: [Component] ◄── dependencies
```

---

## Task-to-Requirement Mapping

| Task | Phase 0 Contracts | Phase A Test File | Phase B Source | Requirements |
|------|-------------------|-------------------|----------------|-------------|
| X.Y | types.py, exceptions.py | test_[component].py | nodes/[file].py | FR-xxx, FR-yyy |

---

## Full Test Suite Verification

After all Phase B tasks complete:

```bash
pytest tests/[package]/ -v --tb=short
```

Expected: ALL PASS
