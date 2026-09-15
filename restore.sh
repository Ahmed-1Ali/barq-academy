#!/usr/bin/env bash
set -euo pipefail

BACKUP_FILE="${1:-}"
DB_NAME="${DB_NAME:-barq_tasks}"

if [[ -z "$BACKUP_FILE" ]]; then
    echo "FAIL: backup file argument is required" >&2
    echo "Usage: ./restore.sh <backup.sql>" >&2
    exit 1
fi

if [[ ! -f "$BACKUP_FILE" ]]; then
    echo "FAIL: backup file does not exist: $BACKUP_FILE" >&2
    exit 1
fi

if [[ ! -s "$BACKUP_FILE" ]]; then
    echo "FAIL: backup file is empty: $BACKUP_FILE" >&2
    exit 1
fi

if ! docker inspect -f '{{.State.Running}}' postgres 2>/dev/null | grep -qx true; then
    echo "FAIL: postgres container is not running" >&2
    exit 1
fi

echo "Restoring PostgreSQL database from: $BACKUP_FILE"

if ! docker exec -i postgres psql -v ON_ERROR_STOP=1 -U barq_app -d "$DB_NAME" < "$BACKUP_FILE"; then
	#Di bet5aly el restore ye3tebar fachel law 7asal ay SQL error, badal ma yekamel we ye2ool PASS bel ghalat
    echo "FAIL: PostgreSQL restore failed" >&2
    exit 1
fi

echo "PASS: PostgreSQL restore completed successfully"
