# @summary
# Local BAAI bge-reranker-v2-m3 wrapper for reranking search results.
# Key exports: LocalBGEReranker, RankedResult
# Deps: transformers, torch, config.settings (RERANKER_MODEL_PATH, RERANK_TOP_K,
#       RERANKER_MAX_LENGTH, RERANKER_BATCH_SIZE), src.vector_db.common.schemas,
#       src.retrieval.common.schemas, src.retrieval.common.exceptions
# @end-summary
"""Local BAAI bge-reranker-v2-m3 wrapper for reranking search results.

Uses transformers directly instead of FlagEmbedding to avoid compatibility
issues with transformers >= 5.x.
"""

from typing import List

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from config.settings import RERANKER_MODEL_PATH, RERANK_TOP_K, RERANKER_MAX_LENGTH, RERANKER_BATCH_SIZE
from src.platform.observability.providers import get_tracer
from src.vector_db.common.schemas import SearchResult
from src.retrieval.common.schemas import RankedResult
from src.retrieval.common.exceptions import ModelLoadError


class LocalBGEReranker:
    """Reranker using a local BAAI/bge-reranker-v2-m3 model.

    Attributes:
        device: Compute device string ("cuda" or "cpu").
        tokenizer: Loaded AutoTokenizer for the reranker model.
        model: Loaded AutoModelForSequenceClassification.
        tracer: Observability tracer for span instrumentation.
    """

    def __init__(self, model_path: str = RERANKER_MODEL_PATH) -> None:
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(model_path)
            self.model = AutoModelForSequenceClassification.from_pretrained(
                model_path,
            ).to(self.device)
        except Exception as exc:
            raise ModelLoadError(
                f"Failed to load reranker model from {model_path!r}: {exc}",
                model_path=model_path,
            ) from exc
        self.model.eval()
        self.tracer = get_tracer()

    @torch.no_grad()
    def rerank(
        self,
        query: str,
        documents: List[SearchResult],
        top_k: int = RERANK_TOP_K,
    ) -> List[RankedResult]:
        """Rerank documents against a query.

        Args:
            query: The search query.
            documents: List of SearchResult objects from the database layer.
            top_k: Number of top results to return.

        Returns:
            Sorted list of RankedResult (highest score first).

        Raises:
            RuntimeError: If the model inference step fails (e.g., CUDA OOM,
                tokenizer version mismatch, unexpected output shape).
        """
        span = self.tracer.start_span(
            "reranker.rerank",
            {"input_count": len(documents), "top_k": top_k},
        )
        _span_status = "ok"
        try:
            if not documents:
                return []

            pairs = [[query, doc.text] for doc in documents]

            # Process in fixed-size batches to bound peak VRAM usage when
            # SEARCH_LIMIT is large (RERANKER_BATCH_SIZE, default 32).
            scores: List[float] = []
            for i in range(0, len(pairs), RERANKER_BATCH_SIZE):
                batch = pairs[i : i + RERANKER_BATCH_SIZE]
                inputs = self.tokenizer(
                    batch,
                    padding=True,
                    truncation=True,
                    max_length=RERANKER_MAX_LENGTH,
                    return_tensors="pt",
                ).to(self.device)
                logits = self.model(**inputs).logits.squeeze(-1).float()
                # Apply sigmoid via manual computation to avoid API differences
                # across transformers/torch versions: newer transformers wraps
                # logits in a _Logits object that lacks .sigmoid(), and
                # torch.sigmoid() was removed in torch 2.x.
                batch_scores: List[float] = (1.0 / (1.0 + (-logits).exp())).cpu().tolist()
                # If batch contains exactly one document, tolist() returns a scalar.
                if isinstance(batch_scores, float):
                    batch_scores = [batch_scores]
                scores.extend(batch_scores)

            results = [
                RankedResult(
                    text=doc.text,
                    score=score,
                    metadata=doc.metadata,
                )
                for doc, score in zip(documents, scores)
            ]

            results.sort(key=lambda r: r.score, reverse=True)
            top_results = results[:top_k]
            if top_results:
                values = [r.score for r in top_results]
                span.set_attribute("score_min", min(values))
                span.set_attribute("score_max", max(values))
                span.set_attribute("output_count", len(top_results))
            return top_results

        except Exception as exc:
            _span_status = "error"
            raise
        finally:
            span.end(status=_span_status)


__all__ = ["LocalBGEReranker", "RankedResult"]
