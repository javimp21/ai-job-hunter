#!/usr/bin/env bash
# Deploy a git ref to the server, like scripts/deploy-stable.ps1.
#   ./deploy/linux/deploy.sh [ref]        # default: origin/main
#   ./deploy/linux/deploy.sh --rollback   # switch back to the previous release
#   NO_START=1 ./deploy/linux/deploy.sh  # build + migrate but do not start the bot/timers (pre-cut-over)
# Run as the app user (not root) from the repository checkout; it needs sudo
# only for systemctl and installing units.
#
# Order matters (migrate-before-deploy): build the release -> alembic upgrade
# head with the NEW code against the live database -> only then atomically
# switch the `current` symlink -> restart the bot. A failed build or migration
# leaves `current` untouched.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
. "$here/lib/common.sh"
[ "$(id -u)" -ne 0 ] || die "run as $APP_USER, not root"

restart_bot() {
    sudo systemctl restart ai-job-hunter-bot.service
    sleep 5
    systemctl is-active --quiet ai-job-hunter-bot.service || die "bot is not active; check: journalctl -u ai-job-hunter-bot -n 50"
}

mkdir -p "$SHARED_DIR/data/local" "$BACKUP_DIR"
exec 9>"$LOCK_FILE"

if [ "${1:-}" = "--rollback" ]; then
    [ -L "$PREVIOUS_LINK" ] || die "no previous release recorded"
    flock -w 1200 9 || die "a run still holds the lock after 20 minutes"
    cur="$(readlink -f "$CURRENT_LINK")"; prev="$(readlink -f "$PREVIOUS_LINK")"
    ln -sfn "$prev" "$CURRENT_LINK.new" && mv -T "$CURRENT_LINK.new" "$CURRENT_LINK"
    ln -sfn "$cur" "$PREVIOUS_LINK"
    restart_bot
    log "rolled back to $(basename "$prev"). Database migrations are NOT undone; restore a dump if the schema must go back (docs/SERVER.md)."
    exit 0
fi

ref="${1:-origin/main}"
repo="${REPO_DIR:-$(git -C "$here" rev-parse --show-toplevel)}"
[ -f "$SHARED_DIR/.env" ] || die "$SHARED_DIR/.env is missing (see docs/SERVER.md)"
if grep -q $'\r' "$SHARED_DIR/.env"; then
    die ".env has CRLF line endings; run: sed -i 's/\\r\$//' $SHARED_DIR/.env"
fi
PYTHON="${PYTHON:-$(cat /etc/ai-job-hunter/python 2>/dev/null || echo python3.13)}"
"$PYTHON" --version >/dev/null || die "Python 3.13 not found; run bootstrap.sh"

log "fetching origin"
git -C "$repo" fetch --quiet --prune origin
sha="$(git -C "$repo" rev-parse --verify "${ref}^{commit}")" || die "unknown ref: $ref"
short="${sha:0:12}"
release="$RELEASES_DIR/$short"
log "deploying $ref -> $short"

if [ -f "$release/.complete" ]; then
    log "release $short already built; reusing it"
else
    rm -rf "$release"
    mkdir -p "$release"
    trap 'rc=$?; [ $rc -ne 0 ] && [ ! -f "$release/.complete" ] && rm -rf "$release"; exit $rc' EXIT
    git -C "$repo" archive "$sha" | tar -x -C "$release"
    # The venv must be created at its final path (entry-point shebangs are absolute).
    "$PYTHON" -m venv "$release/.venv"
    "$release/.venv/bin/pip" install -q --no-cache-dir --upgrade pip
    (cd "$release" && .venv/bin/pip install -q --no-cache-dir ".[jev,llm]")
    ln -s "$SHARED_DIR/.env" "$release/.env"   # pydantic and alembic read .env from the cwd
    "$release/.venv/bin/ai-job-hunter" --help >/dev/null
    touch "$release/.complete"
fi

# Hold the run lock so no scheduled run sees a half-switched state.
log "waiting for the run lock (up to 20 minutes)"
flock -w 1200 9 || die "a run still holds the lock after 20 minutes; nothing was changed"

if [ "${SKIP_BACKUP:-0}" != "1" ] && [ -f "$CURRENT_LINK/.complete" ]; then
    "$here/backup-db.sh"
fi

log "migrating the database (alembic upgrade head)"
(cd "$release" && .venv/bin/alembic upgrade head)

log "switching current -> $short"
old="$(readlink -f "$CURRENT_LINK" 2>/dev/null || true)"
ln -sfn "$release" "$CURRENT_LINK.new" && mv -T "$CURRENT_LINK.new" "$CURRENT_LINK"
if [ -n "$old" ] && [ "$old" != "$release" ]; then ln -sfn "$old" "$PREVIOUS_LINK"; fi

sudo "$release/deploy/linux/lib/install-units.sh" "$release/deploy/linux/systemd"
if [ "${NO_START:-0}" = "1" ]; then
    log "NO_START=1: units installed but the bot and timers were NOT enabled or started"
else
    sudo systemctl enable --now ai-job-hunter-run.timer ai-job-hunter-backup.timer >/dev/null
    sudo systemctl enable ai-job-hunter-bot.service >/dev/null
    restart_bot
fi

echo "$short $(date -Is)" > "$SHARED_DIR/data/local/stable-version.txt"

# Keep the 4 newest releases plus current and previous.
keep="$(readlink -f "$CURRENT_LINK") $(readlink -f "$PREVIOUS_LINK" 2>/dev/null || true)"
ls -1dt "$RELEASES_DIR"/*/ 2>/dev/null | sed 's:/$::' | tail -n +5 | while read -r dir; do
    case " $keep " in *" $dir "*) ;; *) rm -rf "$dir" ;; esac
done
log "deployed $short. Logs: journalctl -u ai-job-hunter-bot -f"
