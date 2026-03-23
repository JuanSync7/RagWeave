#!/usr/bin/env python3
# @summary
# Auto-scales rag-worker replicas up/down using Prometheus + runtime signals.
# Exports: main
# Deps: argparse, json, subprocess, time, urllib
# @end-summary

from __future__ import annotations

import argparse
import orjson
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from typing import Optional
from urllib import parse, request


@dataclass
class Snapshot:
    backlog: Optional[float]
    schedule_to_start_s: Optional[float]
    api_p95_ms: Optional[float]
    worker_max_mem_pct: Optional[float]
    replicas: int


def _query_prometheus(base_url: str, promql: str, timeout_s: int = 5) -> Optional[float]:
    endpoint = f"{base_url.rstrip('/')}/api/v1/query?{parse.urlencode({'query': promql})}"
    try:
        with request.urlopen(endpoint, timeout=timeout_s) as resp:
            payload = orjson.loads(resp.read())
    except Exception:
        return None
    if payload.get("status") != "success":
        return None
    results = payload.get("data", {}).get("result", [])
    if not results:
        return None
    try:
        return float(results[0]["value"][1])
    except Exception:
        return None


def _current_replicas() -> int:
    try:
        proc = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return 0
    return sum(1 for line in proc.stdout.splitlines() if "rag-rag-worker-" in line.strip())


def _worker_max_mem_pct() -> Optional[float]:
    try:
        proc = subprocess.run(
            [
                "docker",
                "stats",
                "--no-stream",
                "--format",
                "{{.Name}}\t{{.MemPerc}}",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return None
    vals: list[float] = []
    for line in proc.stdout.splitlines():
        parts = line.strip().split("\t")
        if len(parts) != 2:
            continue
        name, mem_raw = parts
        if "rag-rag-worker-" not in name:
            continue
        try:
            vals.append(float(mem_raw.replace("%", "").strip()))
        except ValueError:
            continue
    if not vals:
        return None
    return max(vals)


def _collect(args: argparse.Namespace) -> Snapshot:
    return Snapshot(
        backlog=_query_prometheus(args.prometheus_url, args.queue_backlog_query),
        schedule_to_start_s=_query_prometheus(
            args.prometheus_url, args.schedule_to_start_query
        ),
        api_p95_ms=_query_prometheus(args.prometheus_url, args.api_p95_query),
        worker_max_mem_pct=_worker_max_mem_pct(),
        replicas=_current_replicas(),
    )


def _should_scale_up(snapshot: Snapshot, args: argparse.Namespace) -> bool:
    backlog_hot = snapshot.backlog is not None and snapshot.backlog > args.scale_up_backlog
    sts_hot = (
        snapshot.schedule_to_start_s is not None
        and snapshot.schedule_to_start_s > args.scale_up_schedule_to_start_s
    )
    p95_hot = snapshot.api_p95_ms is not None and snapshot.api_p95_ms > args.scale_up_api_p95_ms
    return backlog_hot or sts_hot or p95_hot


def _should_scale_down(snapshot: Snapshot, args: argparse.Namespace) -> bool:
    backlog_cool = snapshot.backlog is None or snapshot.backlog < args.scale_down_backlog
    sts_cool = (
        snapshot.schedule_to_start_s is None
        or snapshot.schedule_to_start_s < args.scale_down_schedule_to_start_s
    )
    p95_cool = snapshot.api_p95_ms is None or snapshot.api_p95_ms < args.scale_down_api_p95_ms
    mem_safe = (
        snapshot.worker_max_mem_pct is None
        or snapshot.worker_max_mem_pct < args.max_worker_mem_pct_for_downscale
    )
    return backlog_cool and sts_cool and p95_cool and mem_safe


def _scale_to(target: int, dry_run: bool) -> bool:
    cmd = [
        "docker",
        "compose",
        "up",
        "-d",
        "--scale",
        f"rag-worker={target}",
        "rag-worker",
    ]
    if dry_run:
        print(f"action=dry_run scale_cmd={' '.join(cmd)}")
        return True
    try:
        subprocess.run(cmd, check=True)
    except Exception as exc:
        print(f"action=scale_failed target={target} error={exc}")
        return False
    return True


def _fmt(value: Optional[float]) -> str:
    if value is None:
        return "None"
    return f"{value:.2f}"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Auto-scale rag-worker replicas with conservative hysteresis."
    )
    p.add_argument(
        "--prometheus-url",
        default=f"http://localhost:{os.environ.get('PROMETHEUS_HOST_PORT', '9091')}",
    )
    p.add_argument("--interval-seconds", type=int, default=30)
    p.add_argument("--min-replicas", type=int, default=1)
    p.add_argument("--max-replicas", type=int, default=6)
    p.add_argument("--step-up", type=int, default=1)
    p.add_argument("--step-down", type=int, default=1)
    p.add_argument("--up-streak", type=int, default=2)
    p.add_argument("--down-streak", type=int, default=5)
    p.add_argument("--scale-up-cooldown-seconds", type=int, default=90)
    p.add_argument("--scale-down-cooldown-seconds", type=int, default=300)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--once", action="store_true")

    # Scale-up thresholds.
    p.add_argument("--scale-up-backlog", type=float, default=8.0)
    p.add_argument("--scale-up-schedule-to-start-s", type=float, default=1.5)
    p.add_argument("--scale-up-api-p95-ms", type=float, default=4000.0)

    # Scale-down thresholds (lower than scale-up to avoid oscillation).
    p.add_argument("--scale-down-backlog", type=float, default=1.0)
    p.add_argument("--scale-down-schedule-to-start-s", type=float, default=0.4)
    p.add_argument("--scale-down-api-p95-ms", type=float, default=1800.0)
    p.add_argument("--max-worker-mem-pct-for-downscale", type=float, default=75.0)

    # Temporal metric names can vary by deployment.
    p.add_argument(
        "--queue-backlog-query",
        default='sum(temporal_long_request_queue_pending_tasks{namespace="default",task_queue="rag-query"})',
    )
    p.add_argument(
        "--schedule-to-start-query",
        default=(
            'histogram_quantile(0.95, sum by (le) (rate(temporal_activity_schedule_to_start_latency_seconds_bucket{namespace="default",task_queue="rag-query"}[5m])))'
        ),
    )
    p.add_argument(
        "--api-p95-query",
        default=(
            'histogram_quantile(0.95, sum by (le) (rate(rag_api_request_latency_ms_bucket{endpoint="/query"}[5m])))'
        ),
    )
    return p


def main() -> int:
    args = build_parser().parse_args()
    up_streak = 0
    down_streak = 0
    last_up_ts = 0.0
    last_down_ts = 0.0

    while True:
        snapshot = _collect(args)
        now = time.time()
        can_scale_up = now - last_up_ts >= max(1, args.scale_up_cooldown_seconds)
        can_scale_down = now - last_down_ts >= max(1, args.scale_down_cooldown_seconds)

        up_signal = _should_scale_up(snapshot, args)
        down_signal = _should_scale_down(snapshot, args)

        up_streak = up_streak + 1 if up_signal else 0
        down_streak = down_streak + 1 if down_signal else 0

        action = "hold"
        target = snapshot.replicas

        if (
            up_streak >= max(1, args.up_streak)
            and can_scale_up
            and snapshot.replicas < args.max_replicas
        ):
            target = min(args.max_replicas, snapshot.replicas + max(1, args.step_up))
            if _scale_to(target, args.dry_run):
                action = "scale_up"
                last_up_ts = now
                up_streak = 0
                down_streak = 0
        elif (
            down_streak >= max(1, args.down_streak)
            and can_scale_down
            and snapshot.replicas > args.min_replicas
        ):
            target = max(args.min_replicas, snapshot.replicas - max(1, args.step_down))
            if _scale_to(target, args.dry_run):
                action = "scale_down"
                last_down_ts = now
                up_streak = 0
                down_streak = 0

        print(
            "action={action} replicas={replicas}->{target} backlog={backlog} "
            "schedule_to_start_s={sts} api_p95_ms={p95} worker_max_mem_pct={mem} "
            "up_streak={up_streak} down_streak={down_streak}".format(
                action=action,
                replicas=snapshot.replicas,
                target=target,
                backlog=_fmt(snapshot.backlog),
                sts=_fmt(snapshot.schedule_to_start_s),
                p95=_fmt(snapshot.api_p95_ms),
                mem=_fmt(snapshot.worker_max_mem_pct),
                up_streak=up_streak,
                down_streak=down_streak,
            )
        )

        if args.once:
            return 0
        time.sleep(max(1, args.interval_seconds))


if __name__ == "__main__":
    sys.exit(main())
