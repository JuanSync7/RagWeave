# RAG 100-User Execution Plan (Practical)

This plan focuses on high-impact controls needed to run the current stack reliably for around 100 concurrent users without overengineering.

## Scope and Principles

- Prefer controls that are enforceable in code and observable with current tooling.
- Keep latency predictable under load by rejecting overload quickly instead of allowing queue collapse.
- Separate "implemented now" from "needs environment-specific values".

## Implemented in This Cycle

1. API overload guardrails:
   - Added bounded in-flight request protection for `/query` and `/query/stream`.
   - Added short queue wait timeout before rejecting with `503` when saturated.
2. Prometheus overload signals:
   - `rag_api_inflight_requests` gauge.
   - `rag_api_overload_rejections_total{endpoint=...}` counter.
3. Practical load-testing script:
   - Added `scripts/load_test_api.py` for concurrent `/query` testing with SLO checks.
4. Regression coverage:
   - Added API test to verify overload path returns standard error envelope.
5. Worker autoscaling loop:
   - Added `scripts/auto_scale_workers.py` to scale `rag-worker` replicas up/down from live Prometheus and runtime signals with hysteresis and cooldowns.

## Execution Plan

## Phase 1 - Capacity Boundaries (Done)

### Objective
Protect service stability when concurrent load spikes.

### Controls
- `RAG_API_MAX_INFLIGHT_REQUESTS`: max requests allowed in active execution window.
- `RAG_API_OVERLOAD_QUEUE_TIMEOUT_MS`: max wait to acquire a slot before `503`.

### Acceptance Criteria
- Under overload, requests fail fast with `503` and standard API error schema.
- In-flight metric plateaus near configured max instead of unbounded growth.

## Phase 2 - Load Validation (Executable Now)

### Objective
Verify p95 latency and error-rate behavior at target concurrency.

### Command

```bash
python scripts/load_test_api.py \
  --url http://localhost:8000 \
  --total-requests 1000 \
  --concurrency 100 \
  --max-error-rate 2.0 \
  --max-p95-ms 2500
```

### What to Record
- `error_rate`, `p50`, `p95`, `p99`, `rps`.
- Prometheus:
  - `rag_api_request_latency_ms`
  - `rag_api_requests_total`
  - `rag_api_inflight_requests`
  - `rag_api_overload_rejections_total`

### Pass/Fail Gate
- Pass if `error_rate <= 2%` and `p95 <= 2500ms` with no sustained queue growth.

## Phase 3 - Tuning Loop (Executable Now)

### Objective
Tune worker replicas and concurrency based on observed saturation points.

### Commands

```bash
# Watch tuning signals
python scripts/watch_tuning_signals.py --interval-seconds 30

# Scale worker replicas
./scripts/compose.sh --profile workers up -d --scale rag-worker=3

# Run conservative autoscaling loop
python scripts/auto_scale_workers.py --min-replicas 1 --max-replicas 6
```

### Tuning Heuristics
- If schedule-to-start latency rises and backlog grows: add worker replicas first.
- If GPU memory pressure spikes: reduce per-worker concurrency.
- If overload rejects remain high despite normal worker stats: raise API in-flight cap carefully.
- For automatic downscale, require sustained cool signals and a longer downscale cooldown to avoid flapping.

## Phase 4 - Production Inputs (Needs Your Environment Values)

These require environment-specific numbers and policy decisions:

- Final SLO contract (e.g., p95 and p99 by endpoint, acceptable error budget).
- Tenant quota policy (default and overrides by customer tier).
- Alert routing destinations and escalation policy.
- Rollback threshold for automated deploy gates.

## Suggested Baseline Values

Start with:

- `RAG_API_MAX_INFLIGHT_REQUESTS=64`
- `RAG_API_OVERLOAD_QUEUE_TIMEOUT_MS=250`
- `RAG_WORKER_CONCURRENCY=4`
- `RAG_RATE_LIMIT_REQUESTS_PER_MINUTE=60` (or tier-specific quota)

Then calibrate after a 100-user load test, not before.

## Operational Checklist

- [ ] API health stable for 30+ minutes under background load.
- [ ] Load test passes SLO gate at 100 concurrency.
- [ ] Overload reject counter remains near zero during normal traffic.
- [ ] Tuning watcher produces no critical alerts.
- [ ] DR restore smoke (`/health` + one query) still succeeds post-change.
