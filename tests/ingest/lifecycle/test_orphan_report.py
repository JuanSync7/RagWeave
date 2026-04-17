"""Tests for orphan_report: formatting roundtrip (text and JSON).

Verifies that both formatters produce the expected output structure and that
format_json is machine-parseable.
"""

from __future__ import annotations

import json

import pytest

from src.ingest.lifecycle.orphan_report import format_json, format_text
from src.ingest.lifecycle.schemas import GCReport, OrphanReport, StoreCleanupStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _report(
    weaviate=None, minio=None, neo4j=None, manifest_only=None
) -> OrphanReport:
    return OrphanReport(
        weaviate_orphans=weaviate or [],
        minio_orphans=minio or [],
        neo4j_orphans=neo4j or [],
        manifest_only=manifest_only or [],
    )


def _gc(
    soft_deleted: int = 0,
    hard_deleted: int = 0,
    retention_purged: int = 0,
    dry_run: bool = False,
    per_document: dict | None = None,
) -> GCReport:
    return GCReport(
        soft_deleted=soft_deleted,
        hard_deleted=hard_deleted,
        retention_purged=retention_purged,
        dry_run=dry_run,
        per_document=per_document or {},
    )


# ---------------------------------------------------------------------------
# Tests: format_text
# ---------------------------------------------------------------------------


class TestFormatText:
    def test_returns_string(self):
        """format_text must return a plain string."""
        result = format_text(_report())
        assert isinstance(result, str)

    def test_contains_header(self):
        """Output must contain the report header."""
        result = format_text(_report())
        assert "Orphan Report" in result

    def test_orphan_counts_in_text(self):
        """Orphan counts from each store must appear in the output."""
        report = _report(weaviate=["key_a", "key_b"], minio=["key_c"])
        text = format_text(report)

        # Count lines listing individual keys
        assert "key_a" in text
        assert "key_b" in text
        assert "key_c" in text

    def test_empty_report_no_key_lines(self):
        """An empty report must not produce any '  -' lines."""
        text = format_text(_report())
        bullet_lines = [l for l in text.splitlines() if l.strip().startswith("- ")]
        assert bullet_lines == []

    def test_gc_summary_omitted_when_none(self):
        """GC summary section must be absent when gc_report=None."""
        text = format_text(_report(), gc_report=None)
        assert "GC Summary" not in text

    def test_gc_summary_present_when_provided(self):
        """GC summary section must appear when gc_report is provided."""
        text = format_text(_report(), gc_report=_gc(soft_deleted=3))
        assert "GC Summary" in text
        assert "3" in text

    def test_gc_dry_run_label(self):
        """Dry-run GC reports must show 'dry-run' in the mode field."""
        text = format_text(_report(), gc_report=_gc(dry_run=True))
        assert "dry-run" in text

    def test_per_document_errors_shown(self):
        """Per-document errors in GC report must appear in text output."""
        status = StoreCleanupStatus(weaviate=False, errors=["weaviate: timeout"])
        gc = _gc(per_document={"problem_doc": status})
        text = format_text(_report(), gc_report=gc)

        assert "problem_doc" in text
        assert "weaviate: timeout" in text

    def test_manifest_only_keys_shown(self):
        """Manifest-only keys must appear in the text output."""
        report = _report(manifest_only=["ghost_doc"])
        text = format_text(report)
        assert "ghost_doc" in text


# ---------------------------------------------------------------------------
# Tests: format_json
# ---------------------------------------------------------------------------


class TestFormatJson:
    def test_returns_valid_json(self):
        """format_json must return valid JSON."""
        result = format_json(_report())
        parsed = json.loads(result)
        assert isinstance(parsed, dict)

    def test_orphan_keys_in_json(self):
        """JSON output must contain the orphan keys under 'orphans'."""
        report = _report(weaviate=["wk1"], minio=["mk1"], neo4j=["nk1"])
        parsed = json.loads(format_json(report))

        assert "orphans" in parsed
        assert parsed["orphans"]["weaviate"] == ["wk1"]
        assert parsed["orphans"]["minio"] == ["mk1"]
        assert parsed["orphans"]["neo4j"] == ["nk1"]

    def test_generated_at_present(self):
        """JSON output must contain a 'generated_at' ISO timestamp."""
        parsed = json.loads(format_json(_report()))
        assert "generated_at" in parsed
        # Quick sanity check: parseable as ISO datetime
        from datetime import datetime

        datetime.fromisoformat(parsed["generated_at"])

    def test_no_gc_key_when_gc_report_none(self):
        """'gc' key must be absent when gc_report is None."""
        parsed = json.loads(format_json(_report(), gc_report=None))
        assert "gc" not in parsed

    def test_gc_key_present_when_provided(self):
        """'gc' key must be present when gc_report is supplied."""
        parsed = json.loads(format_json(_report(), gc_report=_gc(soft_deleted=5)))
        assert "gc" in parsed
        assert parsed["gc"]["soft_deleted"] == 5

    def test_gc_per_document_serialised(self):
        """per_document statuses must be serialised in the 'gc' block."""
        status = StoreCleanupStatus(weaviate=True, minio=False, errors=["minio: err"])
        gc = _gc(per_document={"doc_x": status})
        parsed = json.loads(format_json(_report(), gc_report=gc))

        assert "doc_x" in parsed["gc"]["per_document"]
        assert parsed["gc"]["per_document"]["doc_x"]["minio"] is False

    def test_sorted_keys(self):
        """JSON output must have sorted keys (for determinism in tests)."""
        report = _report(weaviate=["z", "a"], minio=["b"])
        raw = format_json(report)
        parsed = json.loads(raw)
        # Re-serialise without sort_keys and verify keys match sorted order
        top_keys = list(parsed.keys())
        assert top_keys == sorted(top_keys)

    def test_indent_parameter_respected(self):
        """format_json must honour the indent parameter."""
        compact = format_json(_report(), indent=0)
        indented = format_json(_report(), indent=4)
        # Compact version is shorter
        assert len(compact) < len(indented)

    def test_empty_report_json(self):
        """An empty report must produce valid JSON with empty orphan lists."""
        parsed = json.loads(format_json(_report()))
        assert parsed["orphans"]["weaviate"] == []
        assert parsed["orphans"]["minio"] == []
        assert parsed["orphans"]["neo4j"] == []

    def test_manifest_only_in_json(self):
        """manifest_only keys must appear in the JSON orphans block."""
        report = _report(manifest_only=["m_doc"])
        parsed = json.loads(format_json(report))
        assert parsed["orphans"]["manifest_only"] == ["m_doc"]


# ---------------------------------------------------------------------------
# Tests: roundtrip (text -> json same data)
# ---------------------------------------------------------------------------


class TestRoundtrip:
    def test_both_formats_represent_same_counts(self):
        """Text and JSON outputs must reflect the same orphan counts."""
        report = _report(
            weaviate=["k1", "k2"],
            minio=["k3"],
            neo4j=[],
            manifest_only=["k4"],
        )
        text = format_text(report)
        parsed = json.loads(format_json(report))

        assert len(parsed["orphans"]["weaviate"]) == 2
        assert len(parsed["orphans"]["minio"]) == 1
        assert len(parsed["orphans"]["manifest_only"]) == 1
        assert "k1" in text
        assert "k3" in text
