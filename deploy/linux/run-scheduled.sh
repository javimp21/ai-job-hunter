#!/usr/bin/env bash
# Scheduled entry point (port of scripts/run-scheduled.ps1), started by
# ai-job-hunter-run.service. Output goes to journald. Never overlaps: a second
# invocation (or a deploy in progress) skips the run.
# Tunables (set via `systemctl edit ai-job-hunter-run.service`, [Service] Environment=):
#   USER_ALERTS_ENABLED (0: alerts for other signed-up people)  USER_MAX_JEV_JOBS (10)  USER_DAILY_JEV_CAP (150)  USER_MAX_AGE_DAYS (3)  USER_MAX_NOTIFICATIONS (5)  USER_MAX_CANDIDATES (300)  USER_REVIEW_THRESHOLD (global setting)  COMPANY_HUNTER_ENABLED (0)  MAX_JEV_JOBS (40)  MAX_NOTIFICATIONS (10)  DIGEST_FROM_HOUR (20, Madrid time)  WEEKLY_FROM_HOUR (20, Sunday)  RUN_TIMEOUT (55m)
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

# Offers unchanged since the last read are skipped to keep runs short. Once a night (03:00 to 06:00 Madrid time)
# the run re-processes everything (--full-refresh), the safety net after configuration or rule changes.
hour=$(TZ="$TIMEZONE" date +%H)
today=$(TZ="$TIMEZONE" date +%F)
full_marker="$SHARED_DIR/data/local/full-refresh.date"
full_args=()
if [ "$((10#$hour))" -ge 3 ] && [ "$((10#$hour))" -lt 6 ] && [ "$(cat "$full_marker" 2>/dev/null)" != "$today" ]; then
    full_args=(--full-refresh)
    echo "$today" > "$full_marker"
    log "full refresh tonight"
fi

log "run start"
timeout --kill-after=30s "${RUN_TIMEOUT:-55m}" "$exe" run \
    --limit-companies 1000 \
    --max-jobs-per-company 500 \
    --max-jev-jobs "${MAX_JEV_JOBS:-40}" \
    --max-notifications "${MAX_NOTIFICATIONS:-10}" \
    --retry-pending "${full_args[@]}"
code=$?
log "exit=$code"
if [ "$code" -eq 3 ]; then
    # Some sources could not be fetched (e.g. a provider briefly unreachable);
    # the run itself worked, so no Telegram failure notice.
    log "partial: some sources failed (see 'Fetch/ingest failure' lines above)"
    code=0
fi

if [ "${USER_ALERTS_ENABLED:-0}" = 1 ]; then
    # Every other signed-up person: their own evaluation of the offers just read and alerts to their own chat.
    # A failure here never fails the owner's run.
    "$CURRENT_LINK/.venv/bin/python" -m ai_job_hunter.users_cli run --max-jev-jobs "${USER_MAX_JEV_JOBS:-10}"         --daily-jev-cap "${USER_DAILY_JEV_CAP:-150}" --max-age-days "${USER_MAX_AGE_DAYS:-3}"         --max-notifications "${USER_MAX_NOTIFICATIONS:-5}"         --max-candidates "${USER_MAX_CANDIDATES:-300}" ${USER_REVIEW_THRESHOLD:+--review-threshold "$USER_REVIEW_THRESHOLD"} || log "user alerts failed (see above)"
fi

hour=$(TZ="$TIMEZONE" date +%H)
today=$(TZ="$TIMEZONE" date +%F)
marker="$SHARED_DIR/data/local/daily-maintenance.date"
if [ "$((10#$hour))" -ge 7 ] && [ "$(cat "$marker" 2>/dev/null)" != "$today" ]; then
    # Once a day: import monthly lead sources, resolve new company leads, record their boards, and activate
    # boards whose preview has relevant jobs (the rest are re-checked weekly).
    log "daily maintenance"
    # Monthly sources: each command is a cheap no-op unless something is new
    # (HN thread not yet imported once settled; directory changed or 30 days old).
    "$CURRENT_LINK/.venv/bin/python" -m ai_job_hunter.company_leads_cli import-hn --new-only | tail -3 || true
    "$CURRENT_LINK/.venv/bin/python" -m ai_job_hunter.company_leads_cli import-directories --if-due | tail -3 || true
    "$CURRENT_LINK/.venv/bin/python" -m ai_job_hunter.company_leads_cli resolve --limit 100 | tail -12 || true
    "$exe" sources sync || true
    "$exe" sources auto-activate --limit 40 || true
    echo "$today" > "$marker"
fi
dow=$(TZ="$TIMEZONE" date +%u)
hunter_marker="$SHARED_DIR/data/local/company-hunter.date"
# Off until contact extraction is reliable (2026-10-04: menu items were stored as people).
# Enable with COMPANY_HUNTER_ENABLED=1 (systemctl edit ai-job-hunter-run.service).
if [ "${COMPANY_HUNTER_ENABLED:-0}" = 1 ] && [ "$dow" -le 5 ] && [ "$((10#$hour))" -ge 9 ] && [ "$(cat "$hunter_marker" 2>/dev/null)" != "$today" ]; then
    # Weekdays after 09:00, once a day (marker written first so a failure never repeats paid calls
    # every 15 minutes). Mondays also read top companies' public pages and post the weekly
    # "Company Hunter" message. Everything goes to your own Telegram chat; nothing is sent to
    # companies or LinkedIn.
    echo "$today" > "$hunter_marker"
    log "company hunter"
    if [ "$dow" -eq 1 ] || [ "$dow" -eq 4 ]; then
        # The pool of verified people is what limits the daily suggestions, so refill it twice a week.
        "$exe" outreach find-contacts --top 40 || true
    fi
    if [ "$dow" -eq 1 ]; then
        "$exe" outreach weekly --send || true
    fi
    "$exe" outreach connections --send || true
fi
# The owner's free-text opinions become undoable changes of the alerts (needs 3 new notes, at most every 2 days;
# a tick without enough notes costs nothing).
"$exe" notify adapt || true
# New junior-level postings in the countries the owner wants to move to (needs tuning.junior_watch_countries).
"$exe" notify junior-watch || true
if [ "$((10#$hour))" -ge "${DIGEST_FROM_HOUR:-20}" ]; then
    # The command itself sends at most one digest per 20 hours.
    "$exe" notify digest || code=1
fi
if [ "$(TZ="$TIMEZONE" date +%u)" -eq 7 ] && [ "$((10#$hour))" -ge "${WEEKLY_FROM_HOUR:-20}" ]; then
    # Sunday evening. The command itself sends at most one report per 6 days,
    # so every later tick that evening is a no-op.
    "$exe" notify weekly || code=1
    # Claude reads the free-text opinions written since the last review (only with 5 or more new notes) and proposes
    # changes; nothing is applied. It runs after the weekly report, so at most once a week.
    "$exe" notify feedback --min-notes 5 || true
fi

if [ "$code" -ne 0 ]; then
    "$exe" notify system --text "La busqueda programada de las $(TZ="$TIMEZONE" date +%H:%M) fallo (codigo $code). Detalles: journalctl -u ai-job-hunter-run" || true
fi
exit "$code"
