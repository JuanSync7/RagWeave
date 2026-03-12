# Disaster Recovery Runbook

## Backup
- Run `./scripts/backup_all.sh`.
- Artifacts are written to `./backups/<timestamp>`.

## Restore
- Run `./scripts/restore_all.sh ./backups/<timestamp>`.
- Recreate containers with `docker compose up -d`.

## Drill
- Run `./scripts/dr_drill.sh`.
- Record date and backup artifact path after each drill.

## Verification
- Check `http://localhost:8000/health`.
- Run one query using `python -m server.cli_client`.
- Open Langfuse and verify traces are visible.

