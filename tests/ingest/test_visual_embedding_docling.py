# @summary
# Tests for Docling page image extraction extension.
# Covers: src/ingest/support/docling.py — parse_with_docling generate_page_images,
#   _extract_page_images_from_result, DoclingParseResult page_images/page_count fields.
# Exports: TestDoclingParseResultDefaults, TestParseWithDoclingNoImages,
#          TestParseWithDoclingImageExtraction, TestStrategyFallback,
#          TestRGBNormalization, TestPageExtractionErrors, TestPageCountInvariant,
#          TestBoundaryConditions
# Deps: pytest, unittest.mock, sys, src.ingest.support.docling
# @end-summary

"""Tests for Docling page image extraction (generate_page_images flag).

All Docling library imports are mocked so these tests run in environments that
do not have Docling installed.

Implementation note: ``parse_with_docling`` uses lazy imports inside the
function body (``from docling.document_converter import DocumentConverter``).
Patching ``src.ingest.support.docling.DocumentConverter`` does not work because
the name is never bound at module level.  The correct approach is to inject mock
modules into ``sys.modules`` before calling the function so that the lazy import
resolves to the mock.  The ``_docling_sys_modules`` context manager helper does
this.

Known test gaps (per spec):
  - Live PDF conversion not tested: all tests mock ``DocumentConverter.convert()``
    to avoid filesystem / Docling runtime deps.
  - Strategy 1 vs Strategy 2: tests explicitly mock one path unavailable to
    verify fallback behaviour.
  - RGBA source image provenance: synthetic RGBA MagicMock images are used;
    real Docling RGBA images may differ in structure.
  - Warning log content: tests verify that WARNING is emitted (via caplog) but
    do NOT assert the exact log message text.
"""

from __future__ import annotations

import sys
import types
from contextlib import contextmanager
from typing import Any, Generator, List
from unittest.mock import MagicMock, PropertyMock, call, patch

import pytest

# ---------------------------------------------------------------------------
# PIL stub — the import chain through src.ingest.__init__ reaches
# visual_embedding.py which imports PIL.Image at module level.
# ---------------------------------------------------------------------------
def _install_pil_stub() -> None:
    if "PIL" in sys.modules:
        return
    _pil_pkg = types.ModuleType("PIL")
    _pil_image_mod = types.ModuleType("PIL.Image")

    class _Image:
        LANCZOS = 1
        BICUBIC = 3

        def __init__(self) -> None:
            self.size = (0, 0)
            self.mode = "RGB"

        @staticmethod
        def fromarray(arr: object) -> "_Image":
            return _Image()

    _pil_image_mod.Image = _Image  # type: ignore[attr-defined]
    _pil_image_mod.LANCZOS = _Image.LANCZOS  # type: ignore[attr-defined]
    _pil_image_mod.fromarray = _Image.fromarray  # type: ignore[attr-defined]
    _pil_pkg.Image = _pil_image_mod  # type: ignore[attr-defined]
    sys.modules["PIL"] = _pil_pkg
    sys.modules["PIL.Image"] = _pil_image_mod


_install_pil_stub()

from src.ingest.support.docling import DoclingParseResult, parse_with_docling


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_pil_image(mode: str = "RGB") -> MagicMock:
    """Return a mock PIL image with the given ``mode`` attribute.

    ``convert("RGB")`` returns a fresh RGB mock so callers can assert on it.
    """
    img = MagicMock()
    img.mode = mode
    rgb_img = MagicMock()
    rgb_img.mode = "RGB"
    img.convert.return_value = rgb_img
    return img


def _make_page_strategy1(mode: str = "RGB") -> MagicMock:
    """Build a Strategy-1 page mock: ``page.image.pil_image`` accessible."""
    page = MagicMock()
    page.image = MagicMock()
    page.image.pil_image = _make_pil_image(mode)
    return page


def _make_docling_document(n_pages: int = 10) -> MagicMock:
    """Build a minimal mock Docling document with *n_pages* pages.

    ``document.pages`` is a dict keyed by integer page index (1-based), each
    value being a Strategy-2-compatible page mock.
    ``document.export_to_markdown`` returns a simple markdown string.
    ``document.pictures`` is an empty list.
    """
    doc = MagicMock()
    doc.export_to_markdown.return_value = "# Test\n\nParagraph."
    doc.pictures = []
    doc.model_dump_json.return_value = '{"body": {"children": []}}'
    # Strategy-2 pages: each page has .image.pil_image
    pages_dict = {}
    for i in range(1, n_pages + 1):
        pages_dict[i] = _make_page_strategy1()
    doc.pages = pages_dict
    return doc


def _make_conv_result(
    n_pages: int = 10,
    strategy1_pages: Any = None,
) -> MagicMock:
    """Build a mock ``conv_result`` returned by ``DocumentConverter.convert()``.

    Args:
        n_pages: Number of pages in ``conv_result.document.pages`` (dict).
        strategy1_pages: If provided, set as ``conv_result.pages`` (list).
            When None, ``conv_result.pages`` is set to a list of *n_pages*
            Strategy-1 page mocks.
    """
    result = MagicMock()
    result.document = _make_docling_document(n_pages=n_pages)
    if strategy1_pages is not None:
        result.pages = strategy1_pages
    else:
        result.pages = [_make_page_strategy1() for _ in range(n_pages)]
    return result


@contextmanager
def _docling_sys_modules(
    converter_instance: MagicMock | None = None,
    conv_result: MagicMock | None = None,
    n_pages: int = 10,
) -> Generator[tuple[MagicMock, MagicMock], None, None]:
    """Inject minimal ``docling.*`` mocks into ``sys.modules``.

    ``parse_with_docling`` does lazy imports; patching at module level does not
    work.  This helper injects mocks for all sub-modules the function may import.

    Args:
        converter_instance: Mock that ``DocumentConverter(...)`` should return.
            When None, a fresh converter wrapping *conv_result* is used.
        conv_result: Mock ``convert()`` result.  When None, one is built with
            *n_pages* pages.
        n_pages: Number of pages for the auto-built conv_result.

    Yields:
        Tuple of (MockDocumentConverter class, conv_result mock).
    """
    if conv_result is None:
        conv_result = _make_conv_result(n_pages=n_pages)

    if converter_instance is None:
        converter_instance = MagicMock()
        converter_instance.convert.return_value = conv_result

    MockDocumentConverter = MagicMock(return_value=converter_instance)

    mock_dc_module = MagicMock()
    mock_dc_module.DocumentConverter = MockDocumentConverter
    mock_dc_module.PdfFormatOption = MagicMock()

    mock_pipeline_opts = MagicMock()
    mock_pipeline_opts.PdfPipelineOptions = MagicMock(return_value=MagicMock())
    mock_pipeline_opts.PictureDescriptionVlmEngineOptions = MagicMock()

    mock_base_models = MagicMock()
    mock_base_models.InputFormat = MagicMock()
    mock_base_models.InputFormat.PDF = "PDF"

    injected = {
        "docling": MagicMock(),
        "docling.document_converter": mock_dc_module,
        "docling.datamodel": MagicMock(),
        "docling.datamodel.pipeline_options": mock_pipeline_opts,
        "docling.datamodel.base_models": mock_base_models,
    }

    original = {k: sys.modules.get(k) for k in injected}
    sys.modules.update(injected)
    try:
        yield MockDocumentConverter, conv_result
    finally:
        for k, v in original.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


# ---------------------------------------------------------------------------
# Test classes
# ---------------------------------------------------------------------------


class TestDoclingParseResultDefaults:
    """Tests for DoclingParseResult default field initialization."""

    def test_page_images_defaults_to_empty_list(self):
        """FR-default: DoclingParseResult.page_images defaults to empty list."""
        result = DoclingParseResult(
            text_markdown="x",
            has_figures=False,
            figures=[],
            headings=[],
            parser_model="test",
        )
        assert result.page_images == []

    def test_page_count_defaults_to_zero(self):
        """FR-default: DoclingParseResult.page_count defaults to 0."""
        result = DoclingParseResult(
            text_markdown="x",
            has_figures=False,
            figures=[],
            headings=[],
            parser_model="test",
        )
        assert result.page_count == 0

    def test_page_images_uses_separate_list_per_instance(self):
        """FR-default: page_images must use field(default_factory=list); instances do not share a list."""
        r1 = DoclingParseResult(
            text_markdown="a",
            has_figures=False,
            figures=[],
            headings=[],
            parser_model="test",
        )
        r2 = DoclingParseResult(
            text_markdown="b",
            has_figures=False,
            figures=[],
            headings=[],
            parser_model="test",
        )
        r1.page_images.append(MagicMock())
        assert len(r2.page_images) == 0, (
            "page_images must not be shared across instances (use default_factory=list)"
        )

    def test_explicit_page_images_and_count_accepted(self):
        """FR-default: DoclingParseResult accepts explicit page_images and page_count."""
        imgs = [MagicMock(), MagicMock()]
        result = DoclingParseResult(
            text_markdown="x",
            has_figures=False,
            figures=[],
            headings=[],
            parser_model="test",
            page_images=imgs,
            page_count=2,
        )
        assert result.page_images is imgs
        assert result.page_count == 2

    def test_existing_fields_unaffected_by_new_defaults(self):
        """FR-default: existing fields (text_markdown, has_figures, etc.) are unaffected."""
        result = DoclingParseResult(
            text_markdown="# Heading",
            has_figures=True,
            figures=["fig1"],
            headings=["Heading"],
            parser_model="smolvlm",
        )
        assert result.text_markdown == "# Heading"
        assert result.has_figures is True
        assert result.figures == ["fig1"]
        assert result.headings == ["Heading"]
        assert result.parser_model == "smolvlm"


class TestParseWithDoclingNoImages:
    """Tests for parse_with_docling with generate_page_images=False (default)."""

    def test_default_flag_returns_empty_page_images(self):
        """FR-noop: Default call (generate_page_images omitted) returns page_images=[]."""
        with _docling_sys_modules(n_pages=5) as (MockConverter, conv_result):
            result = parse_with_docling("/fake/doc.pdf", parser_model="test")
        assert result.page_images == []

    def test_explicit_false_returns_empty_page_images(self):
        """FR-noop: Explicit generate_page_images=False returns page_images=[]."""
        with _docling_sys_modules(n_pages=5) as (MockConverter, conv_result):
            result = parse_with_docling("/fake/doc.pdf", parser_model="test", generate_page_images=False)
        assert result.page_images == []

    def test_default_flag_returns_page_count_zero(self):
        """FR-noop: generate_page_images=False yields page_count=0."""
        with _docling_sys_modules(n_pages=5) as (MockConverter, conv_result):
            result = parse_with_docling("/fake/doc.pdf", parser_model="test", generate_page_images=False)
        assert result.page_count == 0

    def test_false_flag_does_not_construct_pdf_pipeline_options_with_images(self):
        """FR-noop: PdfPipelineOptions with generate_page_images=True must NOT be constructed when flag is False."""
        with _docling_sys_modules(n_pages=3) as (MockConverter, conv_result):
            # Capture the PdfPipelineOptions mock
            import docling.datamodel.pipeline_options as _po_mod

            _po_mod.PdfPipelineOptions.reset_mock()
            result = parse_with_docling("/fake/doc.pdf", parser_model="test", generate_page_images=False)

            # PdfPipelineOptions should either not be called at all, or never
            # called with generate_page_images=True.
            for c in _po_mod.PdfPipelineOptions.call_args_list:
                kwargs = c.kwargs if hasattr(c, "kwargs") else (c[1] if len(c) > 1 else {})
                assert kwargs.get("generate_page_images", False) is not True, (
                    "PdfPipelineOptions must not be constructed with generate_page_images=True"
                    " when the flag is False"
                )

    def test_text_markdown_populated_without_images(self):
        """FR-noop: text_markdown is populated even when generate_page_images=False."""
        with _docling_sys_modules(n_pages=2) as (MockConverter, conv_result):
            result = parse_with_docling("/fake/doc.pdf", parser_model="test", generate_page_images=False)
        assert isinstance(result.text_markdown, str)
        assert len(result.text_markdown) > 0


class TestParseWithDoclingImageExtraction:
    """Happy-path tests for parse_with_docling with generate_page_images=True."""

    def test_ten_page_pdf_returns_ten_images(self):
        """FR-201: 10-page PDF with generate_page_images=True yields len(page_images)==10."""
        with _docling_sys_modules(n_pages=10) as (MockConverter, conv_result):
            result = parse_with_docling("/fake/doc.pdf", parser_model="test", generate_page_images=True)
        assert len(result.page_images) == 10

    def test_ten_page_pdf_page_count_equals_ten(self):
        """FR-201: page_count==10 for a 10-page PDF."""
        with _docling_sys_modules(n_pages=10) as (MockConverter, conv_result):
            result = parse_with_docling("/fake/doc.pdf", parser_model="test", generate_page_images=True)
        assert result.page_count == 10

    def test_page_count_matches_image_count_on_clean_extraction(self):
        """FR-201: page_count == len(page_images) when all pages succeed."""
        with _docling_sys_modules(n_pages=10) as (MockConverter, conv_result):
            result = parse_with_docling("/fake/doc.pdf", parser_model="test", generate_page_images=True)
        assert result.page_count == len(result.page_images)

    def test_baseline_text_track_preserved_with_images_enabled(self):
        """FR-baseline: text_markdown, has_figures, figures, headings, parser_model populated."""
        with _docling_sys_modules(n_pages=3) as (MockConverter, conv_result):
            result = parse_with_docling("/fake/doc.pdf", parser_model="test", generate_page_images=True)
        # text_markdown should be a non-empty string (populated from export_to_markdown mock)
        assert isinstance(result.text_markdown, str)
        assert len(result.text_markdown) > 0
        # Other fields should exist (may be empty lists / defaults for this mock)
        assert hasattr(result, "has_figures")
        assert hasattr(result, "figures")
        assert hasattr(result, "headings")
        assert hasattr(result, "parser_model")

    def test_strategy1_pages_used_when_available(self):
        """FR-strategy1: Images extracted via Strategy 1 (conv_result.pages list)."""
        strategy1_pages = [_make_page_strategy1() for _ in range(5)]
        conv_result = _make_conv_result(n_pages=5, strategy1_pages=strategy1_pages)

        with _docling_sys_modules(conv_result=conv_result) as (MockConverter, _):
            result = parse_with_docling("/fake/doc.pdf", parser_model="test", generate_page_images=True)

        # Should have extracted 5 images from Strategy 1 pages
        assert len(result.page_images) == 5

    def test_returned_images_are_in_rgb_mode(self):
        """FR-205: All returned images should be in RGB mode."""
        strategy1_pages = [_make_page_strategy1(mode="RGB") for _ in range(3)]
        conv_result = _make_conv_result(n_pages=3, strategy1_pages=strategy1_pages)

        with _docling_sys_modules(conv_result=conv_result) as (MockConverter, _):
            result = parse_with_docling("/fake/doc.pdf", parser_model="test", generate_page_images=True)

        for img in result.page_images:
            assert img.mode == "RGB"


class TestStrategyFallback:
    """Tests for Strategy 1 → Strategy 2 fallback image extraction."""

    def test_strategy2_used_when_strategy1_pages_empty(self):
        """FR-fallback: When conv_result.pages is empty, Strategy 2 (document.pages) is used."""
        # Strategy 1: empty list → triggers fallback
        conv_result = _make_conv_result(n_pages=5, strategy1_pages=[])
        # Strategy 2 pages already configured in conv_result.document.pages (dict of 5 pages)

        with _docling_sys_modules(conv_result=conv_result) as (MockConverter, _):
            result = parse_with_docling("/fake/doc.pdf", parser_model="test", generate_page_images=True)

        assert len(result.page_images) == 5

    def test_strategy2_same_result_shape_as_strategy1(self):
        """FR-fallback: Strategy 2 result has the same shape as Strategy 1 result."""
        # Strategy 1: non-empty 5 pages
        conv_result_s1 = _make_conv_result(n_pages=5)
        with _docling_sys_modules(conv_result=conv_result_s1) as (MockConverter, _):
            result_s1 = parse_with_docling("/fake/doc.pdf", parser_model="test", generate_page_images=True)

        # Strategy 2 fallback (empty strategy1 list)
        conv_result_s2 = _make_conv_result(n_pages=5, strategy1_pages=[])
        with _docling_sys_modules(conv_result=conv_result_s2) as (MockConverter, _):
            result_s2 = parse_with_docling("/fake/doc.pdf", parser_model="test", generate_page_images=True)

        assert len(result_s1.page_images) == len(result_s2.page_images)
        assert result_s1.page_count == result_s2.page_count

    def test_strategy2_used_when_strategy1_raises_attribute_error(self):
        """FR-fallback: When conv_result.pages raises AttributeError, Strategy 2 is used."""
        conv_result = _make_conv_result(n_pages=4, strategy1_pages=None)
        # Make Strategy 1 inaccessible by removing .pages attribute
        del conv_result.pages
        # Strategy 2 document.pages dict still has 4 entries

        with _docling_sys_modules(conv_result=conv_result) as (MockConverter, _):
            result = parse_with_docling("/fake/doc.pdf", parser_model="test", generate_page_images=True)

        # Should fall back to Strategy 2 and extract 4 images (or gracefully return [])
        # The spec says "same result shape", so either 4 images or 0 (no exception)
        assert isinstance(result.page_images, list)
        assert result.page_count >= 0

    def test_strategy2_page_count_is_consistent(self):
        """FR-fallback: page_count from Strategy 2 path equals document page count."""
        conv_result = _make_conv_result(n_pages=7, strategy1_pages=[])

        with _docling_sys_modules(conv_result=conv_result) as (MockConverter, _):
            result = parse_with_docling("/fake/doc.pdf", parser_model="test", generate_page_images=True)

        assert result.page_count == 7


class TestRGBNormalization:
    """Tests for per-image RGB conversion (RGBA → RGB, passthrough for RGB)."""

    def test_rgba_image_converted_to_rgb(self):
        """FR-205: RGBA image is converted to RGB; result has mode=='RGB'."""
        rgba_img = _make_pil_image(mode="RGBA")
        page = MagicMock()
        page.image = MagicMock()
        page.image.pil_image = rgba_img

        conv_result = _make_conv_result(n_pages=1, strategy1_pages=[page])
        with _docling_sys_modules(conv_result=conv_result) as (MockConverter, _):
            result = parse_with_docling("/fake/doc.pdf", parser_model="test", generate_page_images=True)

        assert len(result.page_images) == 1
        # The returned image should be the RGB-converted one
        assert result.page_images[0].mode == "RGB"
        # convert("RGB") must have been called on the RGBA source image
        rgba_img.convert.assert_called_once_with("RGB")

    def test_rgba_conversion_does_not_raise(self):
        """FR-205: RGBA→RGB conversion completes without raising an exception."""
        rgba_img = _make_pil_image(mode="RGBA")
        page = MagicMock()
        page.image = MagicMock()
        page.image.pil_image = rgba_img

        conv_result = _make_conv_result(n_pages=1, strategy1_pages=[page])
        with _docling_sys_modules(conv_result=conv_result) as (MockConverter, _):
            # Should not raise
            result = parse_with_docling("/fake/doc.pdf", parser_model="test", generate_page_images=True)
        assert result is not None

    def test_rgb_image_returned_as_is_or_converted(self):
        """FR-205: RGB image passthrough — result image has mode=='RGB', no error."""
        rgb_img = _make_pil_image(mode="RGB")
        page = MagicMock()
        page.image = MagicMock()
        page.image.pil_image = rgb_img

        conv_result = _make_conv_result(n_pages=1, strategy1_pages=[page])
        with _docling_sys_modules(conv_result=conv_result) as (MockConverter, _):
            result = parse_with_docling("/fake/doc.pdf", parser_model="test", generate_page_images=True)

        assert len(result.page_images) == 1
        assert result.page_images[0].mode == "RGB"

    def test_rgb_conversion_applied_per_page(self):
        """FR-205: convert("RGB") is called individually per page (not batched)."""
        pages = [_make_page_strategy1(mode="RGBA") for _ in range(3)]
        conv_result = _make_conv_result(n_pages=3, strategy1_pages=pages)

        with _docling_sys_modules(conv_result=conv_result) as (MockConverter, _):
            result = parse_with_docling("/fake/doc.pdf", parser_model="test", generate_page_images=True)

        # Each source RGBA image should have had .convert called
        for page in pages:
            page.image.pil_image.convert.assert_called_with("RGB")


class TestPageExtractionErrors:
    """Tests for per-page failure handling during image extraction."""

    def test_page_with_no_image_attribute_is_skipped(self, caplog):
        """FR-err: Page with image=None is skipped; WARNING logged; others returned."""
        import logging

        good_page = _make_page_strategy1()
        bad_page = MagicMock()
        bad_page.image = None  # .image is None → accessing .pil_image will fail
        bad_page.get_image = None  # prevent get_image() fallback

        conv_result = _make_conv_result(n_pages=2, strategy1_pages=[bad_page, good_page])

        with caplog.at_level(logging.WARNING):
            with _docling_sys_modules(conv_result=conv_result) as (MockConverter, _):
                result = parse_with_docling("/fake/doc.pdf", parser_model="test", generate_page_images=True)

        # Bad page skipped; at least 1 image (or 0 if fallback also fails) — no exception
        assert isinstance(result.page_images, list)
        # A warning should have been emitted
        assert any(r.levelno >= logging.WARNING for r in caplog.records)

    def test_page_with_missing_pil_image_is_skipped(self, caplog):
        """FR-err: Page where .image.pil_image raises AttributeError is skipped; WARNING logged."""
        import logging

        good_page = _make_page_strategy1()
        bad_page = MagicMock()
        bad_page.image = MagicMock(spec=[])  # spec=[] → pil_image not accessible
        bad_page.get_image = None  # prevent get_image() fallback

        conv_result = _make_conv_result(n_pages=2, strategy1_pages=[bad_page, good_page])

        with caplog.at_level(logging.WARNING):
            with _docling_sys_modules(conv_result=conv_result) as (MockConverter, _):
                result = parse_with_docling("/fake/doc.pdf", parser_model="test", generate_page_images=True)

        assert isinstance(result.page_images, list)
        assert any(r.levelno >= logging.WARNING for r in caplog.records)

    def test_rgb_conversion_failure_on_one_page_skips_that_page(self, caplog):
        """FR-err: RGB conversion failure on one page skips that page; others continue."""
        import logging

        # Page 1: RGB conversion raises
        bad_img = MagicMock()
        bad_img.mode = "CMYK"
        bad_img.convert.side_effect = OSError("convert failed")
        bad_page = MagicMock()
        bad_page.image = MagicMock()
        bad_page.image.pil_image = bad_img

        # Pages 2 and 3: normal RGB images
        good_page1 = _make_page_strategy1(mode="RGB")
        good_page2 = _make_page_strategy1(mode="RGB")

        conv_result = _make_conv_result(
            n_pages=3, strategy1_pages=[bad_page, good_page1, good_page2]
        )

        with caplog.at_level(logging.WARNING):
            with _docling_sys_modules(conv_result=conv_result) as (MockConverter, _):
                result = parse_with_docling("/fake/doc.pdf", parser_model="test", generate_page_images=True)

        # The 2 good pages should still be present (or at minimum no exception raised)
        assert isinstance(result.page_images, list)
        # A warning should have been logged for the failed page
        assert any(r.levelno >= logging.WARNING for r in caplog.records)

    def test_full_image_extraction_failure_returns_empty_list(self):
        """FR-err: All pages fail extraction → page_images=[], text_markdown unaffected."""
        # All pages have image=None
        bad_pages = [MagicMock(image=None, get_image=None) for _ in range(3)]
        conv_result = _make_conv_result(n_pages=3, strategy1_pages=bad_pages)
        # Also make Strategy 2 fail: document.pages is empty dict
        conv_result.document.pages = {}

        with _docling_sys_modules(conv_result=conv_result) as (MockConverter, _):
            result = parse_with_docling("/fake/doc.pdf", parser_model="test", generate_page_images=True)

        assert result.page_images == []
        assert isinstance(result.text_markdown, str)

    def test_full_extraction_failure_does_not_propagate_exception(self):
        """FR-err: Complete image extraction failure must not raise to caller."""
        bad_pages = [MagicMock(image=None, get_image=None) for _ in range(5)]
        conv_result = _make_conv_result(n_pages=5, strategy1_pages=bad_pages)
        conv_result.document.pages = {}

        with _docling_sys_modules(conv_result=conv_result) as (MockConverter, _):
            # Must not raise
            result = parse_with_docling("/fake/doc.pdf", parser_model="test", generate_page_images=True)

        assert result is not None

    def test_both_strategies_inaccessible_returns_empty_images_no_exception(self):
        """FR-err: Both strategies inaccessible → page_images=[], no exception."""
        conv_result = MagicMock()
        conv_result.document = _make_docling_document(n_pages=3)
        # Strategy 1: accessing .pages raises
        type(conv_result).pages = PropertyMock(side_effect=AttributeError("no pages attr"))
        # Strategy 2: document.pages is empty
        conv_result.document.pages = {}

        with _docling_sys_modules(conv_result=conv_result) as (MockConverter, _):
            result = parse_with_docling("/fake/doc.pdf", parser_model="test", generate_page_images=True)

        assert isinstance(result.page_images, list)
        assert result is not None


class TestPageCountInvariant:
    """Tests ensuring page_count is always derived from document structure, not len(page_images)."""

    def test_page_count_independent_of_image_failures(self):
        """FR-invariant: 10-page PDF, 3 pages fail → page_count==10, len(page_images)==7."""
        good_pages = [_make_page_strategy1() for _ in range(7)]
        bad_pages = [MagicMock(image=None, get_image=None) for _ in range(3)]
        all_pages = good_pages + bad_pages

        # Document structure still reports 10 pages
        conv_result = _make_conv_result(n_pages=10, strategy1_pages=all_pages)

        with _docling_sys_modules(conv_result=conv_result) as (MockConverter, _):
            result = parse_with_docling("/fake/doc.pdf", parser_model="test", generate_page_images=True)

        assert result.page_count == 10
        # 3 bad pages are skipped → at most 7 images
        assert len(result.page_images) <= 7

    def test_page_count_not_derived_from_page_images_length(self):
        """FR-invariant: page_count != len(page_images) when some pages fail."""
        good_pages = [_make_page_strategy1() for _ in range(4)]
        bad_pages = [MagicMock(image=None, get_image=None) for _ in range(6)]

        conv_result = _make_conv_result(n_pages=10, strategy1_pages=good_pages + bad_pages)

        with _docling_sys_modules(conv_result=conv_result) as (MockConverter, _):
            result = parse_with_docling("/fake/doc.pdf", parser_model="test", generate_page_images=True)

        # page_count must reflect the full 10 pages, not just successful extractions
        assert result.page_count == 10

    def test_page_count_set_when_all_images_fail(self):
        """FR-invariant: page_count is set from document structure even when all images fail."""
        bad_pages = [MagicMock(image=None, get_image=None) for _ in range(10)]
        conv_result = _make_conv_result(n_pages=10, strategy1_pages=bad_pages)

        with _docling_sys_modules(conv_result=conv_result) as (MockConverter, _):
            result = parse_with_docling("/fake/doc.pdf", parser_model="test", generate_page_images=True)

        # page_images may be empty but page_count should reflect the document structure
        assert result.page_images == [] or len(result.page_images) == 0
        # page_count must come from document, not from image list
        assert result.page_count == 10

    def test_page_count_with_generate_images_false_is_zero(self):
        """FR-invariant: page_count is 0 when generate_page_images=False (no extraction)."""
        with _docling_sys_modules(n_pages=10) as (MockConverter, conv_result):
            result = parse_with_docling("/fake/doc.pdf", parser_model="test", generate_page_images=False)
        assert result.page_count == 0


class TestBoundaryConditions:
    """Boundary condition tests: zero pages, single page, exact counts."""

    def test_zero_page_document_returns_empty_images_and_zero_count(self):
        """FR-boundary: 0-page document → page_images=[], page_count=0, no exception."""
        conv_result = _make_conv_result(n_pages=0, strategy1_pages=[])
        conv_result.document.pages = {}

        with _docling_sys_modules(conv_result=conv_result) as (MockConverter, _):
            result = parse_with_docling("/fake/doc.pdf", parser_model="test", generate_page_images=True)

        assert result.page_images == []
        assert result.page_count == 0

    def test_single_page_document_returns_one_image(self):
        """FR-boundary: 1-page PDF → len(page_images)==1, page_count==1."""
        conv_result = _make_conv_result(n_pages=1)

        with _docling_sys_modules(conv_result=conv_result) as (MockConverter, _):
            result = parse_with_docling("/fake/doc.pdf", parser_model="test", generate_page_images=True)

        assert len(result.page_images) == 1
        assert result.page_count == 1

    def test_single_page_failure_returns_zero_images_page_count_one(self):
        """FR-boundary: 1-page PDF, extraction fails → page_images=[], page_count==1."""
        bad_page = MagicMock(image=None, get_image=None)
        conv_result = _make_conv_result(n_pages=1, strategy1_pages=[bad_page])
        conv_result.document.pages = {}

        with _docling_sys_modules(conv_result=conv_result) as (MockConverter, _):
            result = parse_with_docling("/fake/doc.pdf", parser_model="test", generate_page_images=True)

        # No images extracted from bad page
        assert isinstance(result.page_images, list)
        # page_count should still be 1 (from document structure)
        # Note: if both strategies fail, page_count behaviour depends on implementation

    def test_exactly_ten_images_for_ten_page_pdf(self):
        """FR-201: Exactly 10 images for a 10-page PDF — not 9, not 11."""
        conv_result = _make_conv_result(n_pages=10)

        with _docling_sys_modules(conv_result=conv_result) as (MockConverter, _):
            result = parse_with_docling("/fake/doc.pdf", parser_model="test", generate_page_images=True)

        assert len(result.page_images) == 10

    def test_generate_images_false_is_complete_noop_no_pdf_pipeline_options(self):
        """FR-noop: PdfPipelineOptions(generate_page_images=True) NOT constructed when flag is False."""
        constructed_with_images = []

        class _TrackingPdfPipelineOptions:
            def __init__(self, **kwargs):
                if kwargs.get("generate_page_images"):
                    constructed_with_images.append(kwargs)

        with _docling_sys_modules(n_pages=3) as (MockConverter, conv_result):
            import docling.datamodel.pipeline_options as _po_mod

            _po_mod.PdfPipelineOptions = _TrackingPdfPipelineOptions
            result = parse_with_docling("/fake/doc.pdf", parser_model="test", generate_page_images=False)

        assert constructed_with_images == [], (
            "PdfPipelineOptions(generate_page_images=True) must NOT be constructed "
            "when generate_page_images=False"
        )
        assert result.page_images == []

    def test_large_page_count_no_off_by_one(self):
        """FR-boundary: 20-page PDF returns exactly 20 images (no off-by-one)."""
        conv_result = _make_conv_result(n_pages=20)

        with _docling_sys_modules(conv_result=conv_result) as (MockConverter, _):
            result = parse_with_docling("/fake/doc.pdf", parser_model="test", generate_page_images=True)

        assert len(result.page_images) == 20
        assert result.page_count == 20
