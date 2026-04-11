# @summary
# Package init for src.guardrails.shared — backend-agnostic ML rail modules.
# @end-summary

# --- Auto-generated re-exports (fix_encapsulation.py) ---
from src.guardrails.shared.faithfulness import (
    FaithfulnessChecker,
    FaithfulnessResult,
    _FALLBACK_MESSAGE,
)
from src.guardrails.shared.injection import InjectionDetector
from src.guardrails.shared.intent import (
    INTENT_RESPONSES,
    IntentClassifier,
)
from src.guardrails.shared.pii import PIIDetector
from src.guardrails.shared.topic_safety import (
    REJECTION_MESSAGE,
    TopicSafetyChecker,
)
from src.guardrails.shared.toxicity import ToxicityFilter
