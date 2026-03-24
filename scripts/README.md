<!-- @summary
Operations and tooling scripts: container compose wrapper, backup/restore, DR drills, load testing, auto-scaling, tuning signals, and developer utilities.
@end-summary -->

# scripts

## Overview

This directory contains operations and development tooling scripts for running, scaling, and maintaining the RAG stack.

## Container Management

| Script | Purpose |
| --- | --- |
| `compose.sh` | Docker/Podman compose wrapper with auto-runtime detection. **Use this instead of `docker-compose` directly.** Reads `docker-compose.yml` at repo root. |
| `container-runtime.sh` | Detects and exports the active container runtime (`docker` or `podman`). Sourced by `compose.sh`. |
| `restart_stack.sh` | Stops and restarts the compose stack services. |

## TLS / Certificates

| Script | Purpose |
| --- | --- |
| `generate-certs.sh` | Generates mkcert locally-trusted TLS certificates for the nginx HTTPS gateway. Writes to `certs/`. |

## Backup and Recovery

| Script | Purpose |
| --- | --- |
| `backup_all.sh` | Backs up Weaviate vector data and runtime state to a timestamped archive. |
| `restore_all.sh` | Restores Weaviate data and runtime state from a backup archive. |
| `dr_drill.sh` | Disaster recovery drill: runs backup → restore → smoke test cycle. |

## Testing and Load

| Script | Purpose |
| --- | --- |
| `smoke_test.sh` | Basic smoke test against the running API (`/health`, `/query`). |
| `load_test_api.py` | Concurrency load test with configurable SLO assertions (max error rate, max p95 latency). |

## Scaling and Tuning

| Script | Purpose |
| --- | --- |
| `auto_scale_workers.py` | Auto-scales `rag-worker` replicas based on Temporal queue and API p95 saturation signals. |
| `watch_tuning_signals.py` | Continuously watches Temporal/Prometheus/GPU signals and emits scaling recommendations. |

## Developer Utilities

| Script | Purpose |
| --- | --- |
| `ollama_host_proxy.py` | Proxy that forwards Ollama requests from containers to the host Ollama service (avoids `host.docker.internal` config). |
| `warmup_docling_models.py` | Pre-downloads Docling layout and TableFormer models before ingestion runs. |
| `temporal_worker.py` | Convenience script to start a Temporal worker (alternative to `python -m server.worker`). |
| `format_spec_fr_blocks.py` | Developer utility: normalizes FR block formatting in spec Markdown documents. |

## Usage Examples

```bash
# Start infrastructure (auto-detects Docker vs Podman)
./scripts/compose.sh up -d

# Full stack with monitoring
./scripts/compose.sh --profile app --profile workers --profile monitoring up -d

# Run load test with SLO checks
python scripts/load_test_api.py --url http://localhost:8000 --total-requests 1000 --concurrency 100

# Preview auto-scale decisions without applying
python scripts/auto_scale_workers.py --dry-run
```
