# @summary
# Supplementary PII detection using GLiNER zero-shot NER for entity-based PII.
# Exports: GLiNERPIIDetector
# Deps: gliner (optional), config.settings, src.guardrails.shared.pii.PIIDetection
# @end-summary
"""GLiNER-based supplementary PII detection.

Uses GLiNER's zero-shot NER capabilities to detect entity-based PII
(PERSON, ORGANIZATION, LOCATION, ADDRESS) that pattern-based detectors
like Presidio regex may miss — especially for non-Western names or
domain-specific entities.

This module is a supplementary layer, not a replacement:
- Layer 1 (primary): Presidio NLP / regex — pattern-based PII
- Layer 2 (this module): GLiNER zero-shot NER — entity-based PII

The GLiNER dependency is optional. If not installed, this module raises
ImportError at instantiation time, and the caller falls back gracefully.
"""

from __future__ import annotations

import logging

from src.guardrails.shared.pii import PIIDetection

logger = logging.getLogger("rag.guardrails.gliner_pii")

# PII-specific entity labels for GLiNER zero-shot NER.
# These differ from the KG entity labels used in ingestion
# (which are "technology", "algorithm", etc.).
_PII_LABELS = ["person", "organization", "location", "address"]

# Map GLiNER labels to standardized PII type names
_LABEL_TO_PII_TYPE: dict[str, str] = {
    "person": "PERSON",
    "organization": "ORGANIZATION",
    "location": "LOCATION",
    "address": "ADDRESS",
}


class GLiNERPIIDetector:
    """Supplementary PII detector using GLiNER zero-shot NER.

    Detects entity-based PII that regex/Presidio may miss. Uses the
    same GLiNER model configured for the project (GLINER_MODEL_PATH)
    but with PII-specific entity labels.

    Raises:
        ImportError: If the gliner package is not installed.
        RuntimeError: If the GLiNER model cannot be loaded.
    """

    def __init__(
        self,
        model_path: str | None = None,
        threshold: float = 0.5,
    ) -> None:
        """Initialize the GLiNER PII detector.

        Args:
            model_path: Path to the GLiNER model. Defaults to the
                project-configured GLINER_MODEL_PATH.
            threshold: Minimum confidence score for entity predictions.
                Lower values detect more entities but increase false
                positives. Default 0.5.
        """
        from gliner import GLiNER
        from config.settings import GLINER_MODEL_PATH

        model_path = model_path or GLINER_MODEL_PATH
        self._model = GLiNER.from_pretrained(model_path, local_files_only=True)
        self._threshold = threshold
        self._labels = list(_PII_LABELS)
        logger.info(
            "GLiNER PII detector initialized (model=%s, threshold=%.2f, labels=%s)",
            model_path,
            threshold,
            self._labels,
        )

    def detect(self, text: str) -> list[PIIDetection]:
        """Detect entity-based PII using GLiNER zero-shot NER.

        Args:
            text: Input text to scan.

        Returns:
            List of PIIDetection objects sorted by position (reverse)
            for safe in-place replacement.
        """
        if not text or not text.strip():
            return []

        try:
            predictions = self._model.predict_entities(
                text,
                self._labels,
                threshold=self._threshold,
            )
        except Exception as e:
            logger.warning("GLiNER prediction failed: %s", e)
            return []

        detections = []
        for pred in predictions:
            pii_type = _LABEL_TO_PII_TYPE.get(
                pred.get("label", "").lower(), "ENTITY"
            )
            start = pred.get("start", 0)
            end = pred.get("end", 0)
            if start >= end:
                continue
            if not (0 <= start < end <= len(text)):
                continue  # skip out-of-bounds detections

            detections.append(
                PIIDetection(
                    pii_type=pii_type,
                    start=start,
                    end=end,
                    placeholder=f"[{pii_type}_REDACTED]",
                )
            )

        # Sort by position (reverse) for safe replacement
        detections.sort(key=lambda d: d.start, reverse=True)

        if detections:
            type_counts: dict[str, int] = {}
            for d in detections:
                type_counts[d.pii_type] = type_counts.get(d.pii_type, 0) + 1
            logger.info(
                "GLiNER PII detected: %s",
                ", ".join(f"{k}={v}" for k, v in sorted(type_counts.items())),
            )

        return detections


def merge_detections(
    primary: list[PIIDetection],
    supplementary: list[PIIDetection],
) -> list[PIIDetection]:
    """Merge PII detections from primary and supplementary layers.

    When detections from both layers overlap (share any character
    positions), the detection from the primary layer is kept. This
    prevents double-redaction of the same text span.

    Non-overlapping supplementary detections are added to the result.

    Args:
        primary: Detections from the primary layer (Presidio/regex).
        supplementary: Detections from the supplementary layer (GLiNER).

    Returns:
        Merged list sorted by position (reverse) for safe replacement.
    """
    if not supplementary:
        return primary
    if not primary:
        supplementary_copy = list(supplementary)
        supplementary_copy.sort(key=lambda d: d.start, reverse=True)
        return supplementary_copy

    # Build interval set from primary detections
    primary_intervals = [(d.start, d.end) for d in primary]

    merged = list(primary)
    for det in supplementary:
        # Check if this detection overlaps with any primary detection
        overlaps = any(
            det.start < p_end and det.end > p_start
            for p_start, p_end in primary_intervals
        )
        if not overlaps:
            merged.append(det)

    # Re-sort by position (reverse) for safe replacement
    merged.sort(key=lambda d: d.start, reverse=True)
    return merged
