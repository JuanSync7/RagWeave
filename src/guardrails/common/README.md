<!-- @summary
Shared typed contracts for the guardrails subsystem: RailVerdict enum, RailExecution result, InputRailResult, OutputRailResult, and GuardrailsMetadata.
@end-summary -->

# guardrails/common

## Overview

This package contains the typed data contracts shared across the guardrails subsystem.

## Files

| File | Purpose | Key Exports |
| --- | --- | --- |
| `schemas.py` | Shared enum and dataclass contracts for rail verdicts and execution results | `RailVerdict`, `RailExecution`, `InputRailResult`, `OutputRailResult`, `GuardrailsMetadata` |
| `__init__.py` | Package facade | re-exports from `schemas.py` |

## Key Types

| Type | Kind | Description |
| --- | --- | --- |
| `RailVerdict` | Enum | `ALLOW`, `REJECT`, `MODIFY` — outcome of a single rail execution |
| `RailExecution` | Dataclass | Structured record of one rail run: name, verdict, latency, metadata |
| `InputRailResult` | Dataclass | Aggregated result across all input rails |
| `OutputRailResult` | Dataclass | Aggregated result across all output rails |
| `GuardrailsMetadata` | Dataclass | Full guardrails execution summary attached to RAG responses |
