# @summary
# Local embedding wrapper for BAAI/bge-m3 model compatible with LangChain.
# Exports: LocalBGEEmbeddings
# Deps: sentence-transformers, numpy, langchain_core, config.settings
# @end-summary
"""Local BAAI bge-m3 embedding wrapper compatible with LangChain."""

from typing import List

import numpy as np
from langchain_core.embeddings import Embeddings
from sentence_transformers import SentenceTransformer

from config.settings import EMBEDDING_MODEL_PATH
from src.platform.observability import get_tracer


class LocalBGEEmbeddings(Embeddings):
    """LangChain-compatible embeddings using a local BAAI/bge-m3 model."""

    def __init__(self, model_path: str = EMBEDDING_MODEL_PATH):
        self.model = SentenceTransformer(model_path)
        self.tracer = get_tracer()

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
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

    def embed_query(self, text: str) -> List[float]:
        """Embed a single query text."""
        span = self.tracer.start_span("embeddings.embed_query", {"text_len": len(text)})
        embedding = self.model.encode(
            text,
            normalize_embeddings=True,
        )
        span.end(status="ok")
        return embedding.tolist()

    def encode_sentences(self, sentences: List[str]) -> np.ndarray:
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
