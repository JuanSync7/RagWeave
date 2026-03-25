# @summary
# NeMo-discoverable Colang action wrappers. Thin wrappers around existing
# guardrail rail classes and new lightweight policy actions.
# Auto-discovered by NeMo Guardrails when placed in the config directory.
# Exports: all @action()-decorated functions
# Deps: nemoguardrails, src.guardrails.*, langdetect, re, logging
# @end-summary
"""NeMo Guardrails Colang action wrappers.

Each function decorated with @action() is auto-discovered by the NeMo runtime
when this file lives inside the guardrails config directory. Actions are thin
wrappers — they delegate to existing rail classes or implement lightweight
deterministic checks. All actions return dicts for Colang variable assignment.
"""

from __future__ import annotations

import functools
import logging
import re
from typing import Any, Dict

# Conditional import: NeMo may not be installed when tests run with RAG_NEMO_ENABLED=false
try:
    from nemoguardrails.actions import action
except ImportError:
    def action():
        """No-op decorator when nemoguardrails is not installed."""
        def decorator(fn):
            return fn
        return decorator

logger = logging.getLogger("rag.guardrails.actions")

# ── Session state (in-memory, keyed by session_id) ──
_jailbreak_session_state: Dict[str, int] = {}
_abuse_session_state: Dict[str, list] = {}

# ── Lazy-initialized rail class singletons ──
_rail_instances: Dict[str, Any] = {}


def _fail_open(default: dict):
    """Decorator: catch exceptions and return default (fail-open)."""
    def decorator(fn):
        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            try:
                return await fn(*args, **kwargs)
            except Exception as e:
                logger.warning("Action %s failed: %s — returning default", fn.__name__, e)
                return default
        return wrapper
    return decorator


# ═══════════════════════════════════════════════════════════════════════
# 2.2 — Lightweight deterministic actions
# ═══════════════════════════════════════════════════════════════════════

@action()
@_fail_open({"valid": True, "length": 0, "reason": ""})
async def check_query_length(query: str) -> dict:
    """Validate query length: min 3 chars, max 2000 chars."""
    length = len(query.strip())
    if length < 3:
        return {"valid": False, "length": length, "reason": "Query too short. Please provide at least a few words."}
    if length > 2000:
        return {"valid": False, "length": length, "reason": "Query too long. Please keep your question under 2000 characters."}
    return {"valid": True, "length": length, "reason": ""}


@action()
@_fail_open({"language": "en", "supported": True})
async def detect_language(query: str) -> dict:
    """Detect query language using langdetect. Only English is supported."""
    try:
        from langdetect import detect
        lang = detect(query)
    except Exception:
        return {"language": "unknown", "supported": True}
    return {"language": lang, "supported": lang == "en"}


@action()
@_fail_open({"clear": True, "suggestion": ""})
async def check_query_clarity(query: str) -> dict:
    """Heuristic clarity check: reject very short or all-stopword queries."""
    words = query.strip().split()
    stopwords = {"a", "an", "the", "it", "is", "was", "are", "to", "of", "in", "on", "and", "or", "for", "that", "this", "what"}
    if len(words) < 2:
        return {"clear": False, "suggestion": f"Your query '{query}' is too vague. Could you provide more detail about what you're looking for?"}
    non_stop = [w for w in words if w.lower() not in stopwords]
    if not non_stop:
        return {"clear": False, "suggestion": "Your query doesn't contain specific terms. Please include keywords related to what you want to find."}
    return {"clear": True, "suggestion": ""}


@action()
@_fail_open({"abusive": False, "reason": ""})
async def check_abuse_pattern(query: str, context: dict = None) -> dict:
    """Track query rate per session. Flag if > 20 queries in rapid succession."""
    import time
    session_id = context.get("session_id", "default") if context else "default"
    now = time.time()
    window = 60  # 1 minute window
    if session_id not in _abuse_session_state:
        _abuse_session_state[session_id] = []
    _abuse_session_state[session_id] = [t for t in _abuse_session_state[session_id] if now - t < window]
    _abuse_session_state[session_id].append(now)
    if len(_abuse_session_state[session_id]) > 20:
        return {"abusive": True, "reason": "Rate limit exceeded"}
    return {"abusive": False, "reason": ""}


@action()
@_fail_open({"has_citations": True})
async def check_citations(answer: str) -> dict:
    """Check if answer contains citation patterns like [Source: ...] or [1]."""
    patterns = [
        r'\[Source:.*?\]',
        r'\[\d+\]',
        r'\(Source:.*?\)',
        r'According to',
        r'Based on the document',
    ]
    for pattern in patterns:
        if re.search(pattern, answer, re.IGNORECASE):
            return {"has_citations": True}
    return {"has_citations": False}


@action()
@_fail_open({"answer": ""})
async def add_citation_reminder(answer: str) -> dict:
    """Append citation reminder to answer."""
    return {"answer": f"{answer}\n\nNote: Source documents are available in the response metadata."}


@action()
@_fail_open({"answer": ""})
async def prepend_hedge(answer: str) -> dict:
    """Prepend hedge language for low-confidence answers."""
    return {"answer": f"Based on limited information in the knowledge base: {answer}"}


@action()
@_fail_open({"answer": ""})
async def prepend_text(text: str, answer: str) -> dict:
    """Prepend arbitrary text (e.g., disclaimer) to answer."""
    return {"answer": f"{text}\n\n{answer}"}


@action()
@_fail_open({"answer": ""})
async def prepend_low_confidence_note(answer: str) -> dict:
    """Prepend low-confidence note."""
    return {"answer": f"Note: The following answer is based on limited matches in the knowledge base.\n\n{answer}"}


@action()
@_fail_open({"valid": True, "reason": ""})
async def check_answer_length(answer: str) -> dict:
    """Validate answer length: min 20 chars, max 5000 chars."""
    length = len(answer.strip())
    if length < 20:
        return {"valid": False, "reason": "too short"}
    if length > 5000:
        return {"valid": False, "reason": "too long"}
    return {"valid": True, "reason": ""}


@action()
@_fail_open({"answer": ""})
async def adjust_answer_length(answer: str, reason: str) -> dict:
    """Truncate overly long answers or flag terse ones."""
    if reason == "too long":
        return {"answer": answer[:5000] + "..."}
    return {"answer": answer}


@action()
@_fail_open({"sensitive": False, "disclaimer": "", "domain": ""})
async def check_sensitive_topic(query: str) -> dict:
    """Keyword + regex check for medical/legal/financial sensitive topics."""
    q_lower = query.lower()
    domains = {
        "medical": {
            "keywords": ["medication", "dosage", "symptom", "diagnosis", "prescription", "treatment", "disease", "medical advice", "drug interaction"],
            "disclaimer": "Note: This information is from the knowledge base and is not medical advice. Please consult a healthcare professional.",
        },
        "legal": {
            "keywords": ["legal advice", "lawsuit", "attorney", "court", "liability", "legal rights", "sue", "legal action"],
            "disclaimer": "Note: This is informational only and does not constitute legal advice. Please consult a qualified attorney.",
        },
        "financial": {
            "keywords": ["investment advice", "stock pick", "buy or sell", "financial advice", "portfolio", "tax advice"],
            "disclaimer": "Note: This is not financial advice. Please consult a qualified financial professional.",
        },
    }
    for domain, info in domains.items():
        for kw in info["keywords"]:
            if kw in q_lower:
                return {"sensitive": True, "disclaimer": info["disclaimer"], "domain": domain}
    return {"sensitive": False, "disclaimer": "", "domain": ""}


@action()
@_fail_open({"attempt": False, "pattern": ""})
async def check_exfiltration(query: str) -> dict:
    """Detect bulk data extraction patterns."""
    patterns = [
        r"list\s+all\s+(documents|records|entries|files|data)",
        r"dump\s+(everything|all|the\s+database)",
        r"show\s+me\s+(all|every)\s+(records?|documents?|entries?)",
        r"export\s+(the\s+)?(database|data|everything)",
        r"give\s+me\s+every(thing|\s+entry|\s+record|\s+document)",
        r"download\s+all",
        r"extract\s+all",
    ]
    for pattern in patterns:
        if re.search(pattern, query, re.IGNORECASE):
            return {"attempt": True, "pattern": pattern}
    return {"attempt": False, "pattern": ""}


@action()
@_fail_open({"violation": False})
async def check_role_boundary(query: str) -> dict:
    """Detect role-play and instruction-override patterns."""
    patterns = [
        r"you\s+are\s+now\s+a",
        r"ignore\s+(previous|all|your)\s+instructions",
        r"pretend\s+(you\s+are|to\s+be)",
        r"act\s+as\s+if",
        r"forget\s+(everything|your\s+rules|your\s+instructions)",
        r"disregard\s+(your|all)\s+(rules|guidelines|instructions)",
        r"you\s+have\s+no\s+restrictions",
        r"jailbreak",
        r"DAN\s+mode",
    ]
    for pattern in patterns:
        if re.search(pattern, query, re.IGNORECASE):
            return {"violation": True}
    return {"violation": False}


@action()
@_fail_open({"escalation_level": "none"})
async def check_jailbreak_escalation(query: str, context: dict = None) -> dict:
    """Track jailbreak attempt count per session. Thresholds: 1-2 -> warn, 3+ -> block."""
    session_id = context.get("session_id", "default") if context else "default"
    violation_patterns = [
        r"ignore\s+(previous|all|your)\s+instructions",
        r"you\s+are\s+now\s+a",
        r"pretend\s+(you\s+are|to\s+be)",
        r"jailbreak",
        r"DAN\s+mode",
    ]
    is_violation = any(re.search(p, query, re.IGNORECASE) for p in violation_patterns)
    if is_violation:
        _jailbreak_session_state[session_id] = _jailbreak_session_state.get(session_id, 0) + 1

    count = _jailbreak_session_state.get(session_id, 0)
    if count >= 3:
        return {"escalation_level": "block"}
    elif count >= 1:
        return {"escalation_level": "warn"}
    return {"escalation_level": "none"}


@action()
@_fail_open({"has_context": False, "augmented_query": ""})
async def handle_follow_up(query: str) -> dict:
    """Check for prior conversation context (stub)."""
    return {"has_context": False, "augmented_query": query}


@action()
@_fail_open({"drifted": False})
async def check_topic_drift(query: str) -> dict:
    """Topic drift detection (stub)."""
    return {"drifted": False}


@action()
@_fail_open({"confidence": "high"})
async def check_response_confidence(answer: str) -> dict:
    """Read retrieval confidence from context (stub)."""
    if not answer or answer.strip() == "":
        return {"confidence": "none"}
    return {"confidence": "high"}


@action()
@_fail_open({"has_results": True, "count": 1, "avg_confidence": 1.0})
async def check_retrieval_results(answer: str) -> dict:
    """Check retrieval results quality (stub)."""
    if not answer or answer.strip() == "":
        return {"has_results": False, "count": 0, "avg_confidence": 0.0}
    return {"has_results": True, "count": 1, "avg_confidence": 0.8}


@action()
@_fail_open({"in_scope": True})
async def check_source_scope(answer: str) -> dict:
    """Source scope check (stub)."""
    return {"in_scope": True}


@action()
@_fail_open({"ambiguous": False, "disambiguation_prompt": ""})
async def check_query_ambiguity(query: str) -> dict:
    """Query ambiguity check (stub)."""
    return {"ambiguous": False, "disambiguation_prompt": ""}


@action()
@_fail_open({"summary": "This knowledge base contains documents about various topics."})
async def get_knowledge_base_summary() -> dict:
    """Return a static summary of the knowledge base contents."""
    return {"summary": "I have access to documents in the knowledge base covering various technical topics. You can ask questions about any topic covered by the ingested documents. Try asking about specific concepts, architectures, or techniques."}


# ═══════════════════════════════════════════════════════════════════════
# 2.1 — Actions wrapping existing rail classes (stubs — Task 5 fills in)
# ═══════════════════════════════════════════════════════════════════════

@action()
@_fail_open({"verdict": "pass", "method": "none", "confidence": 0.0})
async def check_injection(query: str) -> dict:
    """Wraps InjectionDetector. Stub — filled in Task 5."""
    return {"verdict": "pass", "method": "none", "confidence": 0.0}


@action()
@_fail_open({"found": False, "entities": [], "redacted_text": ""})
async def detect_pii(text: str, direction: str = "input") -> dict:
    """Wraps PIIDetector. Stub — filled in Task 5."""
    return {"found": False, "entities": [], "redacted_text": text}


@action()
@_fail_open({"verdict": "pass", "score": 0.0})
async def check_toxicity(text: str, direction: str = "input") -> dict:
    """Wraps ToxicityFilter. Stub — filled in Task 5."""
    return {"verdict": "pass", "score": 0.0}


@action()
@_fail_open({"on_topic": True, "confidence": 1.0})
async def check_topic_safety(query: str) -> dict:
    """Wraps TopicSafetyChecker. Stub — filled in Task 5."""
    return {"on_topic": True, "confidence": 1.0}


@action()
@_fail_open({"verdict": "pass", "score": 1.0, "claim_scores": []})
async def check_faithfulness(answer: str, context_chunks: list = None) -> dict:
    """Wraps FaithfulnessChecker. Stub — filled in Task 5."""
    return {"verdict": "pass", "score": 1.0, "claim_scores": []}


@action()
@_fail_open({"action": "pass", "intent": "rag_search", "redacted_query": "", "metadata": {}})
async def run_input_rails(query: str) -> dict:
    """Wraps InputRailExecutor. Stub — filled in Task 5."""
    return {"action": "pass", "intent": "rag_search", "redacted_query": query, "metadata": {}}


@action()
@_fail_open({"action": "pass", "redacted_answer": "", "metadata": {}})
async def run_output_rails(answer: str) -> dict:
    """Wraps OutputRailExecutor. Stub — filled in Task 5."""
    return {"action": "pass", "redacted_answer": answer, "metadata": {}}


@action()
@_fail_open({"answer": "", "sources": [], "confidence": 0.0})
async def rag_retrieve_and_generate(query: str) -> dict:
    """Wraps RAG retrieval pipeline. Stub — filled in Task 6."""
    return {"answer": "", "sources": [], "confidence": 0.0}
