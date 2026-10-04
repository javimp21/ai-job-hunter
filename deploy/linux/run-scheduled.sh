#!/usr/bin/env bash
# Scheduled entry point (port of scripts/run-scheduled.ps1), started by
# ai-job-hunter-run.service. Output goes to journald. Never overlaps: a second
# invocation (or a deploy in progress) skips the run.
# Tunables (set via `systemctl edit ai-job-hunter-run.service`, [Service] Environment=):
#   MAX_JEV_JOBS (40)  MAX_NOTIFICATIONS (10)  DIGEST_FROM_HOUR (20, Madrid time)  RUN_TIMEOUT (55m)
set -uo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "$here/lib/common.sh"
exe="$CURRENT_LINK/.venv/bin/ai-job-hunter"
cd "$SHARED_DIR"
export PYTHONIOENCODING=utf-8 PYTHONUNBUFFERED=1

mkdir -p "$(dirname "$LOCK_FILE")"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    log "another run or a deploy holds the lock; skipping this run"
    exit 0
fi

log "run start"
timeout --kill-after=30s "${RUN_TIMEOUT:-55m}" "$exe" run \
    --limit-companies 1000 \
    --max-jobs-per-company 500 \
    --max-jev-jobs "${MAX_JEV_JOBS:-40}" \
    --max-notifications "${MAX_NOTIFICATIONS:-10}" \
    --retry-pending
code=$?
log "exit=$code"

hour=$(TZ="$TIMEZONE" date +%H)
if [ "$((10#$hour))" -ge "${DIGEST_FROM_HOUR:-20}" ]; then
    # The command itself sends at most one digest per 20 hours.
    "$exe" notify digest || code=1
fi

if [ "$code" -ne 0 ]; then
    "$exe" notify system --text "La busqueda programada de las $(TZ="$TIMEZONE" date +%H:%M) fallo (codigo $code). Detalles: journalctl -u ai-job-hunter-run" || true
fi
exit "$code"
