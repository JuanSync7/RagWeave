<!-- @summary
NeMo Guardrails integration for input/output safety: intent detection, injection detection, PII filtering, toxicity, topic safety, and faithfulness checks. Rails run in parallel with per-rail timeouts and a consensus merge gate.
@end-summary -->

# src/guardrails

## Overview

This package implements NeMo Guardrails integration for RAG query safety. Input and output rails run in parallel with per-rail timeouts; a consensus gate (`RailMergeGate`) merges individual verdicts into a single routing decision.

**Input rails** (run on user query before retrieval): intent, injection, PII, toxicity, topic safety.
**Output rails** (run on generated answer before delivery): faithfulness, PII, toxicity.

## Files

| File | Purpose | Key Exports |
| --- | --- | --- |
| `executor.py` | Parallel rail execution orchestration with timeout + consensus merge | `InputRailExecutor`, `OutputRailExecutor`, `RailMergeGate` |
| `runtime.py` | Singleton NeMo Guardrails runtime lifecycle manager (lazy import) | `GuardrailsRuntime` |
| `intent.py` | Intent classification rail | `IntentRail` |
| `injection.py` | Prompt injection detection rail | `InjectionRail` |
| `pii.py` | PII detection rail (presidio-based, requires `[pii]` extra) | `PIIRail` |
| `gliner_pii.py` | GLiNER-based PII detection rail (requires `[gliner]` extra) | `GLiNERPIIRail` |
| `toxicity.py` | Toxicity detection rail | `ToxicityRail` |
| `topic_safety.py` | Topic safety / off-topic detection rail | `TopicSafetyRail` |
| `faithfulness.py` | Output faithfulness rail (checks answer grounding in retrieved chunks) | `FaithfulnessRail` |
| `__init__.py` | Package facade | re-exports |

## Subdirectories

| Directory | Purpose |
| --- | --- |
| `common/` | Shared typed contracts (verdict enum, execution result, metadata) |

## Configuration

Guardrails are configured via YAML files in `config/guardrails/`. Optional dependencies:
- `presidio`, `spacy` — required for `pii.py` (install with `uv pip install -e ".[pii]"`)
- `gliner` — required for `gliner_pii.py` (install with `uv pip install -e ".[gliner]"`)

## Architecture

```
User query
    ↓
InputRailExecutor (parallel, per-rail timeout)
    ├─ IntentRail
    ├─ InjectionRail
    ├─ PIIRail
    ├─ ToxicityRail
    └─ TopicSafetyRail
    ↓
RailMergeGate → routing decision (allow / reject / modify)
    ↓
[retrieval + generation]
    ↓
OutputRailExecutor (parallel)
    ├─ FaithfulnessRail
    ├─ PIIRail
    └─ ToxicityRail
    ↓
RailMergeGate → final response
```
