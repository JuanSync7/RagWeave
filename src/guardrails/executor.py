# @summary
# Input and output rail executors with parallel execution, consensus gate,
# and topic safety. Runs intent, injection, PII, toxicity, and topic safety
# rails in parallel for input; faithfulness, PII, toxicity in parallel for output.
# Exports: InputRailExecutor, OutputRailExecutor, RailMergeGate
# Deps: src.guardrails.*, concurrent.futures, logging, time
# @end-summary
"""Rail execution orchestration (REQ-702, REQ-703, REQ-707)."""

from __future__ import annotations

import logging
import time
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError
from typing import Any, Dict, List, Optional

from src.common.utils import make_query_hash
from src.guardrails.common.schemas import (
    GuardrailsMetadata,
    InputRailResult,
    OutputRailResult,
    RailExecution,
    RailVerdict,
)
from src.guardrails.faithfulness import FaithfulnessChecker
from src.guardrails.injection import InjectionDetector
from src.guardrails.intent import IntentClassifier
from src.guardrails.pii import PIIDetector
from src.guardrails.topic_safety import TopicSafetyChecker
from src.guardrails.toxicity import ToxicityFilter
from src.platform.observability.providers import get_tracer
from src.platform.metrics import PIPELINE_STAGE_MS
from src.platform.timing import measure_ms

logger = logging.getLogger("rag.guardrails.executor")

# Prometheus metrics for guardrails (REQ-905)
try:
    from prometheus_client import Counter, Histogram

    GUARDRAIL_EXECUTIONS = Counter(
        "rag_guardrail_executions_total",
        "Total guardrail executions",
        ["rail_name", "verdict"],
    )
    GUARDRAIL_EXECUTION_MS = Histogram(
        "rag_guardrail_execution_ms",
        "Guardrail execution time in milliseconds",
        ["rail_name"],
        buckets=[10, 50, 100, 250, 500, 1000, 2000, 5000, 10000],
    )
    GUARDRAIL_REJECTIONS = Counter(
        "rag_guardrail_rejections_total",
        "Total guardrail rejections",
        ["rail_name", "reason"],
    )
except ImportError:
    GUARDRAIL_EXECUTIONS = None
    GUARDRAIL_EXECUTION_MS = None
    GUARDRAIL_REJECTIONS = None


def _record_metric(rail_name: str, verdict: RailVerdict, ms: float) -> None:
    """Record Prometheus metrics for a rail execution."""
    if GUARDRAIL_EXECUTIONS is not None:
        GUARDRAIL_EXECUTIONS.labels(rail_name=rail_name, verdict=verdict.value).inc()
    if GUARDRAIL_EXECUTION_MS is not None:
        GUARDRAIL_EXECUTION_MS.labels(rail_name=rail_name).observe(ms)
    if verdict == RailVerdict.REJECT and GUARDRAIL_REJECTIONS is not None:
        GUARDRAIL_REJECTIONS.labels(rail_name=rail_name, reason=verdict.value).inc()
    # Also record on the unified pipeline stage histogram
    if PIPELINE_STAGE_MS is not None:
        PIPELINE_STAGE_MS.labels(stage=f"guardrail_{rail_name}", bucket="guardrails").observe(ms)


class InputRailExecutor:
    """Run all enabled input rails in parallel (REQ-702).

    Each rail has a per-rail timeout. Timed-out or failed rails
    return a PASS verdict with a warning logged (REQ-902).
    """

    def __init__(
        self,
        intent_classifier: Optional[IntentClassifier] = None,
        injection_detector: Optional[InjectionDetector] = None,
        pii_detector: Optional[PIIDetector] = None,
        toxicity_filter: Optional[ToxicityFilter] = None,
        topic_safety_checker: Optional[TopicSafetyChecker] = None,
        timeout_seconds: int = 10,
    ) -> None:
        self._intent = intent_classifier
        self._injection = injection_detector
        self._pii = pii_detector
        self._toxicity = toxicity_filter
        self._topic_safety = topic_safety_checker
        self._timeout = timeout_seconds
        self._tracer = get_tracer()

    def execute(
        self,
        query: str,
        tenant_id: str = "",
        parent_span: Any = None,
    ) -> InputRailResult:
        """Run all enabled rails in parallel, return combined result."""
        result = InputRailResult()
        executions: List[RailExecution] = []
        query_hash = make_query_hash(query)

        with ThreadPoolExecutor(
            max_workers=5, thread_name_prefix="input_rail"
        ) as pool:
            futures: Dict[str, Future] = {}

            if self._intent:
                futures["intent"] = pool.submit(self._intent.classify, query)
            if self._injection:
                futures["injection"] = pool.submit(
                    self._injection.check, query, tenant_id
                )
            if self._pii:
                futures["pii"] = pool.submit(self._pii.redact, query)
            if self._toxicity:
                futures["toxicity"] = pool.submit(self._toxicity.check, query)
            if self._topic_safety:
                futures["topic_safety"] = pool.submit(self._topic_safety.check, query)

            for name, fut in futures.items():
                t0 = time.perf_counter()
                span = self._tracer.start_span(
                    f"guardrails.input.{name}",
                    {"query_hash": query_hash},
                    parent=parent_span,
                )
                try:
                    rail_result = fut.result(timeout=self._timeout)
                    ms = measure_ms(t0)

                    if name == "intent":
                        result.intent = rail_result.intent
                        result.intent_confidence = rail_result.confidence
                        verdict = RailVerdict.PASS
                        executions.append(
                            RailExecution(
                                "intent",
                                verdict,
                                ms,
                                {"intent": rail_result.intent, "confidence": rail_result.confidence},
                            )
                        )
                    elif name == "injection":
                        result.injection_verdict = rail_result.verdict
                        executions.append(
                            RailExecution(
                                "injection",
                                rail_result.verdict,
                                ms,
                                {"source": rail_result.detection_source or "none"},
                            )
                        )
                    elif name == "pii":
                        redacted_text, detections = rail_result
                        if detections:
                            result.redacted_query = redacted_text
                            result.pii_redactions = [
                                {"type": d.pii_type} for d in detections
                            ]
                        verdict = (
                            RailVerdict.MODIFY if detections else RailVerdict.PASS
                        )
                        executions.append(RailExecution("pii", verdict, ms))
                    elif name == "toxicity":
                        result.toxicity_verdict = rail_result.verdict
                        executions.append(
                            RailExecution(
                                "toxicity",
                                rail_result.verdict,
                                ms,
                                {"score": rail_result.score},
                            )
                        )
                    elif name == "topic_safety":
                        verdict = rail_result.verdict
                        if not rail_result.on_topic:
                            result.topic_off_topic = True
                        executions.append(
                            RailExecution(
                                "topic_safety",
                                verdict,
                                ms,
                                {"on_topic": rail_result.on_topic},
                            )
                        )

                    _record_metric(name, executions[-1].verdict, ms)
                    span.set_attribute("verdict", executions[-1].verdict.value)
                    span.end(status="ok")

                    logger.info(
                        "Rail %s | verdict=%s | ms=%.0f | hash=%s | tenant=%s",
                        name,
                        executions[-1].verdict.value,
                        ms,
                        query_hash,
                        tenant_id,
                    )

                except TimeoutError:
                    ms = measure_ms(t0)
                    logger.warning(
                        "Rail '%s' timed out after %.0fms — defaulting to pass | hash=%s",
                        name,
                        ms,
                        query_hash,
                    )
                    executions.append(RailExecution(name, RailVerdict.PASS, ms))
                    _record_metric(name, RailVerdict.PASS, ms)
                    span.end(status="error")

                except Exception as e:
                    ms = measure_ms(t0)
                    logger.warning(
                        "Rail '%s' failed: %s — defaulting to pass | hash=%s",
                        name,
                        e,
                        query_hash,
                    )
                    executions.append(RailExecution(name, RailVerdict.PASS, ms))
                    _record_metric(name, RailVerdict.PASS, ms)
                    span.end(status="error", error=e)

        result.rail_executions = executions
        return result


class OutputRailExecutor:
    """Run output rails in parallel with consensus gate (REQ-703).

    All enabled output rails (faithfulness, PII, toxicity) execute
    concurrently. A consensus gate then evaluates results:
    - Faithfulness reject → discard other results, return fallback
    - Otherwise → apply PII redaction, then toxicity filter
    """

    def __init__(
        self,
        faithfulness_checker: Optional[FaithfulnessChecker] = None,
        pii_detector: Optional[PIIDetector] = None,
        toxicity_filter: Optional[ToxicityFilter] = None,
        timeout_seconds: int = 10,
    ) -> None:
        self._faithfulness = faithfulness_checker
        self._pii = pii_detector
        self._toxicity = toxicity_filter
        self._timeout = timeout_seconds
        self._tracer = get_tracer()

    def execute(
        self,
        answer: str,
        context_chunks: List[str],
        parent_span: Any = None,
    ) -> OutputRailResult:
        """Run all enabled output rails in parallel, then apply consensus gate."""
        result = OutputRailResult(final_answer=answer)
        executions: List[RailExecution] = []

        with ThreadPoolExecutor(
            max_workers=3, thread_name_prefix="output_rail"
        ) as pool:
            futures: Dict[str, Future] = {}

            if self._faithfulness:
                futures["faithfulness"] = pool.submit(
                    self._faithfulness.check, answer, context_chunks
                )
            if self._pii:
                futures["pii"] = pool.submit(self._pii.redact, answer)
            if self._toxicity:
                futures["toxicity"] = pool.submit(
                    self._toxicity.filter_output, answer
                )

            # Collect results from all rails
            rail_results: Dict[str, Any] = {}
            for name, fut in futures.items():
                t0 = time.perf_counter()
                span = self._tracer.start_span(
                    f"guardrails.output.{name}", parent=parent_span
                )
                try:
                    rail_results[name] = fut.result(timeout=self._timeout)
                    ms = measure_ms(t0)

                    if name == "faithfulness":
                        faith_result = rail_results[name]
                        result.faithfulness_score = faith_result.overall_score
                        result.faithfulness_verdict = faith_result.verdict
                        result.faithfulness_warning = faith_result.warning
                        result.claim_scores = [
                            {"claim": c.claim, "score": c.score, "supported": c.supported}
                            for c in faith_result.claim_scores
                        ]
                        executions.append(
                            RailExecution(
                                "faithfulness",
                                faith_result.verdict,
                                ms,
                                {"score": faith_result.overall_score},
                            )
                        )
                        _record_metric("faithfulness", faith_result.verdict, ms)
                        span.set_attribute("score", faith_result.overall_score)

                    elif name == "pii":
                        redacted_text, detections = rail_results[name]
                        verdict = RailVerdict.MODIFY if detections else RailVerdict.PASS
                        executions.append(RailExecution("output_pii", verdict, ms))
                        _record_metric("output_pii", verdict, ms)

                    elif name == "toxicity":
                        filtered_text = rail_results[name]
                        verdict = RailVerdict.MODIFY if filtered_text != answer else RailVerdict.PASS
                        executions.append(RailExecution("output_toxicity", verdict, ms))
                        _record_metric("output_toxicity", verdict, ms)

                    span.set_attribute("verdict", executions[-1].verdict.value)
                    span.end(status="ok")

                    logger.info(
                        "Rail output.%s | verdict=%s | ms=%.0f",
                        name,
                        executions[-1].verdict.value,
                        ms,
                    )

                except TimeoutError:
                    ms = measure_ms(t0)
                    logger.warning(
                        "Output rail '%s' timed out after %.0fms — defaulting to pass",
                        name,
                        ms,
                    )
                    executions.append(RailExecution(f"output_{name}", RailVerdict.PASS, ms))
                    _record_metric(f"output_{name}", RailVerdict.PASS, ms)
                    span.end(status="error")

                except Exception as e:
                    ms = measure_ms(t0)
                    logger.warning(
                        "Output rail '%s' failed: %s — defaulting to pass",
                        name,
                        e,
                    )
                    executions.append(RailExecution(f"output_{name}", RailVerdict.PASS, ms))
                    _record_metric(f"output_{name}", RailVerdict.PASS, ms)
                    span.end(status="error", error=e)

        # ── Consensus Gate ──
        # Priority 1: faithfulness reject → discard everything, return fallback
        faith = rail_results.get("faithfulness")
        if faith is not None and faith.verdict == RailVerdict.REJECT:
            logger.info("Output consensus: REJECT (faithfulness score=%.2f)", faith.overall_score)
            result.final_answer = faith.fallback_message
            result.rail_executions = executions
            return result

        # Priority 2: apply PII redaction to the answer
        pii = rail_results.get("pii")
        if pii is not None:
            redacted_text, detections = pii
            if detections:
                result.final_answer = redacted_text
                result.pii_redactions = [
                    {"type": d.pii_type} for d in detections
                ]

        # Priority 3: apply toxicity filter to the (possibly PII-redacted) answer
        toxicity_text = rail_results.get("toxicity")
        if toxicity_text is not None and toxicity_text != answer:
            # Re-run toxicity on the potentially PII-redacted text
            # since the parallel run used the original answer
            if result.final_answer != answer:
                filtered = self._toxicity.filter_output(result.final_answer or "")
            else:
                filtered = toxicity_text
            if filtered != result.final_answer:
                result.final_answer = filtered
                result.toxicity_verdict = RailVerdict.MODIFY

        result.rail_executions = executions
        return result


class RailMergeGate:
    """Merge query processing result with input rail result (REQ-707).

    Priority order:
    1. Injection reject overrides all
    2. Toxicity reject overrides intent routing
    3. Topic safety (off-topic) rejects with canned response
    4. Intent classification determines flow
    5. PII redaction modifies query but does not change flow
    """

    def merge(
        self,
        query_result: Any,
        rail_result: InputRailResult,
    ) -> Dict[str, Any]:
        """Return merged routing decision.

        Returns a dict with:
        - action: "reject" | "canned" | "search"
        - message: rejection/canned response text (if not search)
        - query: effective query to use for search (may be PII-redacted)
        - guardrails_meta: metadata for the response
        """
        from src.guardrails.intent import INTENT_RESPONSES

        # Priority 1: injection reject
        if rail_result.injection_verdict == RailVerdict.REJECT:
            logger.info("Merge gate: REJECT (injection)")
            return {
                "action": "reject",
                "message": "Your query could not be processed. Please rephrase your question.",
            }

        # Priority 2: toxicity reject
        if rail_result.toxicity_verdict == RailVerdict.REJECT:
            logger.info("Merge gate: REJECT (toxicity)")
            return {
                "action": "reject",
                "message": "Your query contains content that violates our usage policy. Please rephrase.",
            }

        # Priority 3: topic safety (LLM-based off-topic detection)
        if rail_result.topic_off_topic:
            from src.guardrails.topic_safety import REJECTION_MESSAGE as TOPIC_MSG
            logger.info("Merge gate: CANNED (topic_safety: off-topic)")
            return {
                "action": "canned",
                "message": TOPIC_MSG,
            }

        # Priority 4: intent routing
        intent = rail_result.intent
        if intent != "rag_search" and intent in INTENT_RESPONSES:
            logger.info("Merge gate: CANNED (%s)", intent)
            return {
                "action": "canned",
                "message": INTENT_RESPONSES[intent],
            }

        # Priority 4: PII redaction (non-blocking)
        effective_query = (
            rail_result.redacted_query or query_result.processed_query
        )

        logger.info("Merge gate: SEARCH (intent=%s)", intent)
        return {
            "action": "search",
            "query": effective_query,
        }
