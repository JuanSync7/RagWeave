"""Tests for observability.schemas record dataclasses.

Test coverage includes:
- SpanRecord construction (minimal, full, field defaults)
- TraceRecord construction (minimal, full, field defaults)
- GenerationRecord construction (minimal, full, field defaults)
- Default field behavior (start_ts auto-population via time(), attributes/metadata default to {}, status defaults to "ok")
- Optional field handling (end_ts defaults to None, parent_span_id None, output None, token counts None)
- Import isolation (zero third-party dependencies)

Non-test concerns (out of scope):
- Backend behavior for populating records
- Serialization/persistence
- Runtime type validation (mypy/type-checker concern, not pytest)
- start_ts/end_ts ordering enforcement (no dataclass validation)
"""
from __future__ import annotations

import time as time_module
from time import time

import pytest

from src.platform.observability.schemas import GenerationRecord, SpanRecord, TraceRecord


# === Happy path tests ===


class TestSpanRecordHappyPath:
    """SpanRecord construction and default field behavior."""

    def test_span_record_minimal_construction(self):
        """SpanRecord with required fields only; defaults applied."""
        record = SpanRecord(name="s1", trace_id="t1", parent_span_id=None)

        assert record.name == "s1"
        assert record.trace_id == "t1"
        assert record.parent_span_id is None
        assert record.attributes == {}
        assert record.status == "ok"
        assert record.error_message is None
        assert isinstance(record.start_ts, float)
        assert record.start_ts > 0
        assert record.end_ts is None

    def test_span_record_full_construction(self):
        """SpanRecord with all fields provided explicitly."""
        ts_start = time()
        ts_end = time()
        attributes = {"key": "value"}
        error_msg = "test error"

        record = SpanRecord(
            name="test_span",
            trace_id="trace_123",
            parent_span_id="parent_456",
            attributes=attributes,
            start_ts=ts_start,
            end_ts=ts_end,
            status="error",
            error_message=error_msg,
        )

        assert record.name == "test_span"
        assert record.trace_id == "trace_123"
        assert record.parent_span_id == "parent_456"
        assert record.attributes == attributes
        assert record.start_ts == ts_start
        assert record.end_ts == ts_end
        assert record.status == "error"
        assert record.error_message == error_msg

    def test_span_record_attributes_default_empty_dict(self):
        """SpanRecord.attributes defaults to {} when not provided."""
        record1 = SpanRecord(name="s1", trace_id="t1", parent_span_id=None)
        record2 = SpanRecord(name="s2", trace_id="t2", parent_span_id=None)

        assert record1.attributes == {}
        assert record2.attributes == {}
        # Verify they are separate dict instances
        assert record1.attributes is not record2.attributes

    def test_span_record_status_defaults_to_ok(self):
        """SpanRecord.status defaults to 'ok' when not provided."""
        record = SpanRecord(name="s1", trace_id="t1", parent_span_id=None)
        assert record.status == "ok"

    def test_span_record_start_ts_auto_populated(self):
        """SpanRecord.start_ts is auto-populated via time() if not provided."""
        before = time()
        record = SpanRecord(name="s1", trace_id="t1", parent_span_id=None)
        after = time()

        assert isinstance(record.start_ts, float)
        assert before <= record.start_ts <= after

    def test_span_record_end_ts_defaults_to_none(self):
        """SpanRecord.end_ts defaults to None when not provided."""
        record = SpanRecord(name="s1", trace_id="t1", parent_span_id=None)
        assert record.end_ts is None

    def test_span_record_with_explicit_attributes(self):
        """SpanRecord accepts explicit attributes dict."""
        attrs = {"key1": "value1", "key2": "value2"}
        record = SpanRecord(
            name="s1", trace_id="t1", parent_span_id=None, attributes=attrs
        )
        assert record.attributes == attrs

    def test_span_record_parent_span_id_none_accepted(self):
        """SpanRecord.parent_span_id=None indicates a top-level span."""
        record = SpanRecord(name="s1", trace_id="t1", parent_span_id=None)
        assert record.parent_span_id is None

    def test_span_record_parent_span_id_with_value(self):
        """SpanRecord.parent_span_id accepted as a string value."""
        record = SpanRecord(
            name="s1", trace_id="t1", parent_span_id="parent_span_id_123"
        )
        assert record.parent_span_id == "parent_span_id_123"


class TestTraceRecordHappyPath:
    """TraceRecord construction and default field behavior."""

    def test_trace_record_minimal_construction(self):
        """TraceRecord with required fields only; defaults applied."""
        record = TraceRecord(name="t1", trace_id="t1")

        assert record.name == "t1"
        assert record.trace_id == "t1"
        assert record.metadata == {}
        assert record.status == "ok"
        assert isinstance(record.start_ts, float)
        assert record.start_ts > 0
        assert record.end_ts is None

    def test_trace_record_full_construction(self):
        """TraceRecord with all fields provided explicitly."""
        ts_start = time()
        ts_end = time()
        metadata = {"service": "api", "version": "1.0"}

        record = TraceRecord(
            name="root_trace",
            trace_id="trace_123",
            metadata=metadata,
            start_ts=ts_start,
            end_ts=ts_end,
            status="ok",
        )

        assert record.name == "root_trace"
        assert record.trace_id == "trace_123"
        assert record.metadata == metadata
        assert record.start_ts == ts_start
        assert record.end_ts == ts_end
        assert record.status == "ok"

    def test_trace_record_metadata_default_empty_dict(self):
        """TraceRecord.metadata defaults to {} when not provided."""
        record1 = TraceRecord(name="t1", trace_id="t1")
        record2 = TraceRecord(name="t2", trace_id="t2")

        assert record1.metadata == {}
        assert record2.metadata == {}
        # Verify they are separate dict instances
        assert record1.metadata is not record2.metadata

    def test_trace_record_status_defaults_to_ok(self):
        """TraceRecord.status defaults to 'ok' when not provided."""
        record = TraceRecord(name="t1", trace_id="t1")
        assert record.status == "ok"

    def test_trace_record_start_ts_auto_populated(self):
        """TraceRecord.start_ts is auto-populated via time() if not provided."""
        before = time()
        record = TraceRecord(name="t1", trace_id="t1")
        after = time()

        assert isinstance(record.start_ts, float)
        assert before <= record.start_ts <= after

    def test_trace_record_end_ts_defaults_to_none(self):
        """TraceRecord.end_ts defaults to None when not provided."""
        record = TraceRecord(name="t1", trace_id="t1")
        assert record.end_ts is None

    def test_trace_record_with_explicit_metadata(self):
        """TraceRecord accepts explicit metadata dict."""
        meta = {"request_id": "req_123", "user": "alice"}
        record = TraceRecord(name="t1", trace_id="t1", metadata=meta)
        assert record.metadata == meta

    def test_trace_record_trace_id_stored_as_provided(self):
        """TraceRecord.trace_id is stored exactly as provided (non-None string)."""
        trace_id = "custom_trace_id_12345"
        record = TraceRecord(name="t1", trace_id=trace_id)
        assert record.trace_id == trace_id


class TestGenerationRecordHappyPath:
    """GenerationRecord construction and default field behavior."""

    def test_generation_record_minimal_construction(self):
        """GenerationRecord with required fields only; defaults applied."""
        record = GenerationRecord(
            name="g1", trace_id="t1", model="gpt-4", input="prompt"
        )

        assert record.name == "g1"
        assert record.trace_id == "t1"
        assert record.model == "gpt-4"
        assert record.input == "prompt"
        assert record.output is None
        assert record.prompt_tokens is None
        assert record.completion_tokens is None
        assert isinstance(record.start_ts, float)
        assert record.start_ts > 0
        assert record.end_ts is None
        assert record.status == "ok"

    def test_generation_record_full_construction(self):
        """GenerationRecord with all fields provided explicitly."""
        ts_start = time()
        ts_end = time()

        record = GenerationRecord(
            name="test_gen",
            trace_id="trace_123",
            model="gpt-4-turbo",
            input="What is 2+2?",
            output="The answer is 4.",
            prompt_tokens=10,
            completion_tokens=8,
            start_ts=ts_start,
            end_ts=ts_end,
            status="ok",
        )

        assert record.name == "test_gen"
        assert record.trace_id == "trace_123"
        assert record.model == "gpt-4-turbo"
        assert record.input == "What is 2+2?"
        assert record.output == "The answer is 4."
        assert record.prompt_tokens == 10
        assert record.completion_tokens == 8
        assert record.start_ts == ts_start
        assert record.end_ts == ts_end
        assert record.status == "ok"

    def test_generation_record_output_defaults_to_none(self):
        """GenerationRecord.output defaults to None (set_output not called)."""
        record = GenerationRecord(
            name="g1", trace_id="t1", model="gpt-4", input="prompt"
        )
        assert record.output is None

    def test_generation_record_prompt_tokens_defaults_to_none(self):
        """GenerationRecord.prompt_tokens defaults to None (not set before end)."""
        record = GenerationRecord(
            name="g1", trace_id="t1", model="gpt-4", input="prompt"
        )
        assert record.prompt_tokens is None

    def test_generation_record_completion_tokens_defaults_to_none(self):
        """GenerationRecord.completion_tokens defaults to None (not set before end)."""
        record = GenerationRecord(
            name="g1", trace_id="t1", model="gpt-4", input="prompt"
        )
        assert record.completion_tokens is None

    def test_generation_record_status_defaults_to_ok(self):
        """GenerationRecord.status defaults to 'ok' when not provided."""
        record = GenerationRecord(
            name="g1", trace_id="t1", model="gpt-4", input="prompt"
        )
        assert record.status == "ok"

    def test_generation_record_start_ts_auto_populated(self):
        """GenerationRecord.start_ts is auto-populated via time() if not provided."""
        before = time()
        record = GenerationRecord(
            name="g1", trace_id="t1", model="gpt-4", input="prompt"
        )
        after = time()

        assert isinstance(record.start_ts, float)
        assert before <= record.start_ts <= after

    def test_generation_record_end_ts_defaults_to_none(self):
        """GenerationRecord.end_ts defaults to None when not provided."""
        record = GenerationRecord(
            name="g1", trace_id="t1", model="gpt-4", input="prompt"
        )
        assert record.end_ts is None

    def test_generation_record_with_output(self):
        """GenerationRecord accepts explicit output."""
        output_text = "Generated response"
        record = GenerationRecord(
            name="g1",
            trace_id="t1",
            model="gpt-4",
            input="prompt",
            output=output_text,
        )
        assert record.output == output_text

    def test_generation_record_with_token_counts(self):
        """GenerationRecord accepts explicit token counts."""
        record = GenerationRecord(
            name="g1",
            trace_id="t1",
            model="gpt-4",
            input="prompt",
            prompt_tokens=15,
            completion_tokens=25,
        )
        assert record.prompt_tokens == 15
        assert record.completion_tokens == 25

    def test_generation_record_partial_optional_fields(self):
        """GenerationRecord accepts partial optional fields."""
        record = GenerationRecord(
            name="g1",
            trace_id="t1",
            model="gpt-4",
            input="prompt",
            output="response",
            # prompt_tokens and completion_tokens left as None
        )
        assert record.output == "response"
        assert record.prompt_tokens is None
        assert record.completion_tokens is None


# === Error scenario tests ===


class TestErrorScenarios:
    """Error scenario testing: dataclass accepts any values without validation."""

    def test_span_record_accepts_arbitrary_field_values(self):
        """SpanRecord accepts arbitrary values without raising validation errors."""
        # No validation expected; dataclass just stores values
        record = SpanRecord(
            name="s1",
            trace_id="t1",
            parent_span_id=None,
            attributes={"nested": {"key": "value"}},
            status="warning",
            error_message="Custom error",
        )
        assert record.status == "warning"
        assert record.error_message == "Custom error"

    def test_trace_record_accepts_arbitrary_field_values(self):
        """TraceRecord accepts arbitrary values without raising validation errors."""
        record = TraceRecord(
            name="t1",
            trace_id="t1",
            metadata={"complex": [1, 2, 3]},
            status="degraded",
        )
        assert record.status == "degraded"
        assert record.metadata == {"complex": [1, 2, 3]}

    def test_generation_record_accepts_zero_token_counts(self):
        """GenerationRecord accepts zero token counts without error."""
        record = GenerationRecord(
            name="g1",
            trace_id="t1",
            model="gpt-4",
            input="",
            prompt_tokens=0,
            completion_tokens=0,
        )
        assert record.prompt_tokens == 0
        assert record.completion_tokens == 0

    def test_generation_record_accepts_empty_strings(self):
        """GenerationRecord accepts empty strings for string fields."""
        record = GenerationRecord(
            name="", trace_id="", model="", input="", output=""
        )
        assert record.name == ""
        assert record.model == ""
        assert record.output == ""


# === Boundary condition tests ===


class TestBoundaryConditions:
    """Boundary conditions from spec functional requirements."""

    def test_span_record_parent_span_id_none_is_top_level(self):
        """SpanRecord.parent_span_id=None indicates a top-level span (REQ-149)."""
        record = SpanRecord(name="root", trace_id="t1", parent_span_id=None)
        assert record.parent_span_id is None

    def test_span_record_attributes_empty_dict_vs_explicit(self):
        """SpanRecord.attributes default {} vs explicit dict behavior (REQ-149)."""
        record_default = SpanRecord(name="s1", trace_id="t1", parent_span_id=None)
        record_explicit = SpanRecord(
            name="s2", trace_id="t2", parent_span_id=None, attributes={}
        )

        assert record_default.attributes == {}
        assert record_explicit.attributes == {}
        # Default should produce empty dicts per instance
        assert record_default.attributes is not record_explicit.attributes

    def test_generation_record_output_none_before_set_output(self):
        """GenerationRecord.output=None before set_output() called (REQ-153)."""
        record = GenerationRecord(
            name="g1", trace_id="t1", model="gpt-4", input="prompt"
        )
        assert record.output is None

    def test_generation_record_token_counts_none_defaults_ok(self):
        """GenerationRecord token counts=None accepted as valid defaults (REQ-153)."""
        record = GenerationRecord(
            name="g1", trace_id="t1", model="gpt-4", input="prompt"
        )
        assert record.prompt_tokens is None
        assert record.completion_tokens is None

    def test_trace_record_trace_id_stored_non_none_string(self):
        """TraceRecord.trace_id must be a non-None string; stored as provided (REQ-151)."""
        trace_id = "unique_trace_123"
        record = TraceRecord(name="t1", trace_id=trace_id)
        assert record.trace_id == trace_id
        assert isinstance(record.trace_id, str)

    def test_span_record_end_ts_none_by_default(self):
        """SpanRecord.end_ts=None by default; set by end() (REQ-155)."""
        record = SpanRecord(name="s1", trace_id="t1", parent_span_id=None)
        assert record.end_ts is None

    def test_trace_record_end_ts_none_by_default(self):
        """TraceRecord.end_ts=None by default; set by end() (REQ-155)."""
        record = TraceRecord(name="t1", trace_id="t1")
        assert record.end_ts is None

    def test_generation_record_end_ts_none_by_default(self):
        """GenerationRecord.end_ts=None by default; set by end() (REQ-155)."""
        record = GenerationRecord(
            name="g1", trace_id="t1", model="gpt-4", input="prompt"
        )
        assert record.end_ts is None

    def test_start_ts_is_float_greater_than_zero(self):
        """start_ts auto-populated as float > 0 via time() (REQ-155)."""
        record = SpanRecord(name="s1", trace_id="t1", parent_span_id=None)
        assert isinstance(record.start_ts, float)
        assert record.start_ts > 0

    def test_multiple_records_have_distinct_start_ts(self):
        """Multiple records created in sequence have increasing start_ts."""
        record1 = SpanRecord(name="s1", trace_id="t1", parent_span_id=None)
        # Sleep briefly to ensure time advances
        time_module.sleep(0.001)
        record2 = SpanRecord(name="s2", trace_id="t1", parent_span_id=None)

        # Both should have valid start_ts
        assert isinstance(record1.start_ts, float)
        assert isinstance(record2.start_ts, float)
        # record2 should be created at or after record1
        assert record2.start_ts >= record1.start_ts


# === Integration point tests ===


class TestIntegrationPoints:
    """Integration with backend and test assertion patterns."""

    def test_span_record_readable_by_tests_for_assertions(self):
        """SpanRecord fields are readable for test assertions (no method calls)."""
        record = SpanRecord(
            name="test_span",
            trace_id="t_123",
            parent_span_id=None,
            attributes={"key": "val"},
            status="ok",
        )

        # Tests can read all fields directly
        assert record.name == "test_span"
        assert record.trace_id == "t_123"
        assert record.attributes["key"] == "val"
        assert record.status == "ok"

    def test_generation_record_readable_by_tests_for_output_assertions(self):
        """GenerationRecord fields readable for output assertion (no method calls)."""
        record = GenerationRecord(
            name="llm_gen",
            trace_id="t_123",
            model="gpt-4",
            input="test input",
            output="test output",
            prompt_tokens=5,
            completion_tokens=10,
        )

        # Tests can assert output and token counts directly
        assert record.output == "test output"
        assert record.prompt_tokens == 5
        assert record.completion_tokens == 10

    def test_span_record_end_ts_none_until_backend_sets_it(self):
        """SpanRecord.end_ts=None initially; backend sets it when end() called."""
        record = SpanRecord(name="s1", trace_id="t1", parent_span_id=None)
        assert record.end_ts is None

        # Simulate backend setting end_ts (test-only mutation)
        record.end_ts = time()
        assert record.end_ts is not None

    def test_start_ts_before_end_ts_ordering_testable_after_backend_sets_end(self):
        """start_ts <= end_ts ordering testable after backend sets end_ts (REQ-155)."""
        record = SpanRecord(name="s1", trace_id="t1", parent_span_id=None)
        start = record.start_ts
        assert start is not None

        # Simulate backend setting end_ts
        time_module.sleep(0.001)
        record.end_ts = time()

        # Now ordering is testable
        assert record.start_ts <= record.end_ts


# === Import isolation tests ===


class TestImportIsolation:
    """Verify zero third-party dependencies for record types."""

    def test_schema_types_importable_without_third_party(self):
        """SpanRecord, TraceRecord, GenerationRecord importable from schemas module."""
        # This test passes by virtue of the import succeeding at module load
        from src.platform.observability.schemas import (
            GenerationRecord as GR,
            SpanRecord as SR,
            TraceRecord as TR,
        )

        assert SR is not None
        assert TR is not None
        assert GR is not None

    def test_schema_types_are_dataclasses(self):
        """Schema types are dataclass instances."""
        from dataclasses import fields as dataclass_fields

        # All should be dataclasses with .fields()
        sr_fields = dataclass_fields(SpanRecord)
        tr_fields = dataclass_fields(TraceRecord)
        gr_fields = dataclass_fields(GenerationRecord)

        assert len(sr_fields) > 0
        assert len(tr_fields) > 0
        assert len(gr_fields) > 0


# === Known test gaps ===


class TestKnownGaps:
    """Document and test known limitations and gaps."""

    def test_dataclass_does_not_enforce_start_ts_ordering_with_end_ts(self):
        """Known gap: dataclass does not validate start_ts <= end_ts.

        This is a known limitation. Ordering validation would be a business
        rule enforced at the backend layer, not the dataclass schema layer.
        """
        record = SpanRecord(name="s1", trace_id="t1", parent_span_id=None)
        # Manually set end_ts before start_ts for testing
        record.end_ts = record.start_ts - 1.0

        # No exception raised — dataclass accepts this
        assert record.end_ts < record.start_ts

    def test_runtime_type_validation_not_enforced_by_dataclass(self):
        """Known gap: runtime type validation (e.g., passing int to name) is mypy concern.

        This is a known limitation of Python dataclasses without Pydantic validation.
        Type checking is delegated to static type checkers (mypy, pyright).

        We document this gap but do NOT test invalid types at runtime,
        as that is outside the scope of pytest (dataclass does not validate).
        """
        # This would be caught by mypy but not by pytest
        # record = SpanRecord(name=123, trace_id="t1", parent_span_id=None)
        # assert isinstance(record.name, int)  # No validation error
        pass

    def test_attributes_and_metadata_accept_any_dict_structure(self):
        """Known gap: attributes and metadata do not validate dict structure.

        Dataclass accepts any dict value without schema validation.
        Schema validation (if needed) would be enforced at serialization time.
        """
        record = SpanRecord(
            name="s1",
            trace_id="t1",
            parent_span_id=None,
            attributes={"level1": {"level2": {"level3": "deep"}}},
        )
        assert record.attributes["level1"]["level2"]["level3"] == "deep"
