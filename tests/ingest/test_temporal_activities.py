"""Tests for src.ingest.temporal.activities helper functions.

Covers prewarm_worker_resources, _deserialise_config, _get_embedder, _get_db_client
without requiring a live Temporal runtime.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Lazy import helpers — avoid importing temporalio at collection time
# ---------------------------------------------------------------------------


def _import_activities():
    """Import the activities module lazily to avoid top-level Temporal load."""
    import src.ingest.temporal.activities as acts
    return acts


# ---------------------------------------------------------------------------
# Tests: prewarm_worker_resources
# ---------------------------------------------------------------------------


class TestPrewarmWorkerResources:
    def test_mock_prewarm_success(self, monkeypatch):
        """prewarm_worker_resources should set _embedder and _db_client singletons."""
        acts = _import_activities()

        fake_embedder = MagicMock()
        fake_db_client = MagicMock()

        monkeypatch.setattr("src.ingest.temporal.activities._embedder", None)
        monkeypatch.setattr("src.ingest.temporal.activities._db_client", None)
        monkeypatch.setattr("src.ingest.temporal.activities.get_embedding_provider", lambda: fake_embedder)
        monkeypatch.setattr("src.ingest.temporal.activities.db.create_persistent_client", lambda: fake_db_client)
        monkeypatch.setattr("src.ingest.temporal.activities.RAG_INGESTION_DOCLING_ENABLED", False)

        acts.prewarm_worker_resources()

        assert acts._embedder is fake_embedder
        assert acts._db_client is fake_db_client

    def test_mock_prewarm_docling_disabled(self, monkeypatch, caplog):
        """prewarm should skip docling warmup when RAG_INGESTION_DOCLING_ENABLED=False."""
        acts = _import_activities()

        monkeypatch.setattr("src.ingest.temporal.activities.get_embedding_provider", lambda: MagicMock())
        monkeypatch.setattr("src.ingest.temporal.activities.db.create_persistent_client", lambda: MagicMock())
        monkeypatch.setattr("src.ingest.temporal.activities.RAG_INGESTION_DOCLING_ENABLED", False)

        ensure_called = []
        monkeypatch.setattr(
            "src.ingest.temporal.activities.ensure_docling_ready",
            lambda **kw: ensure_called.append(True),
        )

        with caplog.at_level(logging.INFO):
            acts.prewarm_worker_resources()

        # ensure_docling_ready should NOT have been called
        assert len(ensure_called) == 0

    def test_mock_prewarm_runtime_error(self, monkeypatch, caplog):
        """prewarm should log warning when docling setup raises RuntimeError."""
        acts = _import_activities()

        monkeypatch.setattr("src.ingest.temporal.activities.get_embedding_provider", lambda: MagicMock())
        monkeypatch.setattr("src.ingest.temporal.activities.db.create_persistent_client", lambda: MagicMock())
        monkeypatch.setattr("src.ingest.temporal.activities.RAG_INGESTION_DOCLING_ENABLED", True)
        monkeypatch.setattr(
            "src.ingest.temporal.activities.ensure_docling_ready",
            lambda **kw: (_ for _ in ()).throw(RuntimeError("model not found")),
        )

        with caplog.at_level(logging.WARNING):
            acts.prewarm_worker_resources()  # should NOT raise

        assert any("Docling" in r.message or "model" in r.message.lower() for r in caplog.records)


# ---------------------------------------------------------------------------
# Tests: _deserialise_config
# ---------------------------------------------------------------------------


class TestDeserialiseConfig:
    def test_mock_deserialise_config(self):
        """_deserialise_config should reconstruct IngestionConfig from a dict."""
        acts = _import_activities()
        from src.ingest.common import IngestionConfig
        import dataclasses

        original = IngestionConfig()
        config_dict = dataclasses.asdict(original)

        result = acts._deserialise_config(config_dict)

        assert isinstance(result, IngestionConfig)
        assert result.verbose_stage_logs == original.verbose_stage_logs

    def test_mock_deserialise_config_extra_keys_ignored(self):
        """_deserialise_config should ignore extra keys not in IngestionConfig."""
        acts = _import_activities()
        from src.ingest.common import IngestionConfig
        import dataclasses

        config_dict = dataclasses.asdict(IngestionConfig())
        config_dict["unknown_future_field"] = "value"

        result = acts._deserialise_config(config_dict)
        assert isinstance(result, IngestionConfig)


# ---------------------------------------------------------------------------
# Tests: _get_embedder and _get_db_client lazy init
# ---------------------------------------------------------------------------


class TestLazyInit:
    def test_mock_get_embedder_lazy_init(self, monkeypatch):
        """_get_embedder should initialise singleton on first call if None."""
        acts = _import_activities()

        fake_embedder = MagicMock()
        monkeypatch.setattr("src.ingest.temporal.activities._embedder", None)
        monkeypatch.setattr("src.ingest.temporal.activities.get_embedding_provider", lambda: fake_embedder)

        result = acts._get_embedder()
        assert result is fake_embedder
        assert acts._embedder is fake_embedder

    def test_mock_get_embedder_returns_existing(self, monkeypatch):
        """_get_embedder should return existing singleton without re-initialising."""
        acts = _import_activities()

        existing = MagicMock()
        monkeypatch.setattr("src.ingest.temporal.activities._embedder", existing)

        called = []
        monkeypatch.setattr(
            "src.ingest.temporal.activities.get_embedding_provider",
            lambda: called.append(True) or MagicMock(),
        )

        result = acts._get_embedder()
        assert result is existing
        assert len(called) == 0  # not called again

    def test_mock_get_db_client_lazy_init(self, monkeypatch):
        """_get_db_client should initialise singleton on first call if None."""
        acts = _import_activities()

        fake_client = MagicMock()
        monkeypatch.setattr("src.ingest.temporal.activities._db_client", None)
        monkeypatch.setattr("src.ingest.temporal.activities.db.create_persistent_client", lambda: fake_client)

        result = acts._get_db_client()
        assert result is fake_client
        assert acts._db_client is fake_client

    def test_mock_get_db_client_returns_existing(self, monkeypatch):
        """_get_db_client should return existing singleton without re-creating."""
        acts = _import_activities()

        existing = MagicMock()
        monkeypatch.setattr("src.ingest.temporal.activities._db_client", existing)

        called = []
        monkeypatch.setattr(
            "src.ingest.temporal.activities.db.create_persistent_client",
            lambda: called.append(True) or MagicMock(),
        )

        result = acts._get_db_client()
        assert result is existing
        assert len(called) == 0
