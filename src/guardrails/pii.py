# @summary
# PII detection and redaction rail with Presidio NLP primary, regex fallback.
# Exports: PIIDetector, PIIDetection
# Deps: re, logging, dataclasses, presidio_analyzer (optional), presidio_anonymizer (optional)
# @end-summary
"""PII detection and redaction rail (REQ-301 through REQ-305)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("rag.guardrails.pii")

# ---------------------------------------------------------------------------
# Regex fallback patterns (used when Presidio is not installed)
# ---------------------------------------------------------------------------

_CORE_PATTERNS: Dict[str, re.Pattern] = {
    "EMAIL": re.compile(
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"
    ),
    "PHONE": re.compile(
        r"(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"
    ),
    "SSN": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
}

_EXTENDED_PATTERNS: Dict[str, re.Pattern] = {
    "CREDIT_CARD": re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b"),
    "DOB": re.compile(
        r"\b(?:0[1-9]|1[0-2])/(?:0[1-9]|[12]\d|3[01])/(?:19|20)\d{2}\b"
    ),
    "PASSPORT": re.compile(r"\b[A-Z]{1,2}\d{6,9}\b"),
}

# Presidio entity types to detect (configurable per instance)
_DEFAULT_PRESIDIO_ENTITIES = [
    "EMAIL_ADDRESS", "PHONE_NUMBER", "US_SSN", "CREDIT_CARD",
    "PERSON", "LOCATION", "DATE_TIME", "NRP", "MEDICAL_LICENSE",
    "US_DRIVER_LICENSE", "US_PASSPORT", "IBAN_CODE", "IP_ADDRESS",
]

_EXTENDED_PRESIDIO_ENTITIES = _DEFAULT_PRESIDIO_ENTITIES + [
    "US_BANK_NUMBER", "UK_NHS", "SG_NRIC_FIN", "AU_ABN",
    "AU_ACN", "AU_TFN", "AU_MEDICARE",
]


@dataclass
class PIIDetection:
    """A single PII detection."""

    pii_type: str
    start: int
    end: int
    placeholder: str


class PIIDetector:
    """Detect and redact PII using Presidio NLP with regex fallback.

    When Presidio (+ spacy en_core_web_lg) is installed, uses NLP-based
    entity recognition for robust detection. Falls back to regex patterns
    when Presidio is not available.

    Core categories (email, phone, SSN) are always enabled.
    Extended categories add credit card, DOB, passport, and more.
    """

    def __init__(
        self,
        extended: bool = False,
        score_threshold: float = 0.4,
    ) -> None:
        self._extended = extended
        self._score_threshold = score_threshold
        self._presidio_analyzer = None
        self._presidio_anonymizer = None
        self._presidio_entities: List[str] = (
            _EXTENDED_PRESIDIO_ENTITIES if extended else _DEFAULT_PRESIDIO_ENTITIES
        )
        self._use_presidio = False

        # Try to initialize Presidio
        try:
            self._init_presidio()
            self._use_presidio = True
            logger.info(
                "PII detector initialized with Presidio NLP (entities=%d, threshold=%.2f)",
                len(self._presidio_entities),
                score_threshold,
            )
        except (ImportError, RuntimeError) as e:
            logger.info("Presidio not available (%s) — using regex fallback", e)
            self._regex_patterns: Dict[str, re.Pattern] = dict(_CORE_PATTERNS)
            if extended:
                self._regex_patterns.update(_EXTENDED_PATTERNS)
            logger.info(
                "PII detector initialized with regex fallback (%d patterns)",
                len(self._regex_patterns),
            )

    def _init_presidio(self) -> None:
        """Initialize Presidio analyzer and anonymizer engines."""
        from presidio_analyzer import AnalyzerEngine
        from presidio_analyzer.nlp_engine import NlpEngineProvider
        from presidio_anonymizer import AnonymizerEngine

        import spacy
        if not spacy.util.is_package("en_core_web_lg"):
            raise RuntimeError(
                "spacy model en_core_web_lg not installed "
                "(run: python -m spacy download en_core_web_lg)"
            )

        configuration = {
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": "en", "model_name": "en_core_web_lg"}],
        }
        provider = NlpEngineProvider(nlp_configuration=configuration)
        nlp_engine = provider.create_engine()

        self._presidio_analyzer = AnalyzerEngine(
            nlp_engine=nlp_engine,
            default_score_threshold=self._score_threshold,
        )
        self._presidio_anonymizer = AnonymizerEngine()

    def detect(self, text: str) -> List[PIIDetection]:
        """Find all PII occurrences in text."""
        if self._use_presidio:
            return self._detect_presidio(text)
        return self._detect_regex(text)

    def _detect_presidio(self, text: str) -> List[PIIDetection]:
        """NLP-based detection via Presidio."""
        results = self._presidio_analyzer.analyze(
            text=text,
            language="en",
            entities=self._presidio_entities,
        )
        detections = [
            PIIDetection(
                pii_type=r.entity_type,
                start=r.start,
                end=r.end,
                placeholder=f"[{r.entity_type}_REDACTED]",
            )
            for r in results
        ]
        # Sort by position (reverse) for safe replacement
        detections.sort(key=lambda d: d.start, reverse=True)
        return detections

    def _detect_regex(self, text: str) -> List[PIIDetection]:
        """Regex fallback detection."""
        detections: List[PIIDetection] = []
        for pii_type, pattern in self._regex_patterns.items():
            for match in pattern.finditer(text):
                detections.append(
                    PIIDetection(
                        pii_type=pii_type,
                        start=match.start(),
                        end=match.end(),
                        placeholder=f"[{pii_type}_REDACTED]",
                    )
                )
        detections.sort(key=lambda d: d.start, reverse=True)
        return detections

    def redact(self, text: str) -> Tuple[str, List[PIIDetection]]:
        """Detect and redact PII, returning redacted text and detections.

        Replaces PII with type-tagged placeholders (e.g., [EMAIL_ADDRESS_REDACTED]).
        Logs detection type and count only — never logs actual PII values (REQ-305).
        """
        detections = self.detect(text)
        redacted = text
        for d in detections:
            redacted = redacted[: d.start] + d.placeholder + redacted[d.end :]

        if detections:
            counts: Dict[str, int] = {}
            for d in detections:
                counts[d.pii_type] = counts.get(d.pii_type, 0) + 1
            logger.info(
                "PII detected (%s): %s",
                "presidio" if self._use_presidio else "regex",
                ", ".join(f"{k}={v}" for k, v in sorted(counts.items())),
            )

        return redacted, detections
