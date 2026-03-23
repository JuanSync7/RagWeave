<!-- @summary
How to reformat markdown Functional Requirement (FR) blocks to match the
spaced, readable style used in the ingestion specification documents
(`INGESTION_PLATFORM_SPEC.md`, `DOCUMENT_PROCESSING_SPEC.md`, `EMBEDDING_PIPELINE_SPEC.md`).
Includes the canonical rules and the formatter script usage.
@end-summary -->

## Purpose

The ingestion specification documents (`INGESTION_PLATFORM_SPEC.md`, `DOCUMENT_PROCESSING_SPEC.md`, `EMBEDDING_PIPELINE_SPEC.md`) use a blockquote-based format for each Functional Requirement (FR). The preferred style is:

- Blank `>` spacer lines between `**Description:**`, `**Rationale:**`, and `**Acceptance Criteria:**`
- Acceptance criteria rendered as a **numbered list**

This document stores the **canonical formatting method** and how to apply it consistently.

## Canonical FR block format

An FR block is a blockquote section that starts with a header line:

```md
> **FR-101** | Priority: MUST
```

and includes (at minimum) these subsections:

```md
> **Description:** ...
>
> **Rationale:** ...
>
> **Acceptance Criteria:**
> 1. Given ...
> 2. Given ...
```

## Formatting rules (the “method”)

- **Rule 1 — spacer lines**: Insert a blank blockquote line (`>`) between:
  - `**Description:**` and `**Rationale:**`
  - `**Rationale:**` and `**Acceptance Criteria:**`

  Note: some FRs include a blank `>` line after the header (e.g., FR-102), but this is optional; the formatter preserves it if present.

- **Rule 2 — Acceptance Criteria header**: `**Acceptance Criteria:**` MUST be on its own line:

```md
> **Acceptance Criteria:**
```

- **Rule 3 — Acceptance Criteria list**:
  - Format acceptance criteria as `> 1. ...`, `> 2. ...`, etc.
  - If acceptance criteria is written as a run-on sentence (e.g., `Given ..., Given ..., ...`), split into one item per “Given …” clause.
  - Renumber lists starting at 1.

- **Rule 4 — preserve non-subsection quoted content**:
  - Tables and other `>` quoted content inside an FR (rare, but possible) should remain quoted and in-place.

## Applying the formatter (recommended)

Use the repo script:

```bash
python3 scripts/format_spec_fr_blocks.py docs/ingestion/INGESTION_PLATFORM_SPEC.md --check
python3 scripts/format_spec_fr_blocks.py docs/ingestion/DOCUMENT_PROCESSING_SPEC.md --check
python3 scripts/format_spec_fr_blocks.py docs/ingestion/EMBEDDING_PIPELINE_SPEC.md --check

python3 scripts/format_spec_fr_blocks.py docs/ingestion/INGESTION_PLATFORM_SPEC.md --write
python3 scripts/format_spec_fr_blocks.py docs/ingestion/DOCUMENT_PROCESSING_SPEC.md --write
python3 scripts/format_spec_fr_blocks.py docs/ingestion/EMBEDDING_PIPELINE_SPEC.md --write
```

- `--check` exits **non-zero** if it would change the file (useful for CI).
- `--write` rewrites the file in-place.

## Safety notes

- The formatter is intentionally narrow and is designed for the `> **FR-###** | Priority: ...` style blocks.
- Always review the resulting diff before committing, especially for FRs with unusual prose or embedded tables.

