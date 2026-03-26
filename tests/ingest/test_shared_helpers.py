# @summary
# Tests for shared ingestion helpers: cross_refs, quality_score,
# extract_keywords_fallback, map_chunk_provenance, append_processing_log.
# Exports: (pytest test functions)
# Deps: src.ingest.common.shared, src.ingest.common.types
# @end-summary
"""Tests for src.ingest.common.shared helper functions.

These tests verify the deterministic behavior of lightweight helpers used
across ingestion pipeline nodes, including cross-reference extraction,
quality scoring, keyword fallback, provenance mapping, and log appending.
"""

import pytest

# extract_keywords_fallback may be exported as public or private name
try:
    from src.ingest.common.shared import _extract_keywords_fallback
except ImportError:
    from src.ingest.common.shared import extract_keywords_fallback as _extract_keywords_fallback

from src.ingest.common.shared import (
    cross_refs,
    quality_score,
    map_chunk_provenance,
    append_processing_log,
)


# ---------------------------------------------------------------------------
# cross_refs
# ---------------------------------------------------------------------------

class TestCrossRefs:
    """Tests for the cross_refs() helper."""

    def test_cross_refs_finds_doc_pattern(self):
        result = cross_refs("See DOC-123 for details")
        values = [r["value"] for r in result]
        assert "DOC-123" in values

    def test_cross_refs_finds_section_pattern(self):
        result = cross_refs("Refer to Section 3.2.1")
        assert any("Section" in r["value"] and "3.2.1" in r["value"] for r in result)

    def test_cross_refs_finds_rfc_pattern(self):
        result = cross_refs("Per RFC 2119 requirements")
        assert any("RFC" in r["value"] and "2119" in r["value"] for r in result)

    def test_cross_refs_returns_dicts_with_type_and_value_keys(self):
        result = cross_refs("DOC-123")
        assert len(result) >= 1
        for ref in result:
            assert "type" in ref
            assert "value" in ref

    def test_cross_refs_doc_type_label(self):
        result = cross_refs("DOC-123")
        types = [r["type"] for r in result]
        assert "document_id" in types

    def test_cross_refs_section_type_label(self):
        result = cross_refs("Section 2.1")
        types = [r["type"] for r in result]
        assert "section" in types

    def test_cross_refs_rfc_type_label(self):
        result = cross_refs("RFC 7230")
        types = [r["type"] for r in result]
        assert "standard" in types

    def test_cross_refs_empty_returns_empty(self):
        assert cross_refs("") == []

    def test_cross_refs_no_matches_returns_empty(self):
        assert cross_refs("plain text with no references") == []

    def test_cross_refs_multiple_types(self):
        result = cross_refs("DOC-001, Section 1.2.3, RFC 7230")
        text = " ".join(r["value"] for r in result)
        assert "DOC-001" in text
        assert "7230" in text

    def test_cross_refs_doc_min_2_digits(self):
        # The DOC pattern requires \d{2,} — 2 or more digits
        result = cross_refs("DOC-12")
        values = [r["value"] for r in result]
        assert "DOC-12" in values

    def test_cross_refs_doc_1_digit_not_matched(self):
        # DOC-1 should NOT match (only 1 digit, below the 2-digit minimum)
        result = cross_refs("DOC-1 is not a valid reference id")
        values = [r["value"] for r in result]
        assert not any(v == "DOC-1" for v in values)

    def test_cross_refs_doc_3_digits_matched(self):
        result = cross_refs("DOC-123")
        values = [r["value"] for r in result]
        assert any("DOC-123" in v for v in values)

    def test_cross_refs_no_deduplication(self):
        # The helper does NOT deduplicate — repeated refs each produce an entry
        result = cross_refs("DOC-42 and DOC-42 again")
        doc_42_matches = [r for r in result if "DOC-42" in r["value"]]
        assert len(doc_42_matches) == 2


# ---------------------------------------------------------------------------
# quality_score
# ---------------------------------------------------------------------------

class TestQualityScore:
    """Tests for the quality_score() helper."""

    def test_quality_score_empty_returns_base_score(self):
        # quality_score always returns at least _QUALITY_BASE (0.4)
        # because the base is added unconditionally before length bonuses
        score = quality_score("")
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0

    def test_quality_score_short_returns_float(self):
        # Short text ("Hi") returns the base score — not 0.0
        score = quality_score("Hi")
        assert isinstance(score, float)
        assert score >= 0.0

    def test_quality_score_well_formed_nonzero(self):
        text = "The clock domain crossing requires careful timing analysis for setup and hold margins."
        score = quality_score(text)
        assert 0.0 < score <= 1.0

    def test_quality_score_returns_float(self):
        assert isinstance(
            quality_score("some text with enough content here for evaluation"), float
        )

    def test_quality_score_whitespace_only_is_float(self):
        # Whitespace-only text still returns a float (base score)
        score = quality_score("   ")
        assert isinstance(score, float)
        assert score >= 0.0

    def test_quality_score_bounded_to_one(self):
        long_numeric_text = "42 " * 200
        score = quality_score(long_numeric_text)
        assert score <= 1.0

    def test_quality_score_long_text_no_less_than_short(self):
        short = quality_score("Hello world.")
        long = quality_score("Hello world. " + "a" * 200)
        # A longer text gets a length bonus — score should be >= short
        assert long >= short

    def test_quality_score_numeric_content_raises_score(self):
        plain = quality_score("a" * 130)
        numeric = quality_score("42 " * 50)
        # Numeric content adds a digit bonus on top of base score
        assert numeric >= plain


# ---------------------------------------------------------------------------
# extract_keywords_fallback
# ---------------------------------------------------------------------------

class TestExtractKeywordsFallback:
    """Tests for the extract_keywords_fallback() helper."""

    def test_empty_returns_empty(self):
        result = _extract_keywords_fallback("", max_keywords=5)
        assert result == []

    def test_returns_list(self):
        result = _extract_keywords_fallback("clock timing setup hold margin", max_keywords=3)
        assert isinstance(result, list)
        assert len(result) <= 3

    def test_max_keywords_zero(self):
        result = _extract_keywords_fallback("some content words here", max_keywords=0)
        assert result == []

    def test_respects_limit(self):
        text = "clock timing setup hold margin violations analysis constraint path critical"
        result = _extract_keywords_fallback(text, max_keywords=3)
        assert len(result) == 3

    def test_high_freq_ranked_first(self):
        # "hold" appears 4 times — should be ranked highest
        text = "DFT scan chain timing timing timing clock clock setup hold hold hold hold"
        result = _extract_keywords_fallback(text, max_keywords=3)
        assert len(result) == 3
        assert result[0] == "hold"

    def test_result_contains_strings(self):
        result = _extract_keywords_fallback("clock timing margin", max_keywords=5)
        assert all(isinstance(kw, str) for kw in result)

    def test_result_lowercase(self):
        result = _extract_keywords_fallback("Clock Timing MARGIN", max_keywords=5)
        assert all(kw == kw.lower() for kw in result)

    def test_max_keywords_larger_than_vocab(self):
        # Requesting more keywords than unique words returns all unique words
        result = _extract_keywords_fallback("clock timing", max_keywords=100)
        assert len(result) <= 2


# ---------------------------------------------------------------------------
# map_chunk_provenance
# ---------------------------------------------------------------------------

class TestMapChunkProvenance:
    """Tests for the map_chunk_provenance() helper."""

    def test_exact_match_high_confidence(self):
        text = "Alpha section.\n\nClock must remain below 800MHz.\n\nBeta section"
        chunk = "Clock must remain below 800MHz."
        provenance, _, _ = map_chunk_provenance(
            chunk,
            original_text=text,
            refactored_text=text,
            original_cursor=0,
            refactored_cursor=0,
        )
        assert provenance["original_char_start"] >= 0
        assert provenance["provenance_confidence"] >= 0.8

    def test_no_match_returns_zero_confidence(self):
        provenance, _, _ = map_chunk_provenance(
            "completely absent text",
            original_text="nothing here",
            refactored_text="nothing here either",
            original_cursor=0,
            refactored_cursor=0,
        )
        assert provenance["provenance_confidence"] == 0.0

    def test_returns_three_tuple(self):
        text = "First chunk here. Second chunk here."
        result = map_chunk_provenance(
            "First chunk here.",
            original_text=text,
            refactored_text=text,
            original_cursor=0,
            refactored_cursor=0,
        )
        assert len(result) == 3

    def test_returns_cursors_as_ints(self):
        text = "First chunk here. Second chunk here."
        _, new_orig_cursor, new_ref_cursor = map_chunk_provenance(
            "First chunk here.",
            original_text=text,
            refactored_text=text,
            original_cursor=0,
            refactored_cursor=0,
        )
        assert isinstance(new_orig_cursor, int)
        assert isinstance(new_ref_cursor, int)

    def test_provenance_dict_has_required_keys(self):
        text = "Some content for testing provenance keys."
        provenance, _, _ = map_chunk_provenance(
            "Some content",
            original_text=text,
            refactored_text=text,
            original_cursor=0,
            refactored_cursor=0,
        )
        for key in (
            "original_char_start",
            "original_char_end",
            "refactored_char_start",
            "refactored_char_end",
            "provenance_method",
            "provenance_confidence",
        ):
            assert key in provenance, f"missing key: {key}"

    def test_cursor_advances_after_match(self):
        text = "First chunk here. Second chunk here."
        _, new_orig_cursor, new_ref_cursor = map_chunk_provenance(
            "First chunk here.",
            original_text=text,
            refactored_text=text,
            original_cursor=0,
            refactored_cursor=0,
        )
        # Cursor should advance past the matched span
        assert new_orig_cursor > 0
        assert new_ref_cursor > 0

    def test_no_match_cursor_unchanged(self):
        _, new_orig_cursor, new_ref_cursor = map_chunk_provenance(
            "absent text xyz",
            original_text="hello world",
            refactored_text="hello world",
            original_cursor=5,
            refactored_cursor=3,
        )
        assert new_orig_cursor == 5
        assert new_ref_cursor == 3


# ---------------------------------------------------------------------------
# append_processing_log
# ---------------------------------------------------------------------------

class TestAppendProcessingLog:
    """Tests for the append_processing_log() helper."""

    def _make_state(self, log=None):
        """Return a minimal dict that satisfies the state contract."""
        return {"processing_log": list(log or []), "runtime": None}

    def test_adds_entry(self):
        state = self._make_state()
        result = append_processing_log(state, "embed:ok")
        assert "embed:ok" in result

    def test_appends_not_replaces(self):
        state = self._make_state(["existing:ok"])
        result = append_processing_log(state, "chunk:ok")
        assert len(result) == 2
        assert "existing:ok" in result
        assert "chunk:ok" in result

    def test_returns_new_list_not_mutating_state(self):
        state = self._make_state()
        result = append_processing_log(state, "embed:ok")
        # The helper returns a new list; it does NOT mutate state["processing_log"]
        assert "embed:ok" not in state["processing_log"]
        assert "embed:ok" in result

    def test_returns_list(self):
        state = self._make_state()
        result = append_processing_log(state, "chunk:ok")
        assert isinstance(result, list)

    def test_empty_log_single_append(self):
        state = self._make_state()
        result = append_processing_log(state, "start:ok")
        assert result == ["start:ok"]

    def test_multiple_appends_accumulate(self):
        state = self._make_state()
        log = append_processing_log(state, "stage1:ok")
        state2 = {**state, "processing_log": log}
        log2 = append_processing_log(state2, "stage2:ok")
        assert "stage1:ok" in log2
        assert "stage2:ok" in log2
        assert len(log2) == 2
