<!-- @summary
Shared typed dataclass contracts for observability (SpanRecord) and reliability (RetryPolicy), consumed by the observability and reliability subpackages.
@end-summary -->

# platform/schemas

## Overview

This package centralizes typed dataclass schemas shared across platform subpackages. Schemas are defined here to avoid circular imports between `observability/` and `reliability/` modules.

## Files

| File | Purpose | Key Exports |
| --- | --- | --- |
| `observability.py` | Structured tracing payload schemas | `SpanRecord`, `Attributes` |
| `reliability.py` | Retry policy and operation metadata schemas | `RetryPolicy` |
| `__init__.py` | Package facade | re-exports from both modules |

## Consumers

| Schema | Used By |
| --- | --- |
| `SpanRecord` | `platform/observability/langfuse_tracer.py`, `platform/observability/noop_tracer.py` |
| `RetryPolicy` | `platform/reliability/local_retry.py`, `platform/reliability/temporal_retry.py` |
