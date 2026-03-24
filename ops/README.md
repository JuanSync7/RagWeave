<!-- @summary
Infrastructure service configuration files for Prometheus, Grafana, Alertmanager, nginx, and PostgreSQL. Mounted into containers by docker-compose.yml.
@end-summary -->

# ops

## Overview

This directory contains configuration files for the infrastructure services used by the RAG stack. Files here are mounted read-only into the relevant service containers via `docker-compose.yml`.

## Subdirectories

| Directory | Contents | Service |
| --- | --- | --- |
| `prometheus/` | `prometheus.yml` (scrape config) + `alerts.yml` (alerting rules) | `prometheus` container |
| `grafana/` | Dashboard JSON definitions + provisioning datasource/dashboard config | `grafana` container |
| `alertmanager/` | `alertmanager.yml` (alert routing and receivers config) | `alertmanager` container |
| `nginx/` | `nginx.conf` (HTTPS reverse proxy config for `gateway` compose profile) | `rag-nginx` container |
| `postgres/` | `postgresql.conf` (PostgreSQL tuning — connections, memory, WAL, autovacuum) | `temporal-db` and `rag-postgres` containers |

## Usage

To apply configuration changes:
1. Edit the relevant file in `ops/`.
2. Restart the affected container:
   ```bash
   ./scripts/compose.sh restart <service-name>
   ```

For Prometheus alert rule changes, reload without restart:
```bash
curl -X POST http://localhost:9091/-/reload
```

## Monitoring Stack URLs (when running)

| Service | URL |
| --- | --- |
| Prometheus | http://localhost:9091 |
| Grafana | http://localhost:3001 |
| Alertmanager | http://localhost:9093 |
