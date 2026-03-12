<!-- @summary
Prompt templates used by retrieval query-processing stages, including legacy
split prompts and the combined reformulate+evaluate prompt.
@end-summary -->

# prompts

## Overview

This directory contains prompt files consumed by `src/retrieval/query_processor.py`.
The runtime can use a combined reformulate+evaluate call while retaining split
prompt templates for compatibility and experimentation.

## Files

| File | Purpose |
| --- | --- |
| `query_reformulate_and_evaluate.md` | Primary combined prompt for reformulation + evaluation JSON output. |
| `query_reformulator.md` | Legacy reformulation-only prompt template. |
| `query_evaluator.md` | Legacy evaluation-only prompt template. |

## Internal Dependencies

- Loaded by `src/retrieval/query_processor.py` through prompt loader helpers.

## Subdirectories

None
