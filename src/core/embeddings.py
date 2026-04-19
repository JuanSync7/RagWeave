# @summary
# Embedding providers: local BAAI/bge-m3 (in-process) and LiteLLM-backed vLLM.
# Exports: LocalBGEEmbeddings, LiteLLMEmbeddings, get_embedding_provider
# Deps: sentence-transformers (local path only), litellm, numpy, langchain_core, config.settings
# @end-summary
"""Embedding provider implementations and factory.

Two backends:
  local  — BAAI/bge-m3 loaded in-process via sentence-transformers (default)
  vllm   — Qwen3-Embedding served by a separate vLLM container via LiteLLM
"""
from __future__ import annotations


import numpy as np
from langchain_core.embeddings import Embeddings

from config.settings import EMBEDDING_MODEL_PATH, INFERENCE_BACKEND, VLLM_TIMEOUT_SECONDS
from src.platform.observability import get_tracer


def _load_sentence_transformer(model_path: str):
    """Lazy import so the worker image can run without sentence-transformers when using vLLM."""
    from sentence_transformers import SentenceTransformer  # noqa: PLC0415
    return SentenceTransformer(model_path)


class LocalBGEEmbeddings(Embeddings):
    """LangChain-compatible embeddings using a local BAAI/bge-m3 model."""

    def __init__(self, model_path: str = EMBEDDING_MODEL_PATH):
        self.model = _load_sentence_transformer(model_path)
        self.tracer = get_tracer()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a list of document texts."""
        span = self.tracer.start_span("embeddings.embed_documents", {"batch_size": len(texts)})
        embeddings = self.model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=True,
            batch_size=32,
        )
        span.end(status="ok")
        return embeddings.tolist()

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query text."""
        span = self.tracer.start_span("embeddings.embed_query", {"text_len": len(text)})
        embedding = self.model.encode(
            text,
            normalize_embeddings=True,
        )
        span.end(status="ok")
        return embedding.tolist()

    def encode_sentences(self, sentences: list[str]) -> np.ndarray:
        """Encode sentences returning numpy array for internal use.

        Used by semantic chunking for cosine similarity computation.
        Returns L2-normalized embeddings so cosine sim = dot product.
        """
        return self.model.encode(
            sentences,
            normalize_embeddings=True,
            batch_size=64,
            show_progress_bar=False,
        )


class LiteLLMEmbeddings(Embeddings):
    """LangChain-compatible embedding provider backed by litellm.embedding().

    Routes to any OpenAI-compatible /v1/embeddings endpoint (e.g., a vLLM
    container).  The ``model`` name is resolved by the LiteLLM router config
    (``RAG_LLM_ROUTER_CONFIG``) to the actual backend URL.
    """

    def __init__(self, model: str = "embedding", timeout: int = VLLM_TIMEOUT_SECONDS) -> None:
        self.model = model
        self.timeout = timeout
        self.tracer = get_tracer()

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of documents via LiteLLM."""
        import litellm  # noqa: PLC0415 — deferred so API container never imports it

        span = self.tracer.start_span("embeddings.embed_documents", {"batch_size": len(texts)})
        resp = litellm.embedding(model=self.model, input=texts, timeout=self.timeout)
        span.end(status="ok")
        return [d["embedding"] for d in resp.data]

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query text via LiteLLM."""
        return self.embed_documents([text])[0]

    def encode_sentences(self, sentences: list[str]) -> np.ndarray:
        """Return L2-normalized embeddings as a numpy array for semantic chunking.

        Callers compute cosine similarity as a raw dot product, which requires
        unit-norm vectors.  vLLM's /v1/embeddings endpoint does not normalize
        by default, so we do it here to match the contract of LocalBGEEmbeddings.
        """
        vecs = np.array(self.embed_documents(sentences))
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        norms = np.where(norms == 0, 1.0, norms)
        return vecs / norms


def get_embedding_provider() -> Embeddings:
    """Return the configured embedding provider.

    Reads ``INFERENCE_BACKEND`` from settings:
      - ``"vllm"``  → :class:`LiteLLMEmbeddings` (routes via LiteLLM to vLLM)
      - anything else → :class:`LocalBGEEmbeddings` (in-process sentence-transformers)
    """
    if INFERENCE_BACKEND == "vllm":
        return LiteLLMEmbeddings(timeout=VLLM_TIMEOUT_SECONDS)
    return LocalBGEEmbeddings()
