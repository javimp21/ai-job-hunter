#!/usr/bin/env bash
# Daily pg_dump (custom format), newest 14 kept. Port of scripts/backup-db.ps1.
# Credentials come from DATABASE_URL in .env via PG* env vars, never argv.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "$here/lib/common.sh"
KEEP="${KEEP:-14}"
mkdir -p "$BACKUP_DIR"
eval "$(python3 "$here/lib/dburl.py" env "$SHARED_DIR/.env")"
name="ai_job_hunter-$(date +%Y%m%d-%H%M).dump"
pg_dump -Fc -f "$BACKUP_DIR/$name.part"
mv "$BACKUP_DIR/$name.part" "$BACKUP_DIR/$name"
ls -1 "$BACKUP_DIR"/ai_job_hunter-*.dump | sort -r | tail -n +"$((KEEP + 1))" | xargs -r rm -f --
log "Backup written: $name ($(du -m "$BACKUP_DIR/$name" | cut -f1) MB)"
