# @summary
# LangGraph-based query processing with confidence routing, backed by LiteLLM Router.
# Exports: process_query, QueryResult, QueryAction, warm_up_ollama
# Deps: langgraph, config.settings, src.platform.llm, src.retrieval.query.schemas, src.retrieval.common.utils
# @end-summary
"""
LangGraph-based query processing pipeline.

Implements a creation/verification loop:
  - Sanitize: clean input, check guardrails (injection, length)
  - Reformulate (creation agent): LLM reformulates query for searchability
  - Evaluate (verification agent): LLM scores query confidence with reasoning
  - Route: confident → SEARCH, exhausted → ASK_USER, else → loop

Falls back to word-count heuristic if Ollama is unavailable.
"""

import orjson
import logging
import os
import re
from collections import defaultdict
from typing import Dict, List, Optional

from langgraph.graph import END, StateGraph

from config.settings import (
    DOMAIN_DESCRIPTION,
    KG_PATH,
    MAX_SANITIZATION_ITERATIONS,
    PROMPTS_DIR,
    QUERY_CONFIDENCE_THRESHOLD,
    QUERY_LOG_DIR,
    QUERY_MAX_LENGTH,
    QUERY_PROCESSING_TEMPERATURE,
)
from src.platform.llm import get_llm_provider
from src.platform.observability.providers import get_tracer
from src.retrieval.query.schemas import QueryAction, QueryResult, QueryState
from src.retrieval.common.utils import parse_json_object

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

logger = logging.getLogger("rag.query_processor")

if not logger.handlers:
    logger.setLevel(logging.INFO)
    os.makedirs(QUERY_LOG_DIR, exist_ok=True)
    _file_handler = logging.FileHandler(QUERY_LOG_DIR / "query_processor.log")
    _file_handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")
    )
    logger.addHandler(_file_handler)

_tracer = get_tracer()


# ---------------------------------------------------------------------------
# Public API — backward-compatible with rag_chain.py
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Prompt loading (cached at module level)
# ---------------------------------------------------------------------------


def _load_prompt(filename: str) -> str:
    path = PROMPTS_DIR / filename
    if not path.exists():
        raise FileNotFoundError(f"Prompt file not found: {path}")
    return path.read_text(encoding="utf-8")


_REFORMULATOR_PROMPT: Optional[str] = None
_EVALUATOR_PROMPT: Optional[str] = None
_COMBINED_PROMPT: Optional[str] = None


def _get_reformulator_prompt() -> str:
    global _REFORMULATOR_PROMPT
    if _REFORMULATOR_PROMPT is None:
        _REFORMULATOR_PROMPT = _load_prompt("query_reformulator.md")
    return _REFORMULATOR_PROMPT


def _get_evaluator_prompt() -> str:
    global _EVALUATOR_PROMPT
    if _EVALUATOR_PROMPT is None:
        _EVALUATOR_PROMPT = _load_prompt("query_evaluator.md")
    return _EVALUATOR_PROMPT


def _get_combined_prompt() -> str:
    global _COMBINED_PROMPT
    if _COMBINED_PROMPT is None:
        _COMBINED_PROMPT = _load_prompt("query_reformulate_and_evaluate.md")
    return _COMBINED_PROMPT


# ---------------------------------------------------------------------------
# Knowledge graph vocabulary (loaded once, used for reformulation context)
# ---------------------------------------------------------------------------

_KG_TERMS: Optional[List[str]] = None
_KG_WORD_INDEX: Optional[Dict[str, List[str]]] = None


def _get_kg_terms() -> tuple:
    """Load entity names from the knowledge graph JSON (if available).

    Returns (terms_list, word_index) where word_index maps lowercase words
    to the terms containing them. Both are built once and cached.
    """
    global _KG_TERMS, _KG_WORD_INDEX
    if _KG_TERMS is not None:
        return _KG_TERMS, _KG_WORD_INDEX

    _KG_TERMS = []
    _KG_WORD_INDEX = defaultdict(list)

    if not KG_PATH.exists():
        return _KG_TERMS, _KG_WORD_INDEX

    try:
        with open(KG_PATH, "rb") as f:
            kg_data = orjson.loads(f.read())
        nodes = kg_data.get("nodes", [])
        # Sort by mention count, filter out noisy short/long entries
        valid = [
            n for n in nodes
            if 2 <= len(n.get("id", "")) <= 60 and n.get("mention_count", 0) >= 1
        ]
        valid.sort(key=lambda n: n.get("mention_count", 0), reverse=True)
        _KG_TERMS = [n["id"] for n in valid]

        # Build inverted index: word -> [term1, term2, ...]
        for term in _KG_TERMS:
            for word in term.lower().split():
                if len(word) >= 3:
                    _KG_WORD_INDEX[word].append(term)

        logger.info(
            "Loaded %d KG terms (%d index keys) for reformulation context",
            len(_KG_TERMS), len(_KG_WORD_INDEX),
        )
    except (orjson.JSONDecodeError, KeyError) as e:
        logger.warning("Failed to load KG terms: %s", e)

    return _KG_TERMS, _KG_WORD_INDEX


# ---------------------------------------------------------------------------
# Guardrails — prompt injection detection (fallback when NeMo is disabled)
# ---------------------------------------------------------------------------

_INJECTION_PATTERNS: Optional[List[re.Pattern]] = None


def _load_injection_patterns() -> List[re.Pattern]:
    """Load injection patterns from config/injection_patterns.yaml.

    Patterns are loaded once and cached. Falls back to a minimal
    hardcoded set if the YAML file is missing or unreadable.
    """
    global _INJECTION_PATTERNS
    if _INJECTION_PATTERNS is not None:
        return _INJECTION_PATTERNS

    try:
        import yaml
        patterns_path = PROMPTS_DIR.parent / "config" / "injection_patterns.yaml"
        if patterns_path.exists():
            with open(patterns_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            raw_patterns = data.get("patterns", [])
            _INJECTION_PATTERNS = [re.compile(p, re.I) for p in raw_patterns]
            logger.info("Loaded %d injection patterns from %s", len(_INJECTION_PATTERNS), patterns_path)
            return _INJECTION_PATTERNS
    except Exception as e:
        logger.warning("Failed to load injection patterns file: %s — using fallback", e)

    # Minimal fallback if file is missing
    _INJECTION_PATTERNS = [
        re.compile(r"ignore\s+(all\s+)?(previous|above|prior)\s+(instructions|prompts)", re.I),
        re.compile(r"you\s+are\s+now\s+", re.I),
        re.compile(r"forget\s+(everything|your\s+instructions)", re.I),
    ]
    return _INJECTION_PATTERNS


def _detect_injection(query: str) -> bool:
    """Check for prompt injection patterns (fallback for when NeMo is disabled).

    When NeMo Guardrails is enabled, its 4-layer injection detection
    (regex + perplexity + model + LLM) handles this. This function
    serves as a lightweight fallback for environments without NeMo.
    """
    patterns = _load_injection_patterns()
    return any(p.search(query) for p in patterns)


# ---------------------------------------------------------------------------
# LLM helper (backed by LiteLLM Router via LLMProvider)
# ---------------------------------------------------------------------------


def _call_llm(prompt: str, system: str = "") -> Optional[str]:
    """Call LLM via LLMProvider. Returns response text or None on failure."""
    span = _tracer.start_span(
        "query_processor.call_llm",
        {"model_alias": "query"},
    )
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    try:
        provider = get_llm_provider()
        response = provider.generate(
            messages,
            model_alias="query",
            temperature=QUERY_PROCESSING_TEMPERATURE,
            max_tokens=256,
        )
        span.end(status="ok")
        return response.content or None
    except Exception as e:
        logger.warning("LLM call failed: %s", e)
        span.end(status="error", error=e)
        return None


# Backward-compatible alias
_call_ollama = _call_llm


def _check_llm_available() -> bool:
    """Check if the LLM provider is reachable."""
    span = _tracer.start_span("query_processor.llm_healthcheck")
    try:
        provider = get_llm_provider()
        result = provider.is_available(model_alias="query")
        span.end(status="ok")
        return result
    except Exception:
        span.end(status="error")
        return False


# Backward-compatible alias
_check_ollama_available = _check_llm_available


# ---------------------------------------------------------------------------
# Fallback heuristic (preserves old behavior when Ollama is unavailable)
# ---------------------------------------------------------------------------


def _heuristic_confidence(query: str) -> float:
    """Word-count-based confidence heuristic."""
    word_count = len(query.split())
    if word_count == 0:
        return 0.0
    elif word_count <= 2:
        return 0.4
    elif word_count <= 5:
        return 0.7
    else:
        return 0.85


# ---------------------------------------------------------------------------
# Graph nodes
# ---------------------------------------------------------------------------


def sanitize_node(state: QueryState) -> dict:
    """Clean input and check guardrails."""
    query = state["current_query"].strip()
    query = " ".join(query.split())  # collapse whitespace

    # Empty check
    if not query:
        logger.info("Query rejected: empty")
        return {
            "current_query": query,
            "confidence": 0.0,
            "action": "ask_user",
            "clarification_message": (
                "Your query appears to be empty. Please enter a question."
            ),
        }

    # Length check
    if len(query) > QUERY_MAX_LENGTH:
        query = query[:QUERY_MAX_LENGTH]
        logger.info("Query truncated to %d characters", QUERY_MAX_LENGTH)

    # Injection detection
    if _detect_injection(query):
        logger.warning("Potential prompt injection detected: %s", query[:80])
        return {
            "current_query": query,
            "confidence": 0.0,
            "action": "ask_user",
            "clarification_message": (
                "Your query could not be processed. Please rephrase."
            ),
        }

    if state.get("fast_path", False):
        return {
            "current_query": query,
            "confidence": 1.0,
            "reasoning": "fast_path enabled",
        }

    return {"current_query": query}


def _match_kg_terms(query: str, max_terms: int = 20) -> str:
    """Find KG terms relevant to the query using inverted index lookup.

    Returns a formatted string for injection into the reformulator prompt.
    Uses pre-built word→terms index for O(query_words) lookup instead of
    scanning all terms. Scales to 10k+ KG nodes with <1ms lookup.
    """
    kg_terms, word_index = _get_kg_terms()
    if not kg_terms:
        return ""

    query_words = {w.lower() for w in query.split() if len(w) >= 3}
    if not query_words:
        return ""

    # Collect candidate terms from index, preserving mention-count order
    seen = set()
    matched = []
    for word in query_words:
        for term in word_index.get(word, []):
            if term not in seen:
                seen.add(term)
                matched.append(term)
                if len(matched) >= max_terms:
                    break
        if len(matched) >= max_terms:
            break

    if not matched:
        # No direct matches — fall back to top terms by mention count
        matched = kg_terms[:max_terms]

    return "Known terms in the knowledge base: " + ", ".join(matched)


def reformulate_and_evaluate_node(state: QueryState) -> dict:
    """Combined LLM reformulation + evaluation in a single Ollama call.

    Halves the number of LLM round-trips compared to separate nodes.
    """
    new_iteration = state["iteration"] + 1

    if not state["ollama_available"]:
        conf = _heuristic_confidence(state["current_query"])
        logger.info(
            "Iteration %d: heuristic confidence=%.2f (Ollama unavailable)",
            new_iteration,
            conf,
        )
        return {
            "current_query": state["current_query"],
            "iteration": new_iteration,
            "confidence": conf,
            "reasoning": "fallback heuristic (Ollama unavailable)",
        }

    previous_feedback = ""
    if state["reasoning"]:
        previous_feedback = (
            f"Previous evaluator feedback: {state['reasoning']}"
        )

    kg_terms = _match_kg_terms(state["original_query"])

    prompt = _get_combined_prompt().format(
        original_query=state["original_query"],
        iteration=new_iteration,
        max_iterations=state["max_iterations"],
        previous_feedback=previous_feedback,
        kg_terms=kg_terms,
        domain_description=DOMAIN_DESCRIPTION,
    )

    result = _call_llm(prompt)

    if result:
        try:
            parsed = parse_json_object(result)
            reformulated = str(parsed.get("reformulated_query", "")).strip()
            confidence = float(parsed.get("confidence", 0.0))
            confidence = max(0.0, min(1.0, confidence))
            reasoning = str(parsed.get("reasoning", ""))

            if reformulated:
                logger.info(
                    "Iteration %d: '%s' -> '%s' (confidence=%.2f, reasoning='%s')",
                    new_iteration,
                    state["current_query"],
                    reformulated,
                    confidence,
                    reasoning,
                )
            else:
                reformulated = state["current_query"]
                logger.info(
                    "Iteration %d: reformulation empty, keeping current query (confidence=%.2f, reasoning='%s')",
                    new_iteration,
                    confidence,
                    reasoning,
                )
            return {
                "current_query": reformulated,
                "iteration": new_iteration,
                "confidence": confidence,
                "reasoning": reasoning,
            }
        except (orjson.JSONDecodeError, ValueError, TypeError) as e:
            logger.warning(
                "Failed to parse combined JSON: %s. Raw: %s", e, result[:200]
            )
            return {
                "current_query": state["current_query"],
                "iteration": new_iteration,
                "confidence": 0.5,
                "reasoning": "parse failed",
            }

    logger.warning(
        "Iteration %d: combined reformulate+evaluate returned no content, keeping query",
        new_iteration,
    )
    return {
        "current_query": state["current_query"],
        "iteration": new_iteration,
        "confidence": 0.5,
        "reasoning": "empty response",
    }


def exhaust_node(state: QueryState) -> dict:
    """Generate clarification message when iterations are exhausted."""
    query = state["current_query"]
    confidence = state["confidence"]

    if len(query.split()) <= 2:
        msg = (
            f'Your query "{query}" seems quite short. '
            "Could you provide more context or detail about what you're looking for?"
        )
    else:
        msg = (
            f'I\'m not fully confident I understand your query "{query}" '
            f"(confidence: {confidence:.0%}). Could you rephrase or add more detail?"
        )

    logger.info("Iterations exhausted. Action: ask_user. Confidence: %.2f", confidence)
    return {"action": "ask_user", "clarification_message": msg}


# ---------------------------------------------------------------------------
# Routers (conditional edges)
# ---------------------------------------------------------------------------


def _route_after_sanitize(state: QueryState) -> str:
    if state.get("action") == "ask_user":
        return "end"
    return "reformulate_and_evaluate"


def _route_after_combined(state: QueryState) -> str:
    if state["confidence"] >= state["confidence_threshold"]:
        return "end"
    if state["iteration"] >= state["max_iterations"]:
        return "exhaust"
    return "reformulate_and_evaluate"


# ---------------------------------------------------------------------------
# Graph assembly (compiled once at module level)
# ---------------------------------------------------------------------------


def _build_graph():
    graph = StateGraph(QueryState)

    graph.add_node("sanitize", sanitize_node)
    graph.add_node("reformulate_and_evaluate", reformulate_and_evaluate_node)
    graph.add_node("exhaust", exhaust_node)

    graph.set_entry_point("sanitize")

    graph.add_conditional_edges(
        "sanitize",
        _route_after_sanitize,
        {"end": END, "reformulate_and_evaluate": "reformulate_and_evaluate"},
    )
    graph.add_conditional_edges(
        "reformulate_and_evaluate",
        _route_after_combined,
        {"end": END, "reformulate_and_evaluate": "reformulate_and_evaluate", "exhaust": "exhaust"},
    )
    graph.add_edge("exhaust", END)

    return graph.compile()


_COMPILED_GRAPH = _build_graph()


# ---------------------------------------------------------------------------
# Public entry point — backward-compatible with rag_chain.py
# ---------------------------------------------------------------------------


def warm_up_ollama() -> None:
    """Send a tiny request to Ollama to pre-load the query processing model.

    Call this at worker startup so the first real query doesn't pay the
    cold-start cost (~5-10s model load).
    """
    if not _check_llm_available():
        logger.warning("LLM not reachable — skipping warm-up")
        return

    logger.info("Warming up query LLM model...")
    import time
    t0 = time.perf_counter()
    _call_llm("ping", system="Reply with 'ok' only.")
    elapsed = (time.perf_counter() - t0) * 1000
    logger.info("LLM warm-up done in %.0fms", elapsed)


def process_query(
    raw_query: str,
    confidence_threshold: float = QUERY_CONFIDENCE_THRESHOLD,
    max_iterations: int = MAX_SANITIZATION_ITERATIONS,
    fast_path: bool = False,
) -> QueryResult:
    """Query processing loop with confidence-based routing.

    Sanitizes the query, then iteratively reformulates and evaluates it
    using LLM agents via LangGraph. If confidence meets the threshold,
    routes to SEARCH. Otherwise, routes to ASK_USER for clarification.

    Falls back to word-count heuristic if Ollama is unavailable.

    Args:
        raw_query: The raw user query.
        confidence_threshold: Minimum confidence to proceed with search.
        max_iterations: Max reformulation attempts before asking user.

    Returns:
        QueryResult with the processed query and recommended action.
    """
    root_span = _tracer.start_span("query_processor.process_query", {"raw_query_len": len(raw_query)})
    span_status = "ok"
    span_error = None
    try:
        ollama_available = _check_llm_available()
        if not ollama_available:
            logger.warning("LLM unavailable; falling back to heuristic mode")

        initial_state: QueryState = {
            "original_query": raw_query,
            "current_query": raw_query,
            "confidence": 0.0,
            "reasoning": "",
            "iteration": 0,
            "max_iterations": max_iterations,
            "confidence_threshold": confidence_threshold,
            "action": "",
            "clarification_message": "",
            "ollama_available": ollama_available,
            "fast_path": fast_path,
        }

        logger.info("Processing query: '%s'", raw_query[:100])
        final_state = _COMPILED_GRAPH.invoke(initial_state)

        action = (
            QueryAction.ASK_USER
            if final_state["action"] == "ask_user"
            else QueryAction.SEARCH
        )
        clarification = final_state["clarification_message"] or None

        logger.info(
            "Query processing complete: action=%s confidence=%.2f iterations=%d query='%s'",
            action.value,
            final_state["confidence"],
            final_state["iteration"],
            final_state["current_query"][:100],
        )

        result = QueryResult(
            processed_query=final_state["current_query"],
            confidence=final_state["confidence"],
            action=action,
            clarification_message=clarification,
            iterations=final_state["iteration"],
        )
        root_span.set_attribute("action", result.action.value)
        root_span.set_attribute("confidence", result.confidence)
        return result
    except Exception as exc:
        span_status = "error"
        span_error = exc
        raise
    finally:
        root_span.end(status=span_status, error=span_error)


__all__ = [
    "QueryAction",
    "QueryResult",
    "QueryState",
    "process_query",
    "warm_up_ollama",
]
