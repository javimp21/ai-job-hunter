#!/usr/bin/env bash
# Scheduled entry point (port of scripts/run-scheduled.ps1), started by
# ai-job-hunter-run.service. Output goes to journald. Never overlaps: a second
# invocation (or a deploy in progress) skips the run.
# Tunables (set via `systemctl edit ai-job-hunter-run.service`, [Service] Environment=):
#   MAX_JEV_JOBS (40)  MAX_NOTIFICATIONS (10)  DIGEST_FROM_HOUR (20, Madrid time)  WEEKLY_FROM_HOUR (20, Sunday)  RUN_TIMEOUT (55m)
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
if [ "$code" -eq 3 ]; then
    # Some sources could not be fetched (e.g. a provider briefly unreachable);
    # the run itself worked, so no Telegram failure notice.
    log "partial: some sources failed (see 'Fetch/ingest failure' lines above)"
    code=0
fi

hour=$(TZ="$TIMEZONE" date +%H)
today=$(TZ="$TIMEZONE" date +%F)
marker="$SHARED_DIR/data/local/daily-maintenance.date"
if [ "$((10#$hour))" -ge 7 ] && [ "$(cat "$marker" 2>/dev/null)" != "$today" ]; then
    # Once a day: resolve new company leads, record their boards, and activate
    # boards whose preview has relevant jobs (the rest are re-checked weekly).
    log "daily maintenance"
    "$CURRENT_LINK/.venv/bin/python" -m ai_job_hunter.company_leads_cli resolve --limit 100 | tail -12 || true
    "$exe" sources sync || true
    "$exe" sources auto-activate --limit 40 || true
    echo "$today" > "$marker"
fi
if [ "$((10#$hour))" -ge "${DIGEST_FROM_HOUR:-20}" ]; then
    # The command itself sends at most one digest per 20 hours.
    "$exe" notify digest || code=1
fi
if [ "$(TZ="$TIMEZONE" date +%u)" -eq 7 ] && [ "$((10#$hour))" -ge "${WEEKLY_FROM_HOUR:-20}" ]; then
    # Sunday evening. The command itself sends at most one report per 6 days,
    # so every later tick that evening is a no-op.
    "$exe" notify weekly || code=1
fi

if [ "$code" -ne 0 ]; then
    "$exe" notify system --text "La busqueda programada de las $(TZ="$TIMEZONE" date +%H:%M) fallo (codigo $code). Detalles: journalctl -u ai-job-hunter-run" || true
fi
exit "$code"
