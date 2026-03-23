#!/usr/bin/env python3
# @summary
# Lightweight concurrent load test for RAG API /query endpoint.
# Exports: main
# Deps: argparse, concurrent.futures, json, time, urllib
# @end-summary

from __future__ import annotations

import argparse
import orjson
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from urllib import request
from urllib.error import HTTPError, URLError


@dataclass
class RequestResult:
    ok: bool
    status: int
    latency_ms: float
    error: str = ""


def _percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    idx = int(round((p / 100.0) * (len(values) - 1)))
    return sorted(values)[idx]


def _one_request(
    *,
    url: str,
    query: str,
    timeout_s: float,
    api_key: str,
    bearer_token: str,
    tenant_id: str,
) -> RequestResult:
    payload = {"query": query}
    if tenant_id:
        payload["tenant_id"] = tenant_id
    body = orjson.dumps(payload)
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["x-api-key"] = api_key
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"

    req = request.Request(
        f"{url.rstrip('/')}/query",
        data=body,
        headers=headers,
        method="POST",
    )

    start = time.perf_counter()
    try:
        with request.urlopen(req, timeout=timeout_s) as resp:
            _ = resp.read()
            latency_ms = (time.perf_counter() - start) * 1000
            return RequestResult(ok=200 <= resp.status < 300, status=resp.status, latency_ms=latency_ms)
    except HTTPError as exc:
        latency_ms = (time.perf_counter() - start) * 1000
        return RequestResult(
            ok=False,
            status=exc.code,
            latency_ms=latency_ms,
            error=f"HTTPError: {exc.code}",
        )
    except URLError as exc:
        latency_ms = (time.perf_counter() - start) * 1000
        return RequestResult(
            ok=False,
            status=0,
            latency_ms=latency_ms,
            error=f"URLError: {exc}",
        )
    except Exception as exc:
        latency_ms = (time.perf_counter() - start) * 1000
        return RequestResult(
            ok=False,
            status=0,
            latency_ms=latency_ms,
            error=f"Error: {exc}",
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a concurrent /query load test against the RAG API."
    )
    parser.add_argument(
        "--url",
        default=os.environ.get("RAG_API_URL", f"http://localhost:{os.environ.get('RAG_API_PORT', '8000')}"),
    )
    parser.add_argument("--query", default="What is retrieval augmented generation?")
    parser.add_argument("--total-requests", type=int, default=500)
    parser.add_argument("--concurrency", type=int, default=100)
    parser.add_argument("--timeout-seconds", type=float, default=30.0)
    parser.add_argument("--api-key", default="")
    parser.add_argument("--bearer-token", default="")
    parser.add_argument("--tenant-id", default="")
    parser.add_argument("--max-error-rate", type=float, default=2.0)
    parser.add_argument("--max-p95-ms", type=float, default=2500.0)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    total_requests = max(1, args.total_requests)
    concurrency = max(1, min(args.concurrency, total_requests))

    print(
        f"starting load test url={args.url} total_requests={total_requests} "
        f"concurrency={concurrency}"
    )
    started = time.perf_counter()
    results: list[RequestResult] = []

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        futures = [
            pool.submit(
                _one_request,
                url=args.url,
                query=args.query,
                timeout_s=args.timeout_seconds,
                api_key=args.api_key,
                bearer_token=args.bearer_token,
                tenant_id=args.tenant_id,
            )
            for _ in range(total_requests)
        ]
        for fut in as_completed(futures):
            results.append(fut.result())

    elapsed_s = time.perf_counter() - started
    latencies = [r.latency_ms for r in results]
    ok_count = sum(1 for r in results if r.ok)
    error_count = total_requests - ok_count
    error_rate = (error_count / total_requests) * 100.0
    p50 = _percentile(latencies, 50)
    p95 = _percentile(latencies, 95)
    p99 = _percentile(latencies, 99)
    rps = total_requests / elapsed_s if elapsed_s > 0 else 0.0

    print(
        "completed requests={req} ok={ok} errors={err} error_rate={err_rate:.2f}% "
        "duration_s={dur:.2f} rps={rps:.2f}".format(
            req=total_requests,
            ok=ok_count,
            err=error_count,
            err_rate=error_rate,
            dur=elapsed_s,
            rps=rps,
        )
    )
    print(
        "latency_ms p50={p50:.1f} p95={p95:.1f} p99={p99:.1f} mean={mean:.1f}".format(
            p50=p50,
            p95=p95,
            p99=p99,
            mean=statistics.mean(latencies) if latencies else 0.0,
        )
    )

    non_2xx = [r for r in results if not r.ok]
    if non_2xx:
        by_status: dict[int, int] = {}
        for r in non_2xx:
            by_status[r.status] = by_status.get(r.status, 0) + 1
        print(f"errors by status: {by_status}")
        sample = non_2xx[:5]
        for idx, item in enumerate(sample, start=1):
            print(
                f"error_sample_{idx} status={item.status} "
                f"latency_ms={item.latency_ms:.1f} msg={item.error}"
            )

    passes = True
    if error_rate > args.max_error_rate:
        passes = False
        print(
            "SLO check failed: error_rate={err:.2f}% > max_error_rate={max_err:.2f}%".format(
                err=error_rate,
                max_err=args.max_error_rate,
            )
        )
    if p95 > args.max_p95_ms:
        passes = False
        print(
            "SLO check failed: p95_ms={p95:.1f} > max_p95_ms={max_p95:.1f}".format(
                p95=p95,
                max_p95=args.max_p95_ms,
            )
        )

    if passes:
        print("SLO check passed.")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
