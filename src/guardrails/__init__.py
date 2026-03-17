# @summary
# Public API for the guardrails subsystem (schemas and results).
# Exports: GuardrailsMetadata, InputRailResult, OutputRailResult, RailExecution, RailVerdict
# Deps: src.guardrails.common.schemas
# @end-summary
"""Public API for guardrails used by the RAG pipeline.

This package groups "guardrail" components that can validate or transform inputs
and outputs (e.g., prompt-injection detection, PII checks, toxicity screening).
The package-level exports are intentionally limited to shared schemas so callers
do not depend on implementation details of individual rails.
"""

from src.guardrails.common.schemas import (
    GuardrailsMetadata,
    InputRailResult,
    OutputRailResult,
    RailExecution,
    RailVerdict,
)

__all__ = [
    "GuardrailsMetadata",
    "InputRailResult",
    "OutputRailResult",
    "RailExecution",
    "RailVerdict",
]
