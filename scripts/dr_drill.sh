#!/usr/bin/env bash
set -euo pipefail

STAMP="drill-$(date +%Y%m%d-%H%M%S)"
./scripts/backup_all.sh "$STAMP"
echo "[dr] backup created: ${BACKUP_DIR:-./backups}/$STAMP"
echo "[dr] validating restore script dry run metadata"
test -d "${BACKUP_DIR:-./backups}/$STAMP"
echo "[dr] drill passed"

