# @summary
# Tests for MinIO page image storage functions in src/db/minio/store.py.
# Covers: store_page_images, delete_page_images — key generation, JPEG
#         serialization, per-page failure isolation, listing/deletion semantics,
#         buffer rewind regression, and boundary conditions.
# Exports: (pytest test functions)
# Deps: pytest, unittest.mock, io
# @end-summary
"""Tests for MinIO page image storage (store_page_images, delete_page_images)."""

import io
import pytest
from unittest.mock import MagicMock, call, patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DEFAULT_BUCKET = "rag-documents"


def _make_client() -> MagicMock:
    """Return a fresh MagicMock MinIO client."""
    return MagicMock()


def _make_image(byte_payload: bytes = b"\xff\xd8\xff" + b"\x00" * 256) -> MagicMock:
    """Return a mock PIL Image whose .save() writes *byte_payload* into buffer arg."""

    def _save_side_effect(buf, format=None, quality=85):  # noqa: A002
        buf.write(byte_payload)

    img = MagicMock(spec=["save"])
    img.save.side_effect = _save_side_effect
    return img


def _make_images(n: int, payload: bytes = b"\xff\xd8\xff" + b"\x00" * 256) -> list:
    return [(i + 1, _make_image(payload)) for i in range(n)]


def _make_list_objects(keys: list[str]) -> list:
    """Return a list of mock MinIO objects with .object_name set."""
    items = []
    for key in keys:
        obj = MagicMock()
        obj.object_name = key
        items.append(obj)
    return items


# ---------------------------------------------------------------------------
# Key format tests
# ---------------------------------------------------------------------------


class TestStorePageImagesKeyFormat:
    """FR-401: Key pattern, 1-indexed, zero-padded to 4 digits."""

    def test_first_key_is_one_indexed(self):
        """FR-401: Page 1 produces 0001.jpg — never 0000.jpg."""
        from src.db.minio.store import store_page_images

        client = _make_client()
        pages = _make_images(1)

        result = store_page_images(client, "doc-1", pages)

        assert len(result) == 1
        assert result[0] == "pages/doc-1/0001.jpg"

    def test_no_zero_page_key_ever_produced(self):
        """FR-401: 0000.jpg must never appear in returned keys."""
        from src.db.minio.store import store_page_images

        client = _make_client()
        pages = _make_images(5)

        result = store_page_images(client, "doc-1", pages)

        for key in result:
            assert not key.endswith("0000.jpg"), f"Found 0-indexed key: {key!r}"

    def test_page_10_is_zero_padded_to_4_digits(self):
        """FR-401: Page 10 of 10 produces pages/doc-1/0010.jpg."""
        from src.db.minio.store import store_page_images

        client = _make_client()
        pages = _make_images(10)

        result = store_page_images(client, "doc-1", pages)

        assert result[-1] == "pages/doc-1/0010.jpg"

    def test_key_prefix_is_pages_namespace(self):
        """FR-404: All generated keys are under pages/, not documents/."""
        from src.db.minio.store import store_page_images

        client = _make_client()
        pages = _make_images(3)

        result = store_page_images(client, "abc-123", pages)

        for key in result:
            assert key.startswith("pages/"), f"Key not under pages/ namespace: {key!r}"
            assert not key.startswith("documents/"), f"Key leaked into documents/ namespace: {key!r}"

    def test_key_embeds_document_id_correctly(self):
        """Key second segment equals document_id verbatim."""
        from src.db.minio.store import store_page_images

        client = _make_client()
        pages = _make_images(1)
        doc_id = "abc-123"

        result = store_page_images(client, doc_id, pages)

        assert result[0] == f"pages/{doc_id}/0001.jpg"

    def test_ten_pages_produce_sequential_keys(self):
        """FR-401: 10 pages produce keys 0001.jpg through 0010.jpg in order."""
        from src.db.minio.store import store_page_images

        client = _make_client()
        pages = _make_images(10)

        result = store_page_images(client, "abc-123", pages)

        expected = [f"pages/abc-123/{i:04d}.jpg" for i in range(1, 11)]
        assert result == expected


# ---------------------------------------------------------------------------
# Happy path tests
# ---------------------------------------------------------------------------


class TestStorePageImagesHappyPath:
    """Successful store_page_images invocations: call counts, arguments, return values."""

    def test_store_10_pages_returns_10_keys(self):
        """All 10 put_object calls succeed → 10 keys returned."""
        from src.db.minio.store import store_page_images

        client = _make_client()
        pages = _make_images(10)

        result = store_page_images(client, "abc-123", pages)

        assert len(result) == 10
        assert client.put_object.call_count == 10

    def test_put_object_called_with_correct_content_type(self):
        """put_object always receives content_type='image/jpeg'."""
        from src.db.minio.store import store_page_images

        client = _make_client()
        pages = _make_images(3)

        store_page_images(client, "doc-x", pages)

        for c in client.put_object.call_args_list:
            kwargs = c.kwargs
            args = c.args
            # content_type may be positional or keyword; check both
            ct = kwargs.get("content_type") or (args[4] if len(args) > 4 else None)
            assert ct == "image/jpeg", f"Expected image/jpeg, got {ct!r}"

    def test_put_object_called_with_correct_keys(self):
        """put_object receives the zero-padded key as second positional arg."""
        from src.db.minio.store import store_page_images

        client = _make_client()
        pages = _make_images(3)

        store_page_images(client, "doc-99", pages)

        call_keys = [c.args[1] for c in client.put_object.call_args_list]
        assert call_keys == [
            "pages/doc-99/0001.jpg",
            "pages/doc-99/0002.jpg",
            "pages/doc-99/0003.jpg",
        ]

    def test_put_object_receives_byte_accurate_length(self):
        """length passed to put_object equals the number of bytes written by image.save."""
        from src.db.minio.store import store_page_images

        payload = b"\xff\xd8\xff" + b"\xAB" * 512
        client = _make_client()
        pages = [(1, _make_image(payload))]

        store_page_images(client, "doc-len", pages)

        assert client.put_object.call_count == 1
        c = client.put_object.call_args
        # length is 4th positional arg (bucket, key, data, length) or keyword
        length = c.kwargs.get("length") or c.args[3]
        assert length == len(payload), f"Expected length {len(payload)}, got {length}"

    def test_default_quality_is_85(self):
        """image.save is called with quality=85 when no quality arg is passed."""
        from src.db.minio.store import store_page_images

        client = _make_client()
        img = _make_image()
        pages = [(1, img)]

        store_page_images(client, "doc-q", pages)

        img.save.assert_called_once()
        _, kwargs = img.save.call_args
        assert kwargs.get("quality") == 85

    def test_custom_quality_is_forwarded(self):
        """image.save is called with the caller-supplied quality value."""
        from src.db.minio.store import store_page_images

        client = _make_client()
        img = _make_image()
        pages = [(1, img)]

        store_page_images(client, "doc-q", pages, quality=50)

        img.save.assert_called_once()
        _, kwargs = img.save.call_args
        assert kwargs.get("quality") == 50

    def test_custom_bucket_forwarded_to_put_object(self):
        """put_object is called with the custom bucket name."""
        from src.db.minio.store import store_page_images

        client = _make_client()
        pages = _make_images(1)

        store_page_images(client, "doc-b", pages, bucket="custom-bucket")

        c = client.put_object.call_args
        bucket_arg = c.kwargs.get("bucket") or c.args[0]
        assert bucket_arg == "custom-bucket"

    def test_empty_pages_list_returns_empty_list(self):
        """Empty pages input → empty result; put_object never called."""
        from src.db.minio.store import store_page_images

        client = _make_client()

        result = store_page_images(client, "doc-empty", [])

        assert result == []
        client.put_object.assert_not_called()

    def test_single_page_document_produces_one_key(self):
        """Single-element pages list produces exactly one key: 0001.jpg."""
        from src.db.minio.store import store_page_images

        client = _make_client()
        pages = _make_images(1)

        result = store_page_images(client, "doc-single", pages)

        assert result == ["pages/doc-single/0001.jpg"]
        assert client.put_object.call_count == 1


# ---------------------------------------------------------------------------
# Error isolation tests for store_page_images
# ---------------------------------------------------------------------------


class TestStorePageImagesErrors:
    """Per-page failure isolation: log WARNING + continue; no exception to caller."""

    def test_single_page_failure_excluded_from_stored_keys(self):
        """put_object failure for one page → that key absent; no exception raised."""
        from src.db.minio.store import store_page_images

        client = _make_client()
        client.put_object.side_effect = RuntimeError("upload failed")
        pages = _make_images(1)

        result = store_page_images(client, "doc-fail", pages)

        assert result == []

    def test_all_pages_fail_returns_empty_list(self):
        """All put_object calls fail → returns [] without raising."""
        from src.db.minio.store import store_page_images

        client = _make_client()
        client.put_object.side_effect = RuntimeError("network error")
        pages = _make_images(5)

        result = store_page_images(client, "doc-all-fail", pages)

        assert result == []

    def test_first_page_fails_remaining_pages_succeed(self):
        """put_object fails on page 1, succeeds on pages 2+; returns N-1 keys."""
        from src.db.minio.store import store_page_images

        client = _make_client()
        call_count = {"n": 0}

        def _put_side_effect(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("first page upload failed")

        client.put_object.side_effect = _put_side_effect
        pages = _make_images(4)

        result = store_page_images(client, "doc-partial", pages)

        # Page 1 key must be absent
        assert "pages/doc-partial/0001.jpg" not in result
        # Pages 2-4 must be present
        assert "pages/doc-partial/0002.jpg" in result
        assert "pages/doc-partial/0003.jpg" in result
        assert "pages/doc-partial/0004.jpg" in result
        assert len(result) == 3

    def test_middle_page_fails_others_succeed(self):
        """put_object fails on page k of N; remaining pages continue; key k absent."""
        from src.db.minio.store import store_page_images

        client = _make_client()
        call_count = {"n": 0}

        def _put_side_effect(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 3:
                raise RuntimeError("middle page failed")

        client.put_object.side_effect = _put_side_effect
        pages = _make_images(5)

        result = store_page_images(client, "doc-mid-fail", pages)

        assert "pages/doc-mid-fail/0003.jpg" not in result
        assert len(result) == 4

    def test_image_save_failure_skips_page_and_continues(self):
        """image.save raises → page skipped; WARNING logged; remaining pages processed."""
        from src.db.minio.store import store_page_images

        client = _make_client()

        # Page 1 raises on save; pages 2 and 3 succeed normally
        bad_img = MagicMock(spec=["save"])
        bad_img.save.side_effect = OSError("disk full")
        pages = [(1, bad_img), (2, _make_image()), (3, _make_image())]

        result = store_page_images(client, "doc-save-fail", pages)

        assert "pages/doc-save-fail/0001.jpg" not in result
        assert len(result) == 2

    def test_per_page_failure_does_not_propagate_exception(self):
        """No exception reaches the caller regardless of put_object failure."""
        from src.db.minio.store import store_page_images

        client = _make_client()
        client.put_object.side_effect = Exception("fatal store error")
        pages = _make_images(3)

        # Must not raise
        result = store_page_images(client, "doc-no-raise", pages)
        assert isinstance(result, list)

    def test_single_page_failure_warning_logged(self):
        """WARNING is logged for a page that fails to store."""
        from src.db.minio.store import store_page_images

        client = _make_client()
        client.put_object.side_effect = RuntimeError("boom")
        pages = _make_images(1)

        with patch("src.db.minio.store.logger") as mock_logger:
            store_page_images(client, "doc-warn", pages)

        assert mock_logger.warning.called or mock_logger.warn.called


# ---------------------------------------------------------------------------
# Happy path tests for delete_page_images
# ---------------------------------------------------------------------------


class TestDeletePageImagesHappyPath:
    """Successful delete_page_images invocations."""

    def test_delete_10_pages_returns_count_10(self):
        """Listing returns 10 objects → remove_object called 10 times → returns 10."""
        from src.db.minio.store import delete_page_images

        client = _make_client()
        keys = [f"pages/abc-123/{i:04d}.jpg" for i in range(1, 11)]
        client.list_objects.return_value = _make_list_objects(keys)

        result = delete_page_images(client, "abc-123")

        assert result == 10
        assert client.remove_object.call_count == 10

    def test_delete_uses_correct_prefix(self):
        """list_objects called with prefix='pages/{document_id}/' and recursive=True."""
        from src.db.minio.store import delete_page_images

        client = _make_client()
        client.list_objects.return_value = []

        delete_page_images(client, "abc-123")

        client.list_objects.assert_called_once()
        c = client.list_objects.call_args
        prefix = c.kwargs.get("prefix") or c.args[1]
        recursive = c.kwargs.get("recursive")
        assert prefix == "pages/abc-123/"
        assert recursive is True

    def test_delete_zero_pages_returns_zero(self):
        """Listing returns no objects → returns 0; remove_object never called."""
        from src.db.minio.store import delete_page_images

        client = _make_client()
        client.list_objects.return_value = []

        result = delete_page_images(client, "empty-doc")

        assert result == 0
        client.remove_object.assert_not_called()

    def test_delete_calls_remove_object_with_each_key(self):
        """remove_object is called with the exact object_name from each listing item."""
        from src.db.minio.store import delete_page_images

        client = _make_client()
        keys = ["pages/doc-del/0001.jpg", "pages/doc-del/0002.jpg"]
        client.list_objects.return_value = _make_list_objects(keys)

        delete_page_images(client, "doc-del")

        expected_calls = [call(DEFAULT_BUCKET, "pages/doc-del/0001.jpg"),
                          call(DEFAULT_BUCKET, "pages/doc-del/0002.jpg")]
        # Accept either positional or keyword bucket arg — check object names at minimum
        actual_names = [c.args[1] if len(c.args) > 1 else c.kwargs.get("object_name")
                        for c in client.remove_object.call_args_list]
        assert actual_names == keys

    def test_delete_custom_bucket_passed_to_list_and_remove(self):
        """list_objects and remove_object both receive the custom bucket name."""
        from src.db.minio.store import delete_page_images

        client = _make_client()
        keys = ["pages/doc-x/0001.jpg"]
        client.list_objects.return_value = _make_list_objects(keys)

        delete_page_images(client, "doc-x", bucket="custom-bucket")

        # list_objects bucket
        list_c = client.list_objects.call_args
        list_bucket = list_c.kwargs.get("bucket") or list_c.args[0]
        assert list_bucket == "custom-bucket"

        # remove_object bucket
        rm_c = client.remove_object.call_args
        rm_bucket = rm_c.kwargs.get("bucket") or rm_c.args[0]
        assert rm_bucket == "custom-bucket"


# ---------------------------------------------------------------------------
# Error tests for delete_page_images
# ---------------------------------------------------------------------------


class TestDeletePageImagesErrors:
    """Failure isolation for delete_page_images: listing failure, removal failure."""

    def test_listing_failure_returns_zero_and_logs_warning(self):
        """list_objects raises → WARNING logged; returns 0; remove_object not called."""
        from src.db.minio.store import delete_page_images

        client = _make_client()
        client.list_objects.side_effect = RuntimeError("bucket unavailable")

        with patch("src.db.minio.store.logger") as mock_logger:
            result = delete_page_images(client, "doc-list-fail")

        assert result == 0
        client.remove_object.assert_not_called()
        assert mock_logger.warning.called or mock_logger.warn.called

    def test_listing_failure_no_exception_propagated(self):
        """list_objects raises → no exception reaches caller."""
        from src.db.minio.store import delete_page_images

        client = _make_client()
        client.list_objects.side_effect = Exception("unexpected error")

        result = delete_page_images(client, "doc-no-raise")
        assert isinstance(result, int)

    def test_first_removal_failure_returns_zero_early_exit(self):
        """remove_object raises on first object → returns 0 (early exit, no increment)."""
        from src.db.minio.store import delete_page_images

        client = _make_client()
        keys = ["pages/doc-rm/0001.jpg", "pages/doc-rm/0002.jpg", "pages/doc-rm/0003.jpg"]
        client.list_objects.return_value = _make_list_objects(keys)
        client.remove_object.side_effect = RuntimeError("first remove failed")

        result = delete_page_images(client, "doc-rm")

        assert result == 0

    def test_mid_sequence_removal_failure_returns_preceding_count(self):
        """remove_object fails on object k → returns k-1 (objects removed before failure)."""
        from src.db.minio.store import delete_page_images

        client = _make_client()
        keys = [f"pages/doc-mid/{i:04d}.jpg" for i in range(1, 6)]
        client.list_objects.return_value = _make_list_objects(keys)
        call_count = {"n": 0}

        def _rm_side_effect(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 3:
                raise RuntimeError("mid-removal failure")

        client.remove_object.side_effect = _rm_side_effect

        result = delete_page_images(client, "doc-mid")

        # 2 successful removals before failure on the 3rd
        assert result == 2

    def test_mid_sequence_failure_logs_warning(self):
        """remove_object failure → WARNING logged."""
        from src.db.minio.store import delete_page_images

        client = _make_client()
        keys = ["pages/doc-warn-rm/0001.jpg", "pages/doc-warn-rm/0002.jpg"]
        client.list_objects.return_value = _make_list_objects(keys)
        client.remove_object.side_effect = [None, RuntimeError("remove failed")]

        with patch("src.db.minio.store.logger") as mock_logger:
            delete_page_images(client, "doc-warn-rm")

        assert mock_logger.warning.called or mock_logger.warn.called

    def test_first_removal_failure_early_exit_no_further_remove_calls(self):
        """Early exit on first removal failure: remove_object called exactly once."""
        from src.db.minio.store import delete_page_images

        client = _make_client()
        keys = [f"pages/doc-early/{i:04d}.jpg" for i in range(1, 5)]
        client.list_objects.return_value = _make_list_objects(keys)
        client.remove_object.side_effect = RuntimeError("hard fail")

        delete_page_images(client, "doc-early")

        assert client.remove_object.call_count == 1


# ---------------------------------------------------------------------------
# Boundary conditions
# ---------------------------------------------------------------------------


class TestBoundaryConditions:
    """Regression-prone details: buffer rewind, key indexing, namespace isolation."""

    def test_buffer_seek_zero_called_before_put_object(self):
        """Buffer rewind regression: seek(0) must be called so MinIO reads from start.

        We verify by checking that the length passed to put_object matches the
        bytes written — i.e. the buffer was properly managed. A seek(0) is
        implicitly required for put_object to read from position 0; if seek(0)
        were missing, the data stream would be empty.

        # NOTE: Full buffer-position ordering (seek after write, before put_object)
        # can only be guaranteed with real I/O; this test covers the byte-accurate
        # length contract as a proxy.
        """
        from src.db.minio.store import store_page_images

        payload = b"\xff\xd8\xff" + b"\xBE" * 100
        client = _make_client()
        pages = [(1, _make_image(payload))]

        store_page_images(client, "doc-seek", pages)

        assert client.put_object.call_count == 1
        c = client.put_object.call_args
        length = c.kwargs.get("length") or c.args[3]
        assert length == len(payload), (
            "length mismatch implies buffer was not rewound before put_object"
        )

    def test_single_page_document_key_is_0001(self):
        """Single-element pages list → one key, always 0001.jpg."""
        from src.db.minio.store import store_page_images

        client = _make_client()
        pages = _make_images(1)

        result = store_page_images(client, "single-page-doc", pages)

        assert result == ["pages/single-page-doc/0001.jpg"]

    def test_key_numbering_strictly_one_indexed_never_zero(self):
        """Exhaustively confirm 0000.jpg is absent across a multi-page run."""
        from src.db.minio.store import store_page_images

        client = _make_client()
        pages = _make_images(10)

        result = store_page_images(client, "doc-index-check", pages)

        zero_keys = [k for k in result if "0000" in k]
        assert zero_keys == [], f"Zero-indexed keys found: {zero_keys}"

    def test_pages_namespace_isolation_no_documents_prefix(self):
        """FR-404: No key ever begins with 'documents/'."""
        from src.db.minio.store import store_page_images

        client = _make_client()
        pages = _make_images(5)

        result = store_page_images(client, "ns-test-doc", pages)

        leaked = [k for k in result if k.startswith("documents/")]
        assert leaked == [], f"Keys leaked into documents/ namespace: {leaked}"

    def test_delete_custom_bucket_list_and_remove_both_use_it(self):
        """list_objects and remove_object both use 'custom-bucket' (not default)."""
        from src.db.minio.store import delete_page_images

        client = _make_client()
        keys = ["pages/doc-cb/0001.jpg", "pages/doc-cb/0002.jpg"]
        client.list_objects.return_value = _make_list_objects(keys)

        delete_page_images(client, "doc-cb", bucket="custom-bucket")

        list_c = client.list_objects.call_args
        list_bucket = list_c.kwargs.get("bucket") or list_c.args[0]
        assert list_bucket == "custom-bucket"

        for rm_c in client.remove_object.call_args_list:
            rm_bucket = rm_c.kwargs.get("bucket") or rm_c.args[0]
            assert rm_bucket == "custom-bucket"

    def test_image_save_called_with_jpeg_format(self):
        """image.save is called with format='JPEG'."""
        from src.db.minio.store import store_page_images

        client = _make_client()
        img = _make_image()
        pages = [(1, img)]

        store_page_images(client, "doc-fmt", pages)

        img.save.assert_called_once()
        _, kwargs = img.save.call_args
        assert kwargs.get("format") == "JPEG"

    def test_store_returns_list_type(self):
        """store_page_images always returns a list (not None or other type)."""
        from src.db.minio.store import store_page_images

        client = _make_client()

        result = store_page_images(client, "doc-type", [])
        assert isinstance(result, list)

    def test_delete_returns_int_type(self):
        """delete_page_images always returns an int."""
        from src.db.minio.store import delete_page_images

        client = _make_client()
        client.list_objects.return_value = []

        result = delete_page_images(client, "doc-int")
        assert isinstance(result, int)


# ---------------------------------------------------------------------------
# Known gaps (documented, not implemented)
# ---------------------------------------------------------------------------
# GAP-1: Real JPEG byte validation (FR-402 full coverage) requires integration
#        test with real PIL + real MinIO — cannot cover with synthetic mocks.
# GAP-2: File size range check (FR-402 30KB–300KB) depends on actual image
#        content and compression — cannot be enforced with mock payloads.
# GAP-3: FR-403 ordering guarantee (store_page_images completes before ColQwen2
#        load) is an orchestration-level invariant, out of scope for this module.
# GAP-4: Exact buffer seek(0) ordering relative to put_object is only fully
#        verifiable with real I/O; the length-proxy test is an approximation.
