#!/usr/bin/env bash
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-backups}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
BACKUP_FILE="${BACKUP_DIR}/barq_tasks_${TIMESTAMP}.sql"

mkdir -p "$BACKUP_DIR"

if ! docker inspect -f '{{.State.Running}}' postgres 2>/dev/null | grep -qx true; then
    echo "FAIL: postgres container is not running" >&2
    exit 1
fi

echo "Creating PostgreSQL backup: $BACKUP_FILE"

if ! docker exec postgres pg_dump -U barq_app -d barq_tasks > "$BACKUP_FILE"; then
    echo "FAIL: PostgreSQL backup failed" >&2
    rm -f "$BACKUP_FILE"
    exit 1
fi

if [[ ! -s "$BACKUP_FILE" ]]; then
    echo "FAIL: backup file is empty" >&2
    rm -f "$BACKUP_FILE"
    exit 1
fi

echo "PASS: PostgreSQL backup created successfully"
echo "Backup: $BACKUP_FILE"
echo "Size: $(du -h "$BACKUP_FILE" | cut -f1)"
