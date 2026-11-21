# @summary
# Thin, dependency-free HTTP client for the RagWeave POST /query endpoint.
# Normalizes the response into a stable dict (answer, chunks, sources, timing)
# and captures errors instead of raising, so the eval loop never dies on one
# bad query.
# Exports: ask, RagResult, health
# Deps: (stdlib only: urllib)
# @end-summary
"""RagWeave query client used by the pilot eval harness.

Why stdlib-only: the harness should run with the system/user python without
needing RagWeave's own virtualenv or `requests` installed.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request


def _post(url: str, payload: dict, timeout: int, token: str = "") -> dict:
    data = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
    return json.loads(body)


def health(rag_url: str, timeout: int = 10) -> dict:
    """Return the /health payload, or an {'error': ...} dict on failure."""
    try:
        req = urllib.request.Request(rag_url.rstrip("/") + "/health", method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - health probe must never raise
        return {"error": f"{type(exc).__name__}: {exc}"}


def _normalize_chunk(raw: dict) -> dict:
    """Flatten a ChunkResult into a render-friendly shape (metadata may vary)."""
    meta = raw.get("metadata") or {}
    return {
        "text": raw.get("text", ""),
        "score": raw.get("score"),
        "source": meta.get("source") or meta.get("source_name") or meta.get("source_uri"),
        "section": meta.get("section") or meta.get("heading"),
        "document_id": meta.get("document_id") or meta.get("doc_id"),
        "source_uri": meta.get("source_uri") or meta.get("source_key"),
        "char_start": meta.get("original_char_start"),
        "char_end": meta.get("original_char_end"),
        "metadata": meta,
    }


def ask(cfg, query: str, *, mode: str = None) -> dict:
    """Send one query to RagWeave and return a normalized result dict.

    Never raises: on any failure the returned dict has ok=False and an `error`
    string, plus whatever partial data was available. Keys:
        ok, error, http_status, query, processed_query,
        answer, llm_confidence, generation_source, query_confidence, action,
        chunks (list of normalized chunk dicts), sources (deduped doc list),
        latency_ms, wall_s, workflow_id, raw (the full server JSON if any)
    """
    url = cfg.rag_url.rstrip("/") + "/query"
    payload = {
        "query": query,
        "mode": mode or cfg.mode,
        "search_limit": cfg.search_limit,
        "rerank_top_k": cfg.rerank_top_k,
        "alpha": cfg.alpha,
    }
    if cfg.fast_path is not None:
        payload["fast_path"] = cfg.fast_path

    last_err = None
    http_status = None
    attempts = max(1, cfg.retries + 1)
    for attempt in range(attempts):
        t0 = time.time()
        try:
            raw = _post(url, payload, cfg.request_timeout_s, cfg.rag_auth_token)
            wall = time.time() - t0
            chunks = [_normalize_chunk(c) for c in (raw.get("results") or [])]
            return {
                "ok": True,
                "error": None,
                "http_status": 200,
                "query": query,
                "processed_query": raw.get("processed_query"),
                "answer": raw.get("generated_answer"),
                "llm_confidence": raw.get("llm_confidence"),
                "generation_source": raw.get("generation_source"),
                "query_confidence": raw.get("query_confidence"),
                "action": raw.get("action"),
                "clarification_message": raw.get("clarification_message"),
                "chunks": chunks,
                "sources": _dedupe_sources(chunks),
                "latency_ms": raw.get("latency_ms"),
                "stage_timings": raw.get("stage_timings") or [],
                "wall_s": round(wall, 2),
                "workflow_id": raw.get("workflow_id"),
                "attempt": attempt + 1,
                "raw": raw,
            }
        except urllib.error.HTTPError as exc:
            http_status = exc.code
            try:
                body = exc.read().decode("utf-8")
            except Exception:  # noqa: BLE001
                body = ""
            last_err = f"HTTP {exc.code}: {body[:400]}"
        except Exception as exc:  # noqa: BLE001 - timeouts, conn refused, etc.
            last_err = f"{type(exc).__name__}: {exc}"
        # brief backoff before retry
        if attempt < attempts - 1:
            time.sleep(3)

    return {
        "ok": False,
        "error": last_err,
        "http_status": http_status,
        "query": query,
        "processed_query": None,
        "answer": None,
        "llm_confidence": None,
        "generation_source": None,
        "query_confidence": None,
        "action": None,
        "clarification_message": None,
        "chunks": [],
        "sources": [],
        "latency_ms": None,
        "stage_timings": [],
        "wall_s": None,
        "workflow_id": None,
        "attempt": attempts,
        "raw": None,
    }


def _dedupe_sources(chunks: list) -> list:
    """Collapse chunks into a per-document summary (name, best score, #chunks)."""
    by_doc = {}
    for c in chunks:
        key = c.get("source") or c.get("document_id") or "(unknown)"
        entry = by_doc.setdefault(key, {
            "source": c.get("source") or "(unknown)",
            "document_id": c.get("document_id"),
            "source_uri": c.get("source_uri"),
            "chunk_count": 0,
            "best_score": None,
            "sections": [],
        })
        entry["chunk_count"] += 1
        s = c.get("score")
        if s is not None and (entry["best_score"] is None or s > entry["best_score"]):
            entry["best_score"] = s
        sec = c.get("section")
        if sec and sec not in entry["sections"]:
            entry["sections"].append(sec)
    return sorted(by_doc.values(),
                  key=lambda e: (e["best_score"] is not None, e["best_score"] or 0),
                  reverse=True)
