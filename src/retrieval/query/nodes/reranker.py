# @summary
# Local BAAI bge-reranker-v2-m3 wrapper for reranking search results.
# Key exports: LocalBGEReranker, RankedResult
# Deps: transformers, torch, config.settings (RERANKER_MODEL_PATH, RERANK_TOP_K,
#       RERANKER_MAX_LENGTH, RERANKER_BATCH_SIZE, RERANKER_PRECISION),
#       src.vector_db.common.schemas, src.retrieval.common.schemas,
#       src.retrieval.common.exceptions
# @end-summary
"""Local BAAI bge-reranker-v2-m3 wrapper for reranking search results.

Uses transformers directly instead of FlagEmbedding to avoid compatibility
issues with transformers >= 5.x.
"""

import logging
import math
import time
from typing import List

import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer

from config.settings import (
    RERANKER_MODEL_PATH,
    RERANK_TOP_K,
    RERANKER_MAX_LENGTH,
    RERANKER_BATCH_SIZE,
    RERANKER_PRECISION,
)
from src.platform.observability import get_tracer
from src.vector_db.common.schemas import SearchResult
from src.retrieval.common.schemas import RankedResult
from src.retrieval.common.exceptions import ModelLoadError

logger = logging.getLogger("rag.reranker")


# Mapping from precision name → torch dtype. int8/int4 are handled via
# bitsandbytes quantization (not a plain dtype) and fall through to the
# fp32 load path in this iteration — the keys exist so downstream iterations
# can flip them on without another PROGRAM.md change.
_TORCH_DTYPE_BY_PRECISION = {
    "fp32": torch.float32,
    "fp16": torch.float16,
    "bf16": torch.bfloat16,
}


class LocalBGEReranker:
    """Reranker using a local BAAI/bge-reranker-v2-m3 model.

    Attributes:
        device: Compute device string ("cuda" or "cpu").
        precision: Precision mode string (e.g., "fp32", "fp16", "bf16").
        tokenizer: Loaded AutoTokenizer for the reranker model.
        model: Loaded AutoModelForSequenceClassification.
    """

    def __init__(
        self,
        model_path: str = RERANKER_MODEL_PATH,
        precision: str = RERANKER_PRECISION,
    ) -> None:
        _t0 = time.perf_counter()
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.precision = precision
        torch_dtype = _TORCH_DTYPE_BY_PRECISION.get(precision)
        try:
            self.tokenizer = AutoTokenizer.from_pretrained(model_path)
            if torch_dtype is not None and torch_dtype != torch.float32:
                # Low-precision fast path (fp16/bf16). Load directly in the
                # target dtype to avoid a wasted fp32 materialization.
                self.model = AutoModelForSequenceClassification.from_pretrained(
                    model_path,
                    torch_dtype=torch_dtype,
                ).to(self.device)
                logger.info(
                    "Reranker loaded in %s precision on %s", precision, self.device
                )
            else:
                # fp32 path — unchanged from baseline. int8/int4 also land here
                # until a future iteration wires bitsandbytes.
                if precision not in ("fp32", None) and precision not in _TORCH_DTYPE_BY_PRECISION:
                    logger.warning(
                        "Reranker precision=%r is declared but not yet wired "
                        "(int8/int4 require bitsandbytes); loading fp32.",
                        precision,
                    )
                self.model = AutoModelForSequenceClassification.from_pretrained(
                    model_path,
                ).to(self.device)
                logger.info(
                    "Reranker loaded in fp32 precision on %s", self.device
                )
        except Exception as exc:
            logger.error("Failed to load reranker from %r: %s", model_path, exc)
            raise ModelLoadError(
                f"Failed to load reranker model from {model_path!r}: {exc}",
                model_path=model_path,
            ) from exc
        self.model.eval()
        logger.info(
            "Reranker ready in %.1fms (precision=%s, device=%s, max_length=%d, batch_size=%d).",
            (time.perf_counter() - _t0) * 1000,
            precision,
            self.device,
            RERANKER_MAX_LENGTH,
            RERANKER_BATCH_SIZE,
        )

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
        with get_tracer().span(
            "reranker.rerank",
            {"input_count": len(documents), "top_k": top_k},
        ) as span:
            if not documents:
                logger.debug("rerank: empty document list, returning empty result")
                return []

            logger.debug(
                "rerank: scoring %d documents (top_k=%d, batch_size=%d)",
                len(documents), top_k, RERANKER_BATCH_SIZE,
            )
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
                # Materialize to Python floats before sigmoid to avoid _Logits
                # proxy limitations in transformers >= 4.50 (no __neg__, no
                # .sigmoid()) and torch.sigmoid removal in torch 2.x.
                scores_raw = logits.cpu().tolist()
                if isinstance(scores_raw, float):
                    scores_raw = [scores_raw]
                batch_scores: List[float] = [1.0 / (1.0 + math.exp(-x)) for x in scores_raw]
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


__all__ = ["LocalBGEReranker", "RankedResult"]
