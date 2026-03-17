# Operations Platform — Implementation Guide

**AION Knowledge Management Platform**
Version: 1.0 | Status: Draft | Domain: Operations

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-03-13 | AI Assistant | Initial implementation guide reverse-engineered from implemented operations infrastructure |

> **Document intent:** This file is a phased implementation plan tied to `OPERATIONS_PLATFORM_SPEC.md`.
> DR runbook and secrets management are included as appendices (Part C).
> For the 100-user scaling plan, see `RAG_100_USER_EXECUTION_PLAN.md`.

---

# Part A: Task-Oriented Overview

## Phase 1 — Deployment Topology and Container Orchestration

### Task 1.1: Declarative Deployment Manifest

**Description:** Define the container orchestration manifest with all services, named profiles, health checks, persistence volumes, and network configuration.

**Requirements Covered:** REQ-101, REQ-102, REQ-103, REQ-104, REQ-903

**Dependencies:** None

**Complexity:** L

**Subtasks:**

1. Define infrastructure services: workflow engine, workflow DB, vector DB, key-value store, container log viewer
2. Define application services under named profiles: API server (`app`), worker replicas (`workers`)
3. Define monitoring services under `monitoring` profile: metrics collector, dashboard server, alert manager
4. Define observability services under `observability` profile: trace backend with its database
5. Configure named persistent volumes for all stateful services
6. Add health checks for API server and worker containers
7. Configure default profile to start infrastructure only; application and monitoring require explicit activation

**Risks:** Profile composition errors may accidentally start unneeded services; mitigate with profile-combination integration tests.

**Testing Strategy:** Profile smoke tests verify each profile starts exactly the documented service set.

---

### Task 1.2: Worker Container Image

**Description:** Build the worker container image with ML runtime dependencies, model preloading, and graceful lifecycle management.

**Requirements Covered:** REQ-201

**Dependencies:** None

**Complexity:** M

**Subtasks:**

1. Define worker container image with ML runtime dependencies (embedding model, reranker, generator)
2. Configure model preloading at container startup with health readiness gating
3. Configure graceful shutdown with in-flight activity draining
4. Set resource limits appropriate for GPU/memory-intensive workloads

---

## Phase 2 — Scaling and Capacity Management

### Task 2.1: API Overload Protection

**Description:** Implement bounded concurrency control at the API tier with configurable in-flight limits and observable metrics.

**Requirements Covered:** REQ-202, REQ-903

**Dependencies:** Task 1.1

**Complexity:** M

**Subtasks:**

1. Implement semaphore-based in-flight request limiter with configurable max permits
2. Implement queue wait timeout before 503 rejection
3. Emit in-flight gauge and overload rejection counter metrics
4. Externalize limits to environment variables

---

### Task 2.2: Worker Autoscaling Controller

**Description:** Build an autoscaling loop that adjusts worker replicas based on live operational signals.

**Requirements Covered:** REQ-203, REQ-903

**Dependencies:** Task 1.1, Task 3.1

**Complexity:** M

**Subtasks:**

1. Implement a polling loop that reads task queue depth, worker utilization, and schedule-to-start latency from the metrics collector
2. Implement scale-up rules: increase replicas when queue depth exceeds configurable threshold
3. Implement scale-down rules: decrease replicas when load drops below threshold with hysteresis and cooldown
4. Execute scaling via container orchestrator CLI commands
5. Log every scale event with timestamp, signal values, and action taken
6. Externalize all thresholds, min/max replicas, and cooldown periods to configuration

---

### Task 2.3: Load Testing Tool

**Description:** Build a load testing script that validates API capacity at target concurrency levels with SLO pass/fail gates.

**Requirements Covered:** REQ-204, REQ-205

**Dependencies:** Task 1.1

**Complexity:** M

**Subtasks:**

1. Implement concurrent query submission at configurable concurrency and request count
2. Collect per-request latency, status codes, and error messages
3. Compute aggregate metrics: error rate, p50, p95, p99, requests per second
4. Implement SLO gates: max error rate, max p95 latency
5. Report pass/fail with detailed metrics summary
6. Document the capacity envelope with results from a standard load profile

**Testing Strategy:** Run against a local deployment with 1 worker; validate metric collection and reporting accuracy.

---

## Phase 3 — Monitoring, Alerting, and Dashboards

### Task 3.1: Metrics Collection Configuration

**Description:** Configure the metrics collector to scrape API server and infrastructure service metrics at regular intervals.

**Requirements Covered:** REQ-301, REQ-903

**Dependencies:** Task 1.1

**Complexity:** S

**Subtasks:**

1. Define scrape targets: API server metrics endpoint, workflow engine metrics (if exposed), container metrics
2. Configure scrape intervals (recommended: 15s for API, 30s for infrastructure)
3. Configure data retention period (recommended: >= 30 days)
4. Verify metric availability after configuration

---

### Task 3.2: Dashboard Provisioning

**Description:** Create pre-configured dashboards for API performance, worker utilization, queue depth, and error rates.

**Requirements Covered:** REQ-302

**Dependencies:** Task 3.1

**Complexity:** M

**Subtasks:**

1. Create API performance dashboard: request rate, latency histograms, error rate, in-flight count
2. Create worker dashboard: worker count, task processing rate, schedule-to-start latency
3. Create infrastructure dashboard: database health, key-value store metrics, queue depth
4. Create overload dashboard: overload rejections, rate limit rejections, 5xx error rate
5. Configure auto-provisioning so dashboards are available on first deployment

---

### Task 3.3: Alert Rules and Tuning Signal Watcher

**Description:** Define alert rules for SLO breaches and build a terminal-based tuning signal watcher.

**Requirements Covered:** REQ-303, REQ-304

**Dependencies:** Task 3.1

**Complexity:** M

**Subtasks:**

1. Define alert rules: p95 latency breach, error rate spike, queue depth growth, worker unavailability, overload rejection spike
2. Configure alert severity levels (page vs. non-page)
3. Build a CLI tuning signal watcher that polls metrics and displays key signals at configurable intervals
4. Display recommendations (add workers, reduce concurrency, check health) based on signal thresholds

---

## Phase 4 — Disaster Recovery and Backup

### Task 4.1: Backup and Restore Scripts

**Description:** Implement scripted backup and restore procedures for all stateful stores.

**Requirements Covered:** REQ-401, REQ-402, REQ-404

**Dependencies:** Task 1.1

**Complexity:** M

**Subtasks:**

1. Implement backup script that creates a timestamped backup directory
2. Back up vector database data volumes
3. Back up workflow engine database
4. Back up key-value store data (RDB/AOF snapshots)
5. Back up observability data (if persistent)
6. Implement restore script that recovers from a backup artifact directory
7. Restore sequence: stop services → restore volumes → restart services → verify health

---

### Task 4.2: DR Drill Script

**Description:** Implement a DR drill script that exercises the full backup → restore → verify cycle.

**Requirements Covered:** REQ-403

**Dependencies:** Task 4.1

**Complexity:** S

**Subtasks:**

1. Run backup script
2. Run restore script against the fresh backup
3. Verify health endpoint returns healthy
4. Verify a test query returns results
5. Record drill date, backup artifact path, and pass/fail status

---

## Phase 5 — Secrets, CI/CD, and Delivery

### Task 5.1: Secrets Documentation and Validation

**Description:** Document all required secrets and implement startup validation that fails fast when secrets are missing.

**Requirements Covered:** REQ-501, REQ-502, REQ-503

**Dependencies:** None

**Complexity:** S

**Subtasks:**

1. Enumerate all required secrets: auth JWT secret, observability keys, encryption keys
2. Document each secret's purpose, environment variable name, and rotation procedure
3. Implement startup check that validates all required secrets are present
4. Document recommended rotation schedule (90 days) with post-rotation validation steps

---

### Task 5.2: CI Pipeline Configuration

**Description:** Configure the CI pipeline with syntax validation, type checking, and unit test execution.

**Requirements Covered:** REQ-601, REQ-602

**Dependencies:** None

**Complexity:** S

**Subtasks:**

1. Define CI workflow triggered on push/PR
2. Add syntax/compile check step
3. Add unit test execution step
4. Optionally add retrieval quality regression gate for prompt/model changes
5. Configure CI to block merge on failure

---

### Task 5.3: Health-Gated Deployment

**Description:** Implement post-deploy health checks and smoke query validation before routing production traffic.

**Requirements Covered:** REQ-603

**Dependencies:** Task 1.1

**Complexity:** S

**Subtasks:**

1. Implement post-deploy health probe loop with timeout
2. Run a smoke query to verify end-to-end pipeline functionality
3. Report deployment success/failure based on health and smoke results
4. Document rollback procedure if post-deploy validation fails

---

## Task Dependency Graph

```
Phase 1 (Deployment Topology)
├── Task 1.1: Deployment Manifest ──────────────────────────┐
└── Task 1.2: Worker Container Image ───────────────────────┤
                                                             │
Phase 2 (Scaling)                                           │
├── Task 2.1: API Overload Protection ◄── Task 1.1 ─────────┤
├── Task 2.2: Worker Autoscaling ◄── Task 1.1, Task 3.1 ────┤
└── Task 2.3: Load Testing Tool ◄── Task 1.1 ───────────────┤ [CRITICAL]
                                                             │
Phase 3 (Monitoring)                                        │
├── Task 3.1: Metrics Collection ◄── Task 1.1 ──────────────┤
├── Task 3.2: Dashboard Provisioning ◄── Task 3.1 ──────────┤
└── Task 3.3: Alert Rules and Tuning Watcher ◄── Task 3.1 ──┤
                                                             │
Phase 4 (DR)                                                │
├── Task 4.1: Backup and Restore Scripts ◄── Task 1.1 ──────┤
└── Task 4.2: DR Drill Script ◄── Task 4.1 ─────────────────┤
                                                             │
Phase 5 (Secrets and Delivery)                              │
├── Task 5.1: Secrets Documentation ─────────────────────────┤
├── Task 5.2: CI Pipeline ──────────────────────────────────┤
└── Task 5.3: Health-Gated Deployment ◄── Task 1.1 ─────────┘

Critical path: Task 1.1 → Task 2.3 → Task 3.1 → Task 3.2 → Task 4.1 → Task 4.2
```

---

## Task-to-Requirement Mapping

| Task | Requirements Covered |
|------|---------------------|
| 1.1 Deployment Manifest | REQ-101, REQ-102, REQ-103, REQ-104, REQ-903 |
| 1.2 Worker Container Image | REQ-201 |
| 2.1 API Overload Protection | REQ-202, REQ-903 |
| 2.2 Worker Autoscaling | REQ-203, REQ-903 |
| 2.3 Load Testing Tool | REQ-204, REQ-205 |
| 3.1 Metrics Collection | REQ-301, REQ-903 |
| 3.2 Dashboard Provisioning | REQ-302 |
| 3.3 Alert Rules and Tuning Watcher | REQ-303, REQ-304 |
| 4.1 Backup and Restore Scripts | REQ-401, REQ-402, REQ-404 |
| 4.2 DR Drill Script | REQ-403 |
| 5.1 Secrets Documentation | REQ-501, REQ-502, REQ-503 |
| 5.2 CI Pipeline | REQ-601, REQ-602 |
| 5.3 Health-Gated Deployment | REQ-603 |

---

# Part B: Code Appendix

## B.1: Worker Autoscaling Controller

This snippet shows the autoscaling loop that reads live signals and adjusts worker replicas.

**Tasks:** Task 2.2
**Requirements:** REQ-203

```python
from __future__ import annotations

import logging
import subprocess
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class ScalingConfig:
    min_replicas: int = 1
    max_replicas: int = 6
    queue_depth_scale_up_threshold: int = 10
    queue_depth_scale_down_threshold: int = 2
    scale_up_cooldown_s: int = 60
    scale_down_cooldown_s: int = 180
    poll_interval_s: int = 30


@dataclass
class ScalingSignals:
    queue_depth: int
    active_workers: int
    schedule_to_start_latency_ms: float


class WorkerAutoscaler:
    def __init__(self, config: ScalingConfig):
        self.config = config
        self._last_scale_up = 0.0
        self._last_scale_down = 0.0

    def evaluate(self, signals: ScalingSignals, current_replicas: int) -> int:
        now = time.time()
        target = current_replicas

        if (
            signals.queue_depth > self.config.queue_depth_scale_up_threshold
            and now - self._last_scale_up > self.config.scale_up_cooldown_s
        ):
            target = min(current_replicas + 1, self.config.max_replicas)
            if target > current_replicas:
                self._last_scale_up = now
                logger.info(
                    "Scale UP %d → %d (queue_depth=%d)",
                    current_replicas, target, signals.queue_depth,
                )

        elif (
            signals.queue_depth < self.config.queue_depth_scale_down_threshold
            and now - self._last_scale_down > self.config.scale_down_cooldown_s
        ):
            target = max(current_replicas - 1, self.config.min_replicas)
            if target < current_replicas:
                self._last_scale_down = now
                logger.info(
                    "Scale DOWN %d → %d (queue_depth=%d)",
                    current_replicas, target, signals.queue_depth,
                )

        return target

    def apply_scale(self, target_replicas: int) -> None:
        subprocess.run(
            ["docker", "compose", "--profile", "workers", "up", "-d",
             "--scale", f"rag-worker={target_replicas}"],
            check=True,
        )
```

**Key design decisions:**
- Hysteresis and separate cooldowns prevent flapping during transient load spikes.
- Scale-down cooldown is longer than scale-up to favor availability over cost.
- Scale actions use the container orchestrator CLI for compatibility.

---

## B.2: Load Testing Tool

This snippet shows the load testing script with concurrent query submission and SLO gate reporting.

**Tasks:** Task 2.3
**Requirements:** REQ-204, REQ-205

```python
from __future__ import annotations

import asyncio
import statistics
import time
from dataclasses import dataclass


@dataclass
class LoadTestResult:
    total_requests: int
    successful: int
    failed: int
    error_rate: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    rps: float
    duration_s: float
    slo_passed: bool


async def run_load_test(
    url: str,
    total_requests: int = 1000,
    concurrency: int = 100,
    max_error_rate: float = 2.0,
    max_p95_ms: float = 2500.0,
) -> LoadTestResult:
    semaphore = asyncio.Semaphore(concurrency)
    latencies: list[float] = []
    errors: int = 0
    start = time.perf_counter()

    async def submit_query(session, i: int) -> None:
        nonlocal errors
        async with semaphore:
            req_start = time.perf_counter()
            try:
                resp = await session.post(
                    f"{url}/query",
                    json={"query": f"Load test query {i}"},
                )
                elapsed_ms = (time.perf_counter() - req_start) * 1000
                latencies.append(elapsed_ms)
                if resp.status >= 400:
                    errors += 1
            except Exception:
                errors += 1

    tasks = [submit_query(session, i) for i in range(total_requests)]
    await asyncio.gather(*tasks)

    duration = time.perf_counter() - start
    sorted_lat = sorted(latencies) if latencies else [0]

    result = LoadTestResult(
        total_requests=total_requests,
        successful=total_requests - errors,
        failed=errors,
        error_rate=round(errors / total_requests * 100, 2),
        p50_ms=round(sorted_lat[len(sorted_lat) // 2], 1),
        p95_ms=round(sorted_lat[int(len(sorted_lat) * 0.95)], 1),
        p99_ms=round(sorted_lat[int(len(sorted_lat) * 0.99)], 1),
        rps=round(total_requests / duration, 1),
        duration_s=round(duration, 1),
        slo_passed=False,
    )
    result.slo_passed = (
        result.error_rate <= max_error_rate and result.p95_ms <= max_p95_ms
    )
    return result
```

**Key design decisions:**
- SLO gates are configurable to support different deployment sizes.
- Latencies are collected per-request for accurate percentile calculation.
- The tool is designed to run as a standalone script or be called from CI.

---

## B.3: DR Drill Script

This snippet shows the DR drill flow: backup → restore → verify → record.

**Tasks:** Task 4.1, Task 4.2
**Requirements:** REQ-401, REQ-402, REQ-403

```bash
#!/usr/bin/env bash
set -euo pipefail

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="./backups/${TIMESTAMP}"
DRILL_LOG="./backups/drill_log.txt"

echo "[drill] Starting DR drill at ${TIMESTAMP}"

echo "[drill] Phase 1: Backup"
./scripts/backup_all.sh "${BACKUP_DIR}"

echo "[drill] Phase 2: Restore"
./scripts/restore_all.sh "${BACKUP_DIR}"

echo "[drill] Phase 3: Recreate containers"
docker compose up -d

echo "[drill] Phase 4: Verify health"
for i in {1..30}; do
  if curl -fsS "http://localhost:8000/health" >/dev/null 2>&1; then
    echo "[drill] Health check passed"
    break
  fi
  sleep 2
done

echo "[drill] Phase 5: Smoke query"
SMOKE=$(curl -fsS -X POST "http://localhost:8000/query" \
  -H "Content-Type: application/json" \
  -d '{"query":"DR drill smoke test"}' 2>&1) && SMOKE_OK=true || SMOKE_OK=false

if [ "${SMOKE_OK}" = true ]; then
  RESULT="PASS"
else
  RESULT="FAIL"
fi

echo "[drill] Result: ${RESULT}"
echo "${TIMESTAMP} | backup=${BACKUP_DIR} | result=${RESULT}" >> "${DRILL_LOG}"
```

**Key design decisions:**
- The drill runs the full lifecycle unattended for automation compatibility.
- Results are appended to a log file for audit trail.
- Health check loop with retry handles slow container startup.

---

# Part C: Quick-Reference Appendices

## C.1: Disaster Recovery Runbook

### Backup
- Run `./scripts/backup_all.sh`.
- Artifacts are written to `./backups/<timestamp>`.

### Restore
- Run `./scripts/restore_all.sh ./backups/<timestamp>`.
- Recreate containers with `docker compose up -d`.

### Drill
- Run `./scripts/dr_drill.sh`.
- Record date and backup artifact path after each drill.

### Verification
- Check `http://localhost:8000/health`.
- Run one query using `python -m server.cli_client`.
- Open Langfuse and verify traces are visible.

---

## C.2: Secrets Management

### Contract
- Runtime secrets must be loaded via environment variables or `*_FILE`.
- Local `.env` is for development only and must not contain production credentials.

### Required Secrets

| Secret | Purpose |
|--------|---------|
| `RAG_AUTH_JWT_HS256_SECRET` | JWT token signing |
| `LANGFUSE_SECRET_KEY` | Langfuse API authentication |
| `LANGFUSE_NEXTAUTH_SECRET` | Langfuse NextAuth session signing |
| `LANGFUSE_ENCRYPTION_KEY` | Langfuse data encryption |

### Rotation
- Rotate API keys and JWT secret every 90 days.
- On rotation, restart `rag-api` and `rag-worker` services.
- Validate with `/health` and one authenticated query.
