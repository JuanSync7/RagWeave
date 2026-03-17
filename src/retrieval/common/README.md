<!-- @summary
Shared retrieval-common schema contracts and deterministic helper utilities.
@end-summary -->

# retrieval/common

## Overview

This directory contains reusable retrieval primitives:

- `schemas.py`: shared typed contracts used across retrieval modules.
- `utils.py`: deterministic helper utilities (for example JSON parsing).

`parse_json_object` is sourced from `src/common/utils.py` so retrieval and ingest
share one canonical JSON extraction behavior while keeping retrieval-local imports stable.

These modules help keep `query_processor.py`, `rag_chain.py`, `reranker.py`, and
`generator.py` focused on orchestration/model logic instead of shared boilerplate.
