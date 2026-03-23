#!/usr/bin/env python3
# @summary
# Watches Prometheus + worker runtime signals and recommends scaling/concurrency tuning.
# Exports: main
# Deps: argparse, json, subprocess, urllib
# @end-summary

from __future__ import annotations

import argparse
import orjson
import os
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Optional
from urllib import parse, request


def _detect_container_runtime() -> str:
    """Return 'podman' if available, else 'docker'."""
    if shutil.which("podman"):
        return "podman"
    if shutil.which("docker"):
        return "docker"
    raise RuntimeError("Neither podman nor docker found in PATH")


CONTAINER_RT = _detect_container_runtime()


@dataclass
class Alert:
    severity: str
    signal: str
    value: float
    threshold: float
    recommendation: str


def _query_prometheus(base_url: str, promql: str, timeout_s: int = 5) -> Optional[float]:
    endpoint = f"{base_url.rstrip('/')}/api/v1/query?{parse.urlencode({'query': promql})}"
    try:
        with request.urlopen(endpoint, timeout=timeout_s) as resp:
            payload = orjson.loads(resp.read())
    except Exception:
        return None
    if payload.get("status") != "success":
        return None
    data = payload.get("data", {})
    results = data.get("result", [])
    if not results:
        return None
    try:
        return float(results[0]["value"][1])
    except Exception:
        return None


def _docker_worker_stats() -> list[tuple[str, float, float]]:
    try:
        proc = subprocess.run(
            [
                CONTAINER_RT,
                "stats",
                "--no-stream",
                "--format",
                "{{.Name}}\t{{.CPUPerc}}\t{{.MemPerc}}",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return []

    rows: list[tuple[str, float, float]] = []
    for line in proc.stdout.splitlines():
        parts = line.strip().split("\t")
        if len(parts) != 3:
            continue
        name, cpu_raw, mem_raw = parts
        if "rag-worker" not in name:
            continue
        try:
            cpu = float(cpu_raw.replace("%", "").strip())
            mem = float(mem_raw.replace("%", "").strip())
        except ValueError:
            continue
        rows.append((name, cpu, mem))
    return rows


def _gpu_mem_pct() -> Optional[float]:
    try:
        proc = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=memory.used,memory.total",
                "--format=csv,noheader,nounits",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return None
    pcts: list[float] = []
    for line in proc.stdout.splitlines():
        chunks = [c.strip() for c in line.split(",")]
        if len(chunks) != 2:
            continue
        try:
            used = float(chunks[0])
            total = float(chunks[1])
        except ValueError:
            continue
        if total > 0:
            pcts.append((used / total) * 100.0)
    if not pcts:
        return None
    return max(pcts)


def _send_webhook(webhook_url: str, alerts: list[Alert], snapshot: dict) -> None:
    payload = {
        "event": "rag_tuning_signals",
        "alerts": [a.__dict__ for a in alerts],
        "snapshot": snapshot,
        "ts": int(time.time()),
    }
    req = request.Request(
        webhook_url,
        data=orjson.dumps(payload),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=5):
            return
    except Exception:
        return


def _evaluate(snapshot: dict, args: argparse.Namespace) -> list[Alert]:
    alerts: list[Alert] = []

    schedule_to_start_s = snapshot.get("schedule_to_start_s")
    backlog = snapshot.get("queue_backlog")
    api_p95_ms = snapshot.get("api_p95_ms")
    stage_retrieval_p95_ms = snapshot.get("retrieval_p95_ms")
    stage_generation_p95_ms = snapshot.get("generation_p95_ms")
    worker_max_mem_pct = snapshot.get("worker_max_mem_pct")
    gpu_max_mem_pct = snapshot.get("gpu_max_mem_pct")

    if schedule_to_start_s is not None and schedule_to_start_s > args.max_schedule_to_start_s:
        alerts.append(
            Alert(
                severity="warning",
                signal="schedule_to_start_s",
                value=schedule_to_start_s,
                threshold=args.max_schedule_to_start_s,
                recommendation="Increase worker replicas for rag-query.",
            )
        )

    if backlog is not None and backlog > args.max_queue_backlog:
        alerts.append(
            Alert(
                severity="warning",
                signal="queue_backlog",
                value=backlog,
                threshold=args.max_queue_backlog,
                recommendation="Backlog is growing; add worker replicas or reduce task duration.",
            )
        )

    if api_p95_ms is not None and api_p95_ms > args.max_api_p95_ms:
        alerts.append(
            Alert(
                severity="warning",
                signal="api_p95_ms",
                value=api_p95_ms,
                threshold=args.max_api_p95_ms,
                recommendation="High API p95; inspect backlog, retrieval and generation stage p95.",
            )
        )

    if stage_retrieval_p95_ms is not None and stage_retrieval_p95_ms > args.max_retrieval_p95_ms:
        alerts.append(
            Alert(
                severity="warning",
                signal="retrieval_p95_ms",
                value=stage_retrieval_p95_ms,
                threshold=args.max_retrieval_p95_ms,
                recommendation="Retrieval is slow; consider fast_path, lower iterations, or more workers.",
            )
        )

    if (
        stage_generation_p95_ms is not None
        and stage_generation_p95_ms > args.max_generation_p95_ms
    ):
        alerts.append(
            Alert(
                severity="warning",
                signal="generation_p95_ms",
                value=stage_generation_p95_ms,
                threshold=args.max_generation_p95_ms,
                recommendation="Generation is slow; tune model, prompt length, or generation concurrency.",
            )
        )

    if worker_max_mem_pct is not None and worker_max_mem_pct > args.max_worker_mem_pct:
        alerts.append(
            Alert(
                severity="critical",
                signal="worker_max_mem_pct",
                value=worker_max_mem_pct,
                threshold=args.max_worker_mem_pct,
                recommendation="Worker memory pressure high; lower RAG_WORKER_CONCURRENCY or add replicas.",
            )
        )

    if gpu_max_mem_pct is not None and gpu_max_mem_pct > args.max_gpu_mem_pct:
        alerts.append(
            Alert(
                severity="critical",
                signal="gpu_max_mem_pct",
                value=gpu_max_mem_pct,
                threshold=args.max_gpu_mem_pct,
                recommendation="GPU memory near limit; reduce per-worker concurrency before scaling up.",
            )
        )

    return alerts


def _print_report(snapshot: dict, alerts: list[Alert]) -> None:
    print("\n=== RAG Tuning Signals ===")
    print(
        "schedule_to_start_s={sts} queue_backlog={backlog} api_p95_ms={api_p95} "
        "retrieval_p95_ms={ret_p95} generation_p95_ms={gen_p95} "
        "worker_max_cpu_pct={cpu} worker_max_mem_pct={mem} gpu_max_mem_pct={gpu}".format(
            sts=snapshot.get("schedule_to_start_s"),
            backlog=snapshot.get("queue_backlog"),
            api_p95=snapshot.get("api_p95_ms"),
            ret_p95=snapshot.get("retrieval_p95_ms"),
            gen_p95=snapshot.get("generation_p95_ms"),
            cpu=snapshot.get("worker_max_cpu_pct"),
            mem=snapshot.get("worker_max_mem_pct"),
            gpu=snapshot.get("gpu_max_mem_pct"),
        )
    )

    if not alerts:
        print("status=ok recommendation=No tuning change needed right now.")
        return

    for alert in alerts:
        print(
            f"status={alert.severity} signal={alert.signal} value={alert.value:.2f} "
            f"threshold={alert.threshold:.2f} recommendation={alert.recommendation}"
        )


def _collect_snapshot(args: argparse.Namespace) -> dict:
    workers = _docker_worker_stats()
    worker_max_cpu = max((cpu for _, cpu, _ in workers), default=0.0) if workers else None
    worker_max_mem = max((mem for _, _, mem in workers), default=0.0) if workers else None

    snapshot = {
        "schedule_to_start_s": _query_prometheus(
            args.prometheus_url, args.schedule_to_start_query
        ),
        "queue_backlog": _query_prometheus(args.prometheus_url, args.queue_backlog_query),
        "api_p95_ms": _query_prometheus(args.prometheus_url, args.api_p95_query),
        "retrieval_p95_ms": _query_prometheus(args.prometheus_url, args.retrieval_p95_query),
        "generation_p95_ms": _query_prometheus(args.prometheus_url, args.generation_p95_query),
        "worker_max_cpu_pct": worker_max_cpu,
        "worker_max_mem_pct": worker_max_mem,
        "gpu_max_mem_pct": _gpu_mem_pct(),
        "worker_count": len(workers),
    }
    return snapshot


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Monitor RAG worker scaling/concurrency signals and emit tuning alerts."
    )
    p.add_argument(
        "--prometheus-url",
        default=f"http://localhost:{os.environ.get('PROMETHEUS_HOST_PORT', '9091')}",
    )
    p.add_argument("--interval-seconds", type=int, default=30)
    p.add_argument("--once", action="store_true")
    p.add_argument("--webhook-url", default="")

    p.add_argument("--max-schedule-to-start-s", type=float, default=2.0)
    p.add_argument("--max-queue-backlog", type=float, default=10.0)
    p.add_argument("--max-api-p95-ms", type=float, default=2500.0)
    p.add_argument("--max-retrieval-p95-ms", type=float, default=5000.0)
    p.add_argument("--max-generation-p95-ms", type=float, default=15000.0)
    p.add_argument("--max-worker-mem-pct", type=float, default=85.0)
    p.add_argument("--max-gpu-mem-pct", type=float, default=90.0)

    # Temporal metric names vary across deployments. Keep these overridable.
    p.add_argument(
        "--schedule-to-start-query",
        default=(
            'histogram_quantile(0.95, sum by (le) (rate(temporal_activity_schedule_to_start_latency_seconds_bucket{namespace="default",task_queue="rag-query"}[5m])))'
        ),
    )
    p.add_argument(
        "--queue-backlog-query",
        default='sum(temporal_long_request_queue_pending_tasks{namespace="default",task_queue="rag-query"})',
    )
    p.add_argument(
        "--api-p95-query",
        default=(
            'histogram_quantile(0.95, sum by (le) (rate(rag_api_request_latency_ms_bucket{endpoint="/query"}[5m])))'
        ),
    )
    p.add_argument(
        "--retrieval-p95-query",
        default=(
            'histogram_quantile(0.95, sum by (le) (rate(rag_pipeline_stage_ms_bucket{bucket="retrieval"}[5m])))'
        ),
    )
    p.add_argument(
        "--generation-p95-query",
        default=(
            'histogram_quantile(0.95, sum by (le) (rate(rag_pipeline_stage_ms_bucket{bucket="generation"}[5m])))'
        ),
    )
    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    while True:
        snapshot = _collect_snapshot(args)
        alerts = _evaluate(snapshot, args)
        _print_report(snapshot, alerts)

        if alerts and args.webhook_url:
            _send_webhook(args.webhook_url, alerts, snapshot)

        if args.once:
            return 0
        time.sleep(max(1, args.interval_seconds))


if __name__ == "__main__":
    sys.exit(main())
