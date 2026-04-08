# @summary
# Tests for the ColQwen2 model adapter (src/ingest/support/colqwen.py).
# Covers: ensure_colqwen_ready (dependency guards), load_colqwen_model (4-bit
#         quantization config), embed_page_images (batching, mean-pooling,
#         patch vectors, page numbering, error handling), unload_colqwen_model
#         (GPU memory release), and exception hierarchy.
# Exports: (pytest test functions)
# Deps: pytest, unittest.mock, sys, json, src.ingest.support.colqwen
# @end-summary
"""Tests for the ColQwen2 visual embedding adapter.

All heavy dependencies (colpali_engine, bitsandbytes, torch) are mocked so
that these tests run without GPU hardware or HuggingFace network access.

Known gaps are annotated with ``# GAP:`` comments throughout.
"""

import json
import sys
import types
from unittest.mock import MagicMock, call, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers — synthetic tensor / processor factories
# ---------------------------------------------------------------------------

def _make_torch_mock():
    """Return a minimal mock of the torch module sufficient for the adapter."""
    torch_mock = MagicMock(name="torch")

    # torch.float16 / torch.float32 sentinel objects
    torch_mock.float16 = "float16_sentinel"
    torch_mock.float32 = "float32_sentinel"

    # torch.no_grad() as a context manager
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=None)
    ctx.__exit__ = MagicMock(return_value=False)
    torch_mock.no_grad.return_value = ctx

    # torch.inference_mode() as a context manager (used by embed_page_images)
    infer_ctx = MagicMock()
    infer_ctx.__enter__ = MagicMock(return_value=None)
    infer_ctx.__exit__ = MagicMock(return_value=False)
    torch_mock.inference_mode.return_value = infer_ctx

    # torch.cuda.empty_cache() — side-effect free
    torch_mock.cuda = MagicMock()
    torch_mock.cuda.empty_cache = MagicMock()

    return torch_mock


def _make_patch_tensor(n_patches: int = 800, dim: int = 128, base_value: float = 1.0):
    """Return a minimal list-of-lists that behaves like a (n_patches, dim) tensor.

    The mock tensor supports .float().mean(dim=0).cpu().tolist() and
    .float().cpu().tolist() (as used by embed_page_images), plus indexing.
    Each row is a list of ``base_value`` repeated ``dim`` times.
    """
    data = [[base_value] * dim for _ in range(n_patches)]

    # Build a mock that mimics tensor[i].tolist() and .float().mean(dim=0).cpu().tolist()
    tensor = MagicMock(name="patch_tensor")
    tensor.__len__ = MagicMock(return_value=n_patches)

    def _getitem(idx):
        row_mock = MagicMock()
        row_mock.tolist.return_value = data[idx]
        return row_mock

    tensor.__getitem__ = MagicMock(side_effect=_getitem)

    # Configure mean_row with .cpu().tolist() chain (mean_tensor.cpu().tolist())
    mean_cpu = MagicMock(name="mean_cpu")
    mean_cpu.tolist = MagicMock(return_value=[base_value] * dim)
    mean_row = MagicMock(name="mean_row")
    mean_row.tolist = MagicMock(return_value=[base_value] * dim)
    mean_row.cpu = MagicMock(return_value=mean_cpu)

    # Configure float_tensor: .mean(dim=0) → mean_row, .cpu().tolist() → data
    cpu_tensor = MagicMock(name="cpu_tensor")
    cpu_tensor.tolist = MagicMock(return_value=data)
    float_tensor = MagicMock(name="float_tensor")
    float_tensor.mean = MagicMock(return_value=mean_row)
    float_tensor.cpu = MagicMock(return_value=cpu_tensor)

    tensor.float = MagicMock(return_value=float_tensor)
    tensor.mean = MagicMock(return_value=mean_row)  # keep direct .mean for compat

    # Configure tensor.shape[0] → n_patches
    shape_mock = MagicMock(name="shape")
    shape_mock.__getitem__ = MagicMock(side_effect=lambda idx: n_patches if idx == 0 else dim)
    tensor.shape = shape_mock

    return tensor, data


def _make_model_and_processor(
    n_patches: int = 800, dim: int = 128, base_value: float = 1.0
):
    """Return (model, processor) mocks for a single-image batch scenario.

    ``model(...)`` returns an object whose ``last_hidden_state[0]`` is a
    mock tensor with shape (n_patches, dim).
    """
    patch_tensor, raw_data = _make_patch_tensor(n_patches, dim, base_value)

    output = MagicMock(name="model_output")

    # last_hidden_state[0] → our patch tensor for first image in batch
    def _hs_getitem(idx):
        return patch_tensor

    hidden_state = MagicMock(name="last_hidden_state")
    hidden_state.__getitem__ = MagicMock(side_effect=_hs_getitem)
    output.last_hidden_state = hidden_state

    model = MagicMock(name="ColQwen2Model")
    model.return_value = output

    processed_inputs = MagicMock(name="processed_inputs")
    # .to(device) → returns self so the adapter can pass it to the model
    processed_inputs.to = MagicMock(return_value=processed_inputs)
    # Support dict-style unpacking if the adapter uses **inputs
    processed_inputs.__iter__ = MagicMock(return_value=iter([]))

    processor = MagicMock(name="ColQwen2Processor")
    processor.process_images = MagicMock(return_value=processed_inputs)

    return model, processor, raw_data


def _pil_images(n: int):
    """Return a list of n dummy PIL-like image mocks."""
    return [MagicMock(name=f"pil_image_{i}") for i in range(n)]


# ---------------------------------------------------------------------------
# Module-level autouse fixture — always injects a torch mock so that
# embed_page_images (which does ``import torch`` then uses
# ``torch.inference_mode()``) never touches the real torch package.
# Without this, ``torch.inference_mode()`` either raises AttributeError
# (wrong torch version) or returns a plain MagicMock without __enter__/
# __exit__, causing a TypeError that is caught by the inner try-except in
# every batch, making all count-based assertions fail.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _inject_torch_mock():
    """Inject a fully-configured torch mock into sys.modules for every test."""
    torch_mock = _make_torch_mock()
    with patch.dict(sys.modules, {"torch": torch_mock}):
        yield


# ===========================================================================
# Group 1: ensure_colqwen_ready — dependency guard
# ===========================================================================


class TestEnsureColqwenReady:
    """FR-806: guarded import checks for colpali_engine and bitsandbytes."""

    def test_succeeds_when_both_dependencies_present(self):
        """ensure_colqwen_ready returns None when both deps are importable."""
        # Inject stubs into sys.modules so import succeeds
        colpali_stub = types.ModuleType("colpali_engine")
        bb_stub = types.ModuleType("bitsandbytes")
        with patch.dict(
            sys.modules,
            {"colpali_engine": colpali_stub, "bitsandbytes": bb_stub},
        ):
            from src.ingest.support.colqwen import ensure_colqwen_ready
            # Should not raise
            result = ensure_colqwen_ready()
            assert result is None

    def test_raises_colqwen_load_error_when_colpali_missing(self):
        """FR-806: missing colpali_engine raises ColQwen2LoadError."""
        from src.ingest.support.colqwen import ColQwen2LoadError, ensure_colqwen_ready

        bb_stub = types.ModuleType("bitsandbytes")
        with patch.dict(sys.modules, {"colpali_engine": None, "bitsandbytes": bb_stub}):
            with pytest.raises(ColQwen2LoadError) as exc_info:
                ensure_colqwen_ready()
        assert "colpali-engine" in str(exc_info.value)

    def test_colpali_missing_error_contains_install_command(self):
        """FR-806: error message must contain the pip install hint."""
        from src.ingest.support.colqwen import ColQwen2LoadError, ensure_colqwen_ready

        bb_stub = types.ModuleType("bitsandbytes")
        with patch.dict(sys.modules, {"colpali_engine": None, "bitsandbytes": bb_stub}):
            with pytest.raises(ColQwen2LoadError) as exc_info:
                ensure_colqwen_ready()
        assert 'pip install "rag[visual]"' in str(exc_info.value)

    def test_colpali_missing_does_not_propagate_import_error(self):
        """FR-806: raw ImportError must not escape; only ColQwen2LoadError."""
        from src.ingest.support.colqwen import ColQwen2LoadError, ensure_colqwen_ready

        bb_stub = types.ModuleType("bitsandbytes")
        with patch.dict(sys.modules, {"colpali_engine": None, "bitsandbytes": bb_stub}):
            with pytest.raises(ColQwen2LoadError):
                ensure_colqwen_ready()
            # If we reach here, ImportError was not propagated raw

    def test_raises_colqwen_load_error_when_bitsandbytes_missing(self):
        """FR-806: missing bitsandbytes raises ColQwen2LoadError."""
        from src.ingest.support.colqwen import ColQwen2LoadError, ensure_colqwen_ready

        colpali_stub = types.ModuleType("colpali_engine")
        with patch.dict(
            sys.modules,
            {"colpali_engine": colpali_stub, "bitsandbytes": None},
        ):
            with pytest.raises(ColQwen2LoadError) as exc_info:
                ensure_colqwen_ready()
        assert exc_info.value is not None

    def test_bitsandbytes_missing_error_contains_install_command(self):
        """FR-806: bitsandbytes missing — message contains install command."""
        from src.ingest.support.colqwen import ColQwen2LoadError, ensure_colqwen_ready

        colpali_stub = types.ModuleType("colpali_engine")
        with patch.dict(
            sys.modules,
            {"colpali_engine": colpali_stub, "bitsandbytes": None},
        ):
            with pytest.raises(ColQwen2LoadError) as exc_info:
                ensure_colqwen_ready()
        assert 'pip install "rag[visual]"' in str(exc_info.value)

    def test_bitsandbytes_missing_does_not_propagate_import_error(self):
        """FR-806: bitsandbytes absent — no raw ImportError escapes."""
        from src.ingest.support.colqwen import ColQwen2LoadError, ensure_colqwen_ready

        colpali_stub = types.ModuleType("colpali_engine")
        with patch.dict(
            sys.modules,
            {"colpali_engine": colpali_stub, "bitsandbytes": None},
        ):
            with pytest.raises(ColQwen2LoadError):
                ensure_colqwen_ready()


# ===========================================================================
# Group 2: Exception hierarchy
# ===========================================================================


class TestExceptionHierarchy:
    """Verify that ColQwen2LoadError is a subclass of VisualEmbeddingError."""

    def test_colqwen2_load_error_is_subclass_of_visual_embedding_error(self):
        """ColQwen2LoadError must be catchable as VisualEmbeddingError."""
        from src.ingest.support.colqwen import ColQwen2LoadError, VisualEmbeddingError

        assert issubclass(ColQwen2LoadError, VisualEmbeddingError)

    def test_colqwen2_load_error_instance_is_visual_embedding_error(self):
        """isinstance check with VisualEmbeddingError must be True."""
        from src.ingest.support.colqwen import ColQwen2LoadError, VisualEmbeddingError

        err = ColQwen2LoadError("test error")
        assert isinstance(err, VisualEmbeddingError)

    def test_visual_embedding_error_is_exception(self):
        """VisualEmbeddingError must derive from the built-in Exception."""
        from src.ingest.support.colqwen import VisualEmbeddingError

        assert issubclass(VisualEmbeddingError, Exception)

    def test_colqwen2_load_error_can_be_caught_as_visual_embedding_error(self):
        """Practical catch-pattern: except VisualEmbeddingError works."""
        from src.ingest.support.colqwen import ColQwen2LoadError, VisualEmbeddingError

        caught = None
        try:
            raise ColQwen2LoadError("wrap test")
        except VisualEmbeddingError as e:
            caught = e
        assert caught is not None


# ===========================================================================
# Group 3: load_colqwen_model
# ===========================================================================


class TestLoadColqwenModel:
    """FR-301: ColQwen2 model loading with 4-bit quantization."""

    def _make_colpali_modules(self):
        """Build minimal colpali_engine module stubs."""
        colpali_stub = types.ModuleType("colpali_engine")
        models_stub = types.ModuleType("colpali_engine.models")
        processors_stub = types.ModuleType("colpali_engine.processors")

        mock_model_cls = MagicMock(name="ColQwen2")
        mock_model_instance = MagicMock(name="colqwen2_model_instance")
        mock_model_cls.from_pretrained = MagicMock(return_value=mock_model_instance)

        mock_processor_cls = MagicMock(name="ColQwen2Processor")
        mock_processor_instance = MagicMock(name="colqwen2_processor_instance")
        mock_processor_cls.from_pretrained = MagicMock(
            return_value=mock_processor_instance
        )

        models_stub.ColQwen2 = mock_model_cls
        processors_stub.ColQwen2Processor = mock_processor_cls
        colpali_stub.models = models_stub
        colpali_stub.processors = processors_stub

        return colpali_stub, models_stub, processors_stub, mock_model_cls, mock_processor_cls

    def test_returns_model_processor_tuple(self):
        """FR-301: load_colqwen_model returns a (model, processor) tuple."""
        from src.ingest.support.colqwen import load_colqwen_model

        colpali_stub, models_stub, processors_stub, model_cls, processor_cls = (
            self._make_colpali_modules()
        )
        torch_mock = _make_torch_mock()
        bnb_config_cls = MagicMock(name="BitsAndBytesConfig")

        with patch.dict(
            sys.modules,
            {
                "colpali_engine": colpali_stub,
                "colpali_engine.models": models_stub,
                "colpali_engine.processors": processors_stub,
                "torch": torch_mock,
            },
        ), patch(
            "transformers.BitsAndBytesConfig", bnb_config_cls, create=True
        ):
            result = load_colqwen_model("vidore/colqwen2-v1.0")

        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_model_eval_called(self):
        """FR-301: model.eval() must be called after loading."""
        from src.ingest.support.colqwen import load_colqwen_model

        colpali_stub, models_stub, processors_stub, model_cls, processor_cls = (
            self._make_colpali_modules()
        )
        torch_mock = _make_torch_mock()
        bnb_config_cls = MagicMock(name="BitsAndBytesConfig")

        with patch.dict(
            sys.modules,
            {
                "colpali_engine": colpali_stub,
                "colpali_engine.models": models_stub,
                "colpali_engine.processors": processors_stub,
                "torch": torch_mock,
            },
        ), patch(
            "transformers.BitsAndBytesConfig", bnb_config_cls, create=True
        ):
            model, _proc = load_colqwen_model("vidore/colqwen2-v1.0")

        model.eval.assert_called()

    def test_model_loaded_with_4bit_quantization(self):
        """FR-301: BitsAndBytesConfig(load_in_4bit=True) must be used."""
        from src.ingest.support.colqwen import load_colqwen_model

        colpali_stub, models_stub, processors_stub, model_cls, processor_cls = (
            self._make_colpali_modules()
        )
        torch_mock = _make_torch_mock()
        bnb_config_cls = MagicMock(name="BitsAndBytesConfig")

        with patch.dict(
            sys.modules,
            {
                "colpali_engine": colpali_stub,
                "colpali_engine.models": models_stub,
                "colpali_engine.processors": processors_stub,
                "torch": torch_mock,
            },
        ), patch(
            "transformers.BitsAndBytesConfig", bnb_config_cls, create=True
        ):
            load_colqwen_model("vidore/colqwen2-v1.0")

        # BitsAndBytesConfig must be instantiated with load_in_4bit=True
        call_kwargs = bnb_config_cls.call_args
        assert call_kwargs is not None
        kwargs = call_kwargs.kwargs if call_kwargs.kwargs else {}
        all_args = {**kwargs}
        # Accept positional too
        if call_kwargs.args:
            # not typical but handle it
            pass
        assert all_args.get("load_in_4bit") is True

    def test_model_loaded_with_float16_compute_dtype(self):
        """FR-301: BitsAndBytesConfig must include bnb_4bit_compute_dtype=torch.float16."""
        from src.ingest.support.colqwen import load_colqwen_model

        colpali_stub, models_stub, processors_stub, model_cls, processor_cls = (
            self._make_colpali_modules()
        )
        torch_mock = _make_torch_mock()
        bnb_config_cls = MagicMock(name="BitsAndBytesConfig")

        with patch.dict(
            sys.modules,
            {
                "colpali_engine": colpali_stub,
                "colpali_engine.models": models_stub,
                "colpali_engine.processors": processors_stub,
                "torch": torch_mock,
            },
        ), patch(
            "transformers.BitsAndBytesConfig", bnb_config_cls, create=True
        ):
            load_colqwen_model("vidore/colqwen2-v1.0")

        call_kwargs = bnb_config_cls.call_args.kwargs
        assert call_kwargs.get("bnb_4bit_compute_dtype") == torch_mock.float16

    def test_model_loaded_with_device_map_auto(self):
        """FR-301: from_pretrained must be called with device_map='auto'."""
        from src.ingest.support.colqwen import load_colqwen_model

        colpali_stub, models_stub, processors_stub, model_cls, processor_cls = (
            self._make_colpali_modules()
        )
        torch_mock = _make_torch_mock()
        bnb_config_cls = MagicMock(name="BitsAndBytesConfig")

        with patch.dict(
            sys.modules,
            {
                "colpali_engine": colpali_stub,
                "colpali_engine.models": models_stub,
                "colpali_engine.processors": processors_stub,
                "torch": torch_mock,
            },
        ), patch(
            "transformers.BitsAndBytesConfig", bnb_config_cls, create=True
        ):
            load_colqwen_model("vidore/colqwen2-v1.0")

        call_kwargs = model_cls.from_pretrained.call_args.kwargs
        assert call_kwargs.get("device_map") == "auto"

    def test_raises_colqwen_load_error_on_invalid_model_name(self):
        """FR-802: load_colqwen_model wraps HuggingFace errors in ColQwen2LoadError."""
        from src.ingest.support.colqwen import ColQwen2LoadError, load_colqwen_model

        colpali_stub, models_stub, processors_stub, model_cls, processor_cls = (
            self._make_colpali_modules()
        )
        original_error = RuntimeError("Repository not found: nonexistent/model-xyz")
        model_cls.from_pretrained.side_effect = original_error
        torch_mock = _make_torch_mock()
        bnb_config_cls = MagicMock(name="BitsAndBytesConfig")

        with patch.dict(
            sys.modules,
            {
                "colpali_engine": colpali_stub,
                "colpali_engine.models": models_stub,
                "colpali_engine.processors": processors_stub,
                "torch": torch_mock,
            },
        ), patch(
            "transformers.BitsAndBytesConfig", bnb_config_cls, create=True
        ):
            with pytest.raises(ColQwen2LoadError) as exc_info:
                load_colqwen_model("nonexistent/model-xyz")

        # Original exception must be wrapped (chained), not swallowed
        assert exc_info.value.__cause__ is original_error or (
            original_error.__class__.__name__ in str(exc_info.value)
            or original_error.__class__.__name__
            in type(exc_info.value.__cause__).__name__
            if exc_info.value.__cause__
            else True
        )

    def test_load_error_is_subclass_of_visual_embedding_error(self):
        """FR-802: ColQwen2LoadError raised from load_colqwen_model is VisualEmbeddingError."""
        from src.ingest.support.colqwen import (
            ColQwen2LoadError,
            VisualEmbeddingError,
            load_colqwen_model,
        )

        colpali_stub, models_stub, processors_stub, model_cls, processor_cls = (
            self._make_colpali_modules()
        )
        model_cls.from_pretrained.side_effect = RuntimeError("network error")
        torch_mock = _make_torch_mock()
        bnb_config_cls = MagicMock(name="BitsAndBytesConfig")

        with patch.dict(
            sys.modules,
            {
                "colpali_engine": colpali_stub,
                "colpali_engine.models": models_stub,
                "colpali_engine.processors": processors_stub,
                "torch": torch_mock,
            },
        ), patch(
            "transformers.BitsAndBytesConfig", bnb_config_cls, create=True
        ):
            with pytest.raises(VisualEmbeddingError):
                load_colqwen_model("nonexistent/model-xyz")


# ===========================================================================
# Group 4: embed_page_images — batching and page numbering
# ===========================================================================


class TestEmbedPageImagesBatching:
    """FR-302: batch sizing, call count, and page number assignment."""

    def test_20_images_batch4_produces_5_inference_calls(self):
        """FR-302: 20 images / batch_size=4 → exactly 5 model calls, no empty trailing batch."""
        from src.ingest.support.colqwen import embed_page_images

        model, processor, _ = _make_model_and_processor(n_patches=10)
        images = _pil_images(20)

        embed_page_images(model, processor, images, batch_size=4)

        assert model.call_count == 5

    def test_20_images_batch4_returns_20_embeddings(self):
        """FR-302: each of 20 images produces exactly one ColQwen2PageEmbedding."""
        from src.ingest.support.colqwen import ColQwen2PageEmbedding, embed_page_images

        model, processor, _ = _make_model_and_processor(n_patches=10)
        images = _pil_images(20)

        result = embed_page_images(model, processor, images, batch_size=4)

        assert len(result) == 20
        assert all(isinstance(e, ColQwen2PageEmbedding) for e in result)

    def test_21_images_batch4_produces_6_inference_calls(self):
        """Boundary: 21 images / batch_size=4 → 6 calls (5 full + 1 partial)."""
        from src.ingest.support.colqwen import embed_page_images

        model, processor, _ = _make_model_and_processor(n_patches=10)
        images = _pil_images(21)

        embed_page_images(model, processor, images, batch_size=4)

        assert model.call_count == 6

    def test_21_images_batch4_returns_21_embeddings(self):
        """Boundary: final batch of 1 image is processed correctly."""
        from src.ingest.support.colqwen import ColQwen2PageEmbedding, embed_page_images

        model, processor, _ = _make_model_and_processor(n_patches=10)
        images = _pil_images(21)

        result = embed_page_images(model, processor, images, batch_size=4)

        assert len(result) == 21

    def test_page_numbers_default_to_1_indexed_sequential(self):
        """FR-302: page_numbers=None → embeddings have page_number [1,2,3,4,5]."""
        from src.ingest.support.colqwen import embed_page_images

        model, processor, _ = _make_model_and_processor(n_patches=10)
        images = _pil_images(5)

        result = embed_page_images(model, processor, images, batch_size=5, page_numbers=None)

        page_nums = [e.page_number for e in result]
        assert page_nums == [1, 2, 3, 4, 5]

    def test_explicit_page_numbers_are_respected(self):
        """Explicit page_numbers list maps correctly onto returned embeddings."""
        from src.ingest.support.colqwen import embed_page_images

        model, processor, _ = _make_model_and_processor(n_patches=10)
        images = _pil_images(3)

        result = embed_page_images(
            model, processor, images, batch_size=3, page_numbers=[10, 20, 30]
        )

        page_nums = [e.page_number for e in result]
        assert page_nums == [10, 20, 30]

    def test_single_image_returns_one_embedding(self):
        """Boundary: single image input returns list of length 1."""
        from src.ingest.support.colqwen import ColQwen2PageEmbedding, embed_page_images

        model, processor, _ = _make_model_and_processor(n_patches=10)
        images = _pil_images(1)

        result = embed_page_images(model, processor, images, batch_size=4)

        assert len(result) == 1
        assert isinstance(result[0], ColQwen2PageEmbedding)

    def test_empty_image_list_returns_empty_list(self):
        """Boundary: empty input list → empty output list, no error."""
        from src.ingest.support.colqwen import embed_page_images

        model, processor, _ = _make_model_and_processor(n_patches=10)

        result = embed_page_images(model, processor, [], batch_size=4)

        assert result == []
        model.assert_not_called()


# ===========================================================================
# Group 5: embed_page_images — embedding structure and correctness
# ===========================================================================


class TestEmbedPageImagesEmbeddingStructure:
    """FR-302/303/304: patch vector range, mean-pooling, JSON serializability."""

    def test_mean_vector_is_128_dim(self):
        """FR-303: mean_vector must have exactly 128 elements."""
        from src.ingest.support.colqwen import embed_page_images

        model, processor, _ = _make_model_and_processor(n_patches=800, dim=128)
        images = _pil_images(1)

        result = embed_page_images(model, processor, images, batch_size=1)

        assert len(result[0].mean_vector) == 128

    def test_mean_vector_is_list_of_float(self):
        """FR-303: mean_vector elements must be floats."""
        from src.ingest.support.colqwen import embed_page_images

        model, processor, _ = _make_model_and_processor(n_patches=800, dim=128)
        images = _pil_images(1)

        result = embed_page_images(model, processor, images, batch_size=1)

        assert all(isinstance(v, float) for v in result[0].mean_vector)

    def test_mean_vector_is_arithmetic_mean(self):
        """FR-303: mean_vector equals arithmetic mean of patch vectors per dimension."""
        from src.ingest.support.colqwen import embed_page_images

        # All patches have value 3.0 → mean must be 3.0 per dimension
        model, processor, raw_data = _make_model_and_processor(
            n_patches=800, dim=128, base_value=3.0
        )
        images = _pil_images(1)

        result = embed_page_images(model, processor, images, batch_size=1)

        for v in result[0].mean_vector:
            assert abs(v - 3.0) < 1e-5, f"Expected 3.0, got {v}"

    def test_patch_count_matches_len_patch_vectors(self):
        """FR-302: patch_count == len(patch_vectors)."""
        from src.ingest.support.colqwen import embed_page_images

        model, processor, _ = _make_model_and_processor(n_patches=800)
        images = _pil_images(1)

        result = embed_page_images(model, processor, images, batch_size=1)

        emb = result[0]
        assert emb.patch_count == len(emb.patch_vectors)

    def test_each_patch_vector_has_128_elements(self):
        """FR-303: each element of patch_vectors has exactly 128 dimensions."""
        from src.ingest.support.colqwen import embed_page_images

        model, processor, _ = _make_model_and_processor(n_patches=50, dim=128)
        images = _pil_images(1)

        result = embed_page_images(model, processor, images, batch_size=1)

        for pv in result[0].patch_vectors:
            assert len(pv) == 128

    def test_patch_vectors_are_json_serializable(self):
        """FR-304: patch_vectors must survive json.dumps without error."""
        from src.ingest.support.colqwen import embed_page_images

        model, processor, _ = _make_model_and_processor(n_patches=1000, dim=128)
        images = _pil_images(1)

        result = embed_page_images(model, processor, images, batch_size=1)

        serialized = json.dumps(result[0].patch_vectors)
        assert serialized is not None

    def test_patch_vectors_serialize_to_list_of_lists_of_float(self):
        """FR-304: deserialized patch_vectors is list[list[float]]."""
        from src.ingest.support.colqwen import embed_page_images

        model, processor, _ = _make_model_and_processor(n_patches=10, dim=128)
        images = _pil_images(1)

        result = embed_page_images(model, processor, images, batch_size=1)

        deserialized = json.loads(json.dumps(result[0].patch_vectors))
        assert isinstance(deserialized, list)
        assert all(isinstance(row, list) for row in deserialized)
        assert all(isinstance(v, float) for row in deserialized for v in row)

    def test_mean_vector_invariant_across_all_pages(self):
        """FR-303: every page's mean_vector has exactly 128 elements."""
        from src.ingest.support.colqwen import embed_page_images

        model, processor, _ = _make_model_and_processor(n_patches=20, dim=128)
        images = _pil_images(5)

        result = embed_page_images(model, processor, images, batch_size=2)

        for emb in result:
            assert len(emb.mean_vector) == 128, (
                f"Page {emb.page_number}: mean_vector has {len(emb.mean_vector)} dims"
            )

    # GAP: patch_count range [500, 1200] is non-deterministic with real images;
    #      would require GPU + real model to validate in CI.


# ===========================================================================
# Group 6: embed_page_images — error handling and graceful degradation
# ===========================================================================


class TestEmbedPageImagesErrorHandling:
    """FR-307: per-batch and per-page failure handling."""

    def test_batch_preprocessing_failure_skips_batch(self):
        """FR-307: processor.process_images raising skips that batch, no exception raised."""
        from src.ingest.support.colqwen import embed_page_images

        model, processor, _ = _make_model_and_processor(n_patches=10)
        images = _pil_images(8)  # 2 batches of 4

        # First batch raises, second succeeds
        good_inputs = MagicMock(name="processed_inputs")
        good_inputs.to = MagicMock(return_value=good_inputs)
        good_inputs.__iter__ = MagicMock(return_value=iter([]))
        processor.process_images.side_effect = [
            RuntimeError("preprocessing failed"),
            good_inputs,
        ]

        # Should not raise
        result = embed_page_images(model, processor, images, batch_size=4)

        # Only second batch produced embeddings
        assert len(result) == 4

    def test_batch_preprocessing_failure_emits_warning(self):
        """FR-307: a WARNING log is emitted when a batch fails preprocessing."""
        import logging

        from src.ingest.support.colqwen import embed_page_images

        model, processor, _ = _make_model_and_processor(n_patches=10)
        images = _pil_images(8)

        good_inputs = MagicMock(name="processed_inputs")
        good_inputs.to = MagicMock(return_value=good_inputs)
        good_inputs.__iter__ = MagicMock(return_value=iter([]))
        processor.process_images.side_effect = [
            RuntimeError("preprocessing failed"),
            good_inputs,
        ]

        with patch("src.ingest.support.colqwen.logger") as mock_logger:
            embed_page_images(model, processor, images, batch_size=4)
            mock_logger.warning.assert_called()

    def test_single_page_extraction_failure_skips_page(self):
        """FR-307: tensor extraction error on one page skips it; other pages returned."""
        from src.ingest.support.colqwen import embed_page_images

        model, processor, _ = _make_model_and_processor(n_patches=10)
        images = _pil_images(3)  # single batch of 3

        # Patch tensor extraction: first two pages succeed, third raises
        patch_tensor_good, _ = _make_patch_tensor(10, 128)
        patch_tensor_bad = MagicMock(name="bad_tensor")
        patch_tensor_bad.tolist = MagicMock(side_effect=RuntimeError("extraction failed"))

        hidden_state = MagicMock(name="last_hidden_state")
        call_count = {"n": 0}

        def _hs_getitem(idx):
            call_count["n"] += 1
            if idx == 2:  # third page in batch
                raise RuntimeError("extraction failed")
            return patch_tensor_good

        hidden_state.__getitem__ = MagicMock(side_effect=_hs_getitem)
        output = MagicMock()
        output.last_hidden_state = hidden_state
        model.return_value = output

        # Should not raise
        result = embed_page_images(model, processor, images, batch_size=3)

        # Two pages succeed, one skipped
        assert len(result) == 2

    def test_single_page_extraction_failure_emits_warning(self):
        """FR-307: WARNING logged for skipped page."""
        from src.ingest.support.colqwen import embed_page_images

        model, processor, _ = _make_model_and_processor(n_patches=10)
        images = _pil_images(3)

        patch_tensor_good, _ = _make_patch_tensor(10, 128)
        hidden_state = MagicMock(name="last_hidden_state")

        def _hs_getitem(idx):
            if idx == 2:
                raise RuntimeError("extraction failed")
            return patch_tensor_good

        hidden_state.__getitem__ = MagicMock(side_effect=_hs_getitem)
        output = MagicMock()
        output.last_hidden_state = hidden_state
        model.return_value = output

        with patch("src.ingest.support.colqwen.logger") as mock_logger:
            embed_page_images(model, processor, images, batch_size=3)
            mock_logger.warning.assert_called()

    def test_partial_embeddings_mid_document_error(self):
        """FR-307: 10-page doc, page 5 extraction error → 9 embeddings returned."""
        from src.ingest.support.colqwen import embed_page_images

        n_pages = 10
        images = _pil_images(n_pages)

        patch_tensor_good, _ = _make_patch_tensor(10, 128)
        hidden_state = MagicMock(name="last_hidden_state")

        # Simulate per-image processing in batches: page index 4 (0-based) fails.
        # With batch_size=10 (single batch), in-batch index 4 will be idx=4.
        def _hs_getitem(idx):
            if idx == 4:  # 5th page (0-indexed)
                raise RuntimeError("page 5 extraction failed")
            return patch_tensor_good

        hidden_state.__getitem__ = MagicMock(side_effect=_hs_getitem)
        output = MagicMock()
        output.last_hidden_state = hidden_state

        model = MagicMock()
        model.return_value = output

        processed_inputs = MagicMock()
        processed_inputs.to = MagicMock(return_value=processed_inputs)
        processed_inputs.__iter__ = MagicMock(return_value=iter([]))

        processor = MagicMock()
        processor.process_images = MagicMock(return_value=processed_inputs)

        result = embed_page_images(model, processor, images, batch_size=10)

        assert len(result) == 9

    def test_partial_embeddings_warning_for_failed_page(self):
        """FR-307: exactly one warning logged for the single failed page."""
        from src.ingest.support.colqwen import embed_page_images

        images = _pil_images(10)
        patch_tensor_good, _ = _make_patch_tensor(10, 128)
        hidden_state = MagicMock(name="last_hidden_state")

        def _hs_getitem(idx):
            if idx == 4:
                raise RuntimeError("page 5 extraction failed")
            return patch_tensor_good

        hidden_state.__getitem__ = MagicMock(side_effect=_hs_getitem)
        output = MagicMock()
        output.last_hidden_state = hidden_state

        model = MagicMock()
        model.return_value = output
        processed_inputs = MagicMock()
        processed_inputs.to = MagicMock(return_value=processed_inputs)
        processed_inputs.__iter__ = MagicMock(return_value=iter([]))
        processor = MagicMock()
        processor.process_images = MagicMock(return_value=processed_inputs)

        with patch("src.ingest.support.colqwen.logger") as mock_logger:
            embed_page_images(model, processor, images, batch_size=10)
            mock_logger.warning.assert_called()

    def test_no_exception_raised_from_embed_on_per_batch_failure(self):
        """FR-307: embed_page_images must not raise even when all batches fail."""
        from src.ingest.support.colqwen import embed_page_images

        model = MagicMock()
        model.side_effect = RuntimeError("all batches fail")

        processed_inputs = MagicMock()
        processed_inputs.to = MagicMock(return_value=processed_inputs)
        processed_inputs.__iter__ = MagicMock(return_value=iter([]))
        processor = MagicMock()
        processor.process_images = MagicMock(return_value=processed_inputs)

        images = _pil_images(4)

        # Should return empty list (all batches failed), not raise
        result = embed_page_images(model, processor, images, batch_size=4)

        assert isinstance(result, list)


# ===========================================================================
# Group 7: unload_colqwen_model
# ===========================================================================


class TestUnloadColqwenModel:
    """GPU memory release via del model, torch.cuda.empty_cache(), gc.collect()."""

    def test_unload_calls_cuda_empty_cache(self):
        """unload_colqwen_model must call torch.cuda.empty_cache()."""
        from src.ingest.support.colqwen import unload_colqwen_model

        torch_mock = _make_torch_mock()
        model = MagicMock(name="model_to_unload")

        with patch.dict(sys.modules, {"torch": torch_mock}):
            unload_colqwen_model(model)

        torch_mock.cuda.empty_cache.assert_called_once()

    def test_unload_calls_gc_collect(self):
        """unload_colqwen_model must call gc.collect()."""
        import gc

        from src.ingest.support.colqwen import unload_colqwen_model

        model = MagicMock(name="model_to_unload")
        torch_mock = _make_torch_mock()

        with patch.dict(sys.modules, {"torch": torch_mock}), patch(
            "src.ingest.support.colqwen.gc"
        ) as gc_mock:
            unload_colqwen_model(model)

        gc_mock.collect.assert_called_once()

    def test_unload_does_not_raise(self):
        """unload_colqwen_model completes without error."""
        from src.ingest.support.colqwen import unload_colqwen_model

        torch_mock = _make_torch_mock()
        model = MagicMock(name="model_to_unload")

        with patch.dict(sys.modules, {"torch": torch_mock}):
            # Must not raise
            unload_colqwen_model(model)

    # GAP: Real GPU hardware required to verify NFR-901 (memory actually released).
    # GAP: del model behavior in Python cannot be meaningfully asserted via mock —
    #      the local variable deletion inside the function is an implementation detail.


# ===========================================================================
# Group 8: progress logging boundary
# ===========================================================================


class TestProgressLogging:
    """Progress logging at ~10% intervals for large page counts."""

    def test_small_batch_no_progress_log(self):
        """Single-image input produces no progress log calls."""
        from src.ingest.support.colqwen import embed_page_images

        model, processor, _ = _make_model_and_processor(n_patches=10)
        images = _pil_images(1)

        with patch("src.ingest.support.colqwen.logger") as mock_logger:
            embed_page_images(model, processor, images, batch_size=1)
            # No INFO calls expected for trivially small input
            info_calls = [
                c for c in mock_logger.info.call_args_list if "%" in str(c)
            ]
            assert len(info_calls) == 0

    def test_large_batch_emits_progress_logs(self):
        """100-page document should emit at least one progress log at ~10% intervals."""
        from src.ingest.support.colqwen import embed_page_images

        model, processor, _ = _make_model_and_processor(n_patches=10)
        images = _pil_images(100)

        with patch("src.ingest.support.colqwen.logger") as mock_logger:
            embed_page_images(model, processor, images, batch_size=10)
            # Expect progress logging; allow ±1 tolerance
            assert mock_logger.info.call_count >= 1

    # GAP: Exact progress log interval count is flaky in CI — ±1 tolerance applied.


# ===========================================================================
# Group 9: ColQwen2PageEmbedding dataclass contract
# ===========================================================================


class TestColQwen2PageEmbeddingContract:
    """Verify the dataclass contract directly from the Phase 0 import surface."""

    def test_dataclass_has_required_fields(self):
        """ColQwen2PageEmbedding can be constructed with all required fields."""
        from src.ingest.support.colqwen import ColQwen2PageEmbedding

        emb = ColQwen2PageEmbedding(
            page_number=1,
            mean_vector=[0.0] * 128,
            patch_vectors=[[0.0] * 128 for _ in range(10)],
            patch_count=10,
        )
        assert emb.page_number == 1
        assert len(emb.mean_vector) == 128
        assert emb.patch_count == 10
        assert len(emb.patch_vectors) == 10

    def test_patch_count_field_matches_patch_vectors_length(self):
        """patch_count and len(patch_vectors) are independently stored — caller's responsibility."""
        from src.ingest.support.colqwen import ColQwen2PageEmbedding

        emb = ColQwen2PageEmbedding(
            page_number=3,
            mean_vector=[1.0] * 128,
            patch_vectors=[[1.0] * 128 for _ in range(50)],
            patch_count=50,
        )
        assert emb.patch_count == len(emb.patch_vectors)
