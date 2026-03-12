<!-- @summary
Centralized configuration package for ingestion, retrieval, server runtime,
security, limits, observability, and operational behavior.
@end-summary -->

# config

## Overview

This directory houses environment-driven configuration for the entire RAG system.
`settings.py` is the canonical source of runtime defaults and env var bindings.

## Files

| File | Purpose | Key Exports |
| --- | --- | --- |
| `settings.py` | Global settings for models, ingestion/retrieval behavior, API/worker runtime, auth, limits, caching, and observability | Path constants, model/runtime toggles, timeout/concurrency settings, auth/limit/cache providers, ingestion feature flags |

## Internal Dependencies

- `settings.py` depends primarily on `os` and `pathlib`.
- It is imported across ingestion, retrieval, server, and platform modules.

## Subdirectories

None
