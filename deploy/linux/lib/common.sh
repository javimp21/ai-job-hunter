# Shared settings for the deploy kit. Source it; do not execute it.
# Override any of these by exporting them before running a script.
APP_ROOT="${APP_ROOT:-/opt/ai-job-hunter}"
APP_USER="${APP_USER:-ubuntu}"
SHARED_DIR="${SHARED_DIR:-$APP_ROOT/shared}"      # working directory of every service: .env, data/, private/, *.local.json
RELEASES_DIR="${RELEASES_DIR:-$APP_ROOT/releases}"
CURRENT_LINK="${CURRENT_LINK:-$APP_ROOT/current}"
PREVIOUS_LINK="${PREVIOUS_LINK:-$APP_ROOT/previous}"
LOCK_FILE="${LOCK_FILE:-$SHARED_DIR/data/local/run.lock}"
BACKUP_DIR="${BACKUP_DIR:-$SHARED_DIR/data/local/backups}"
TIMEZONE="${TIMEZONE:-Europe/Madrid}"

log() { printf '%s %s\n' "$(date -Is)" "$*"; }
die() { log "ERROR: $*" >&2; exit 1; }
