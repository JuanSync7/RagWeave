# @summary
# Local BAAI bge-reranker-v2-m3 wrapper for reranking search results.
# Key exports: LocalBGEReranker, RankedResult
# Deps: transformers, dataclasses, torch, AutoModelForSequenceClassification, AutoTokenizer, config.settings
# @end-summary
"""Local BAAI bge-reranker-v2-m3 wrapper for reranking search results.

Uses transformers directly instead of FlagEmbedding to avoid compatibility
issues with transformers >= 5.x.
"""

from typing import List

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from config.settings import RERANKER_MODEL_PATH, RERANK_TOP_K
from src.platform.observability.providers import get_tracer
from src.retrieval.schemas import RankedResult


class LocalBGEReranker:
    """Reranker using a local BAAI/bge-reranker-v2-m3 model."""

    def __init__(self, model_path: str = RERANKER_MODEL_PATH):
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.tokenizer = AutoTokenizer.from_pretrained(model_path)
        self.model = AutoModelForSequenceClassification.from_pretrained(
            model_path, device_map=self.device,
        )
        self.model.eval()
        self.tracer = get_tracer()

    @torch.no_grad()
    def rerank(
        self,
        query: str,
        documents: List[dict],
        top_k: int = RERANK_TOP_K,
    ) -> List[RankedResult]:
        """Rerank documents against a query.

        Args:
            query: The search query.
            documents: List of dicts with 'text' and 'metadata' keys.
            top_k: Number of top results to return.

        Returns:
            Sorted list of RankedResult (highest score first).
        """
        span = self.tracer.start_span(
            "reranker.rerank",
            {"input_count": len(documents), "top_k": top_k},
        )
        if not documents:
            span.end(status="ok")
            return []

        pairs = [[query, doc["text"]] for doc in documents]

        inputs = self.tokenizer(
            pairs,
            padding=True,
            truncation=True,
            max_length=512,
            return_tensors="pt",
        ).to(self.device)

        scores = self.model(**inputs).logits.squeeze(-1).float().cpu().tolist()

        # If single document, scores is a scalar
        if isinstance(scores, float):
            scores = [scores]

        # Normalize scores to 0-1 via sigmoid
        scores = [1 / (1 + torch.exp(torch.tensor(-s)).item()) for s in scores]

        results = [
            RankedResult(
                text=doc["text"],
                score=score,
                metadata=doc.get("metadata", {}),
            )
            for doc, score in zip(documents, scores)
        ]

        results.sort(key=lambda r: r.score, reverse=True)
        top_results = results[:top_k]
        if top_results:
            values = [r.score for r in top_results]
            span.set_attribute("score_min", min(values))
            span.set_attribute("score_max", max(values))
        span.end(status="ok")
        return top_results


__all__ = ["LocalBGEReranker", "RankedResult"]
