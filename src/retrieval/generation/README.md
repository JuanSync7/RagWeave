<!-- @summary
Generation sub-pipeline: document formatting, LLM answer synthesis, output sanitization, and 3-signal composite confidence scoring with post-generation routing. Owns FormattedContext, VersionConflict, ConfidenceBreakdown, and PostGuardrailAction contracts.
@end-summary -->

# retrieval/generation

## Overview

This sub-package takes ranked results from the query stage and produces a final answer, including formatting, generation, sanitization, and confidence-based routing.

## Files

| File | Purpose | Key Exports |
| --- | --- | --- |
| `schemas.py` | Generation sub-package contracts | `FormattedContext`, `VersionConflict` |

## Subdirectories

### `nodes/`

| File | Purpose | Key Exports |
| --- | --- | --- |
| `document_formatter.py` | Transforms `RankedResult` list into structured context string; detects version conflicts | `format_context` |
| `generator.py` | LLM answer synthesis via LiteLLM Router; extracts self-reported confidence | `OllamaGenerator` |
| `output_sanitizer.py` | Removes system prompt leakage, boundary markers, and template artifacts | `sanitize_answer` |

### `confidence/`

| File | Purpose | Key Exports |
| --- | --- | --- |
| `schemas.py` | Confidence scoring contracts | `ConfidenceBreakdown`, `PostGuardrailAction` |
| `scoring.py` | 3-signal composite confidence (retrieval + LLM + citation) | `compute_composite_confidence` |
| `routing.py` | Routes answer based on composite score: RETURN, RE_RETRIEVE, FLAG, BLOCK | `route_by_confidence` |

## Schema Ownership

- `FormattedContext` — output of `format_context`: context string, chunk count, detected conflicts.
- `VersionConflict` — a document stem with multiple retrieved versions.
- `ConfidenceBreakdown` — 3-signal composite: retrieval score, LLM self-report, citation coverage.
- `PostGuardrailAction` — post-generation routing decision.

## Flow

```
List[RankedResult]
  → document_formatter   (metadata headers, version conflict detection)
  → OllamaGenerator      (LLM synthesis, extracts CONFIDENCE: high|medium|low)
  → output_sanitizer     (remove prompt leakage artifacts)
  → confidence scoring   (retrieval × 0.5 + llm × 0.25 + citation × 0.25)
  → route_by_confidence  (RETURN | RE_RETRIEVE | FLAG | BLOCK)
```
