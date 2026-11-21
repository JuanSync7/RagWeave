#!/usr/bin/env python3
# @summary
# Tiny stdlib HTTP stand-in for RagWeave's /query and /health, so the eval
# harness, judge and report can be smoke-tested end-to-end without the real
# stack (e.g. when the vLLM host is down). Returns canned but
# schema-accurate answers + chunks. NOT for real evaluation.
# Exports: (run as a script)  python mock_ragweave.py --port 8077
# Deps: (stdlib only: http.server)
# @end-summary
"""Mock RagWeave server for offline harness testing."""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def _fake_answer(q: str) -> dict:
    chunks = [
        {"text": f"Relevant passage about: {q[:60]} ... (mock chunk 1).",
         "score": 0.82,
         "metadata": {"source": "IHI0050H_amba_chi_architecture_spec.pdf",
                      "section": "B1.1.2", "document_id": "doc-001",
                      "source_uri": "s3://corpus/IHI0050H.pdf"}},
        {"text": "Secondary supporting passage (mock chunk 2).",
         "score": 0.61,
         "metadata": {"source": "IHI0022L_amba_axi_protocol_spec.pdf",
                      "section": "A1.1", "document_id": "doc-002",
                      "source_uri": "s3://corpus/IHI0022L.pdf"}},
    ]
    return {
        "query": q, "processed_query": q, "query_confidence": 0.9, "action": "search",
        "results": chunks,
        "generated_answer": (f"[MOCK ANSWER] Based on the retrieved specs, here is a "
                             f"plausible response to: {q[:80]}. This is canned text for "
                             f"harness testing only."),
        "llm_confidence": "medium", "generation_source": "retrieval",
        "workflow_id": "mock-wf-1", "latency_ms": 1234.0,
        "stage_timings": [], "timing_totals": {},
        "seen_doc_ids": ["doc-001", "doc-002"],
        "relevant_doc_ids": ["doc-001"], "ignored_doc_ids": [],
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/health"):
            self._send(200, {"status": "ok", "temporal_connected": True,
                             "worker_available": True, "ingest_worker_available": True})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self.path.startswith("/query"):
            self._send(404, {"error": "not found"})
            return
        n = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(n) or b"{}")
        self._send(200, _fake_answer(payload.get("query", "")))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8077)
    args = ap.parse_args()
    print(f"[mock-ragweave] listening on http://localhost:{args.port}  "
          f"(point the harness with --rag-url http://localhost:{args.port})")
    ThreadingHTTPServer(("0.0.0.0", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
