#!/bin/sh
# LiteLLM spend-log maintenance script.
# Deletes spend log rows older than LITELLM_LOG_RETENTION_DAYS (default: 90).
# Runs once at startup, then every 24 hours.
#
# Called by: Docker Compose (pg-maintenance container, profile: app).
# Scheduling: the sleep loop below is the scheduler — no cron daemon needed.
set -e

RETENTION_DAYS="${LITELLM_LOG_RETENTION_DAYS:-90}"
HOST="${PGHOST:-rag-postgres}"
USER="${PGUSER:-litellm}"
DB="${PGDATABASE:-litellm}"

echo "[litellm-maintenance] Waiting for PostgreSQL at ${HOST}..."
until pg_isready -h "${HOST}" -U "${USER}"; do
    sleep 5
done

echo "[litellm-maintenance] Starting cleanup loop (retention: ${RETENTION_DAYS} days, runs every 24h)"
while true; do
    echo "[litellm-maintenance] $(date -u '+%Y-%m-%dT%H:%M:%SZ') — deleting spend logs older than ${RETENTION_DAYS} days..."
    psql -h "${HOST}" -U "${USER}" -d "${DB}" \
        -c "DELETE FROM litellmspendlogs WHERE startTime < NOW() - (${RETENTION_DAYS} || ' days')::INTERVAL;" \
        2>&1 || echo "[litellm-maintenance] Skipped (table may not exist yet)"
    echo "[litellm-maintenance] Next run in 24h"
    sleep 86400
done
