# Running on an always-on Linux server

Target: Oracle Cloud Always Free, Ubuntu 24.04, SSH user `ubuntu`
(`VM.Standard.A1.Flex` 1 OCPU / 6 GB ARM64, or `VM.Standard.E2.1.Micro` 1 GB AMD64).
PostgreSQL runs natively (no Docker) to save RAM; the bootstrap adds a 2 GB swapfile when RAM < 2 GB.
Application behaviour is unchanged: the same `ai-job-hunter run`, `notify digest`, `notify system` and `bot` commands, driven by systemd instead of Windows Task Scheduler.

## Layout on the server

```text
/opt/ai-job-hunter/
  repo/                  git clone (deploy key); deploy scripts run from here
  releases/<sha12>/      one non-editable release each: source + .venv (+ .env symlink)
  current -> releases/…  atomic symlink; previous -> prior release (for rollback)
  shared/                WORKING DIRECTORY of every service (the app reads paths relative to it)
    .env  candidate*.local.json  private/  data/local/…
```

Everything private lives in `shared/` and survives deploys. Nothing in it is committed.

## 1. Bootstrap the host (once)

```bash
ssh ubuntu@<server-ip>
sudo mkdir -p /opt/ai-job-hunter && sudo chown ubuntu:ubuntu /opt/ai-job-hunter
git clone git@github.com:javimp21/ai-job-hunter.git /opt/ai-job-hunter/repo   # private repo: add a read-only deploy key first
sudo /opt/ai-job-hunter/repo/deploy/linux/bootstrap.sh
```

`bootstrap.sh` is idempotent. It sets the timezone to Europe/Madrid, installs Python 3.13 (deadsnakes PPA; falls back to a standalone Python from `uv` if the PPA is unavailable), PostgreSQL 16 with a small-memory profile, swap, unattended-upgrades and `ufw` (only 22/tcp). It creates the role and database named in `DATABASE_URL` from `shared/.env` without printing it. On the first run `.env` is not there yet, so it warns; **re-run it after step 2**.

Also keep the Oracle VCN security list limited to TCP 22.

## 2. Copy secrets and private data from Windows

Run in PowerShell **from the repository root** on Windows (OpenSSH `scp` ships with Windows 10/11). Replace `$KEY` and the IP.

```powershell
$S   = "ubuntu@<server-ip>"
$KEY = "$HOME\.ssh\oracle_key"
$D   = "/opt/ai-job-hunter/shared"
$O   = @("-i", $KEY)
```

Files the application reads (all relative to the working directory). Copy those that exist; missing optional ones are fine.

| What | Path (repo root) | Needed by | Copy |
|---|---|---|---|
| Secrets and settings | `.env` | everything | required |
| Candidate profile | `candidate.local.json` | run, notify, bot | required |
| CV metadata | `candidate_documents.local.json` | bot (cover letters) | required |
| Application facts | `candidate_application.local.json` | bot (cover letters) | required |
| Writing style config | `candidate_writing.local.json` | cover letters / application prep | if present |
| Outreach projects | `candidate_projects.local.json` | outreach | if present |
| Style guide + CV PDF | `private/` (`WRITING.md`, the CV `.pdf`) | cover letters | required |
| Generated cover letters | `data/local/cover-letters/` | bot (re-send) | recommended |
| Job-portal cursor | `data/local/portal-state.json` | run (Himalayas) | required (avoids re-fetch/duplicates) |
| Bot update offset | `data/local/telegram-bot-offset.json` | bot | required (avoids replaying old taps) |
| Jev decision cache | `data/local/job-decision-cache.local.json` | run (saves paid Jev calls) | recommended |
| Application drafts/sessions | `data/local/application-packages.local.json`, `data/local/application-sessions.local.json` | application prep | if present |
| Company intelligence | `data/local/company-intelligence/` | company commands | if present |
| Human labels | `human-labels.local.json` | label tooling | if present |

Not needed on the server: `data/local/logs`, `data/local/backups`, `data/local/stable-*`, the benchmark/snapshot files used only by `policy_comparison`, `.venv*`.

The CV PDF is whatever `local_path` says in `candidate_documents.local.json`. List it, and make sure it is **inside the copied tree**:

```powershell
Select-String -Path candidate_documents.local.json -Pattern '"local_path"'
```

Do the final copy **after** disabling the Windows tasks (step 4), so `portal-state.json`, the offset and the database are not changing underneath you. A rehearsal copy earlier is fine, just repeat it at cut-over.

```powershell
# files (skip any that do not exist)
foreach ($f in "candidate.local.json","candidate_documents.local.json","candidate_application.local.json",
               "candidate_writing.local.json","candidate_projects.local.json","human-labels.local.json") {
    if (Test-Path $f) { scp @O $f "${S}:$D/" }
}
scp @O .env "${S}:$D/.env"

# directories
scp @O -r private "${S}:$D/"
ssh @O $S "mkdir -p $D/data/local"
foreach ($f in "portal-state.json","telegram-bot-offset.json","job-decision-cache.local.json",
               "application-packages.local.json","application-sessions.local.json") {
    if (Test-Path "data\local\$f") { scp @O "data\local\$f" "${S}:$D/data/local/" }
}
foreach ($d in "cover-letters","company-intelligence") {
    if (Test-Path "data\local\$d") { scp @O -r "data\local\$d" "${S}:$D/data/local/" }
}
```

Then fix up on the server:

```bash
cd /opt/ai-job-hunter/shared
sed -i 's/\r$//' .env candidate*.local.json     # CRLF breaks systemd's EnvironmentFile
chmod 600 .env && chmod -R go-rwx .
# 1) DATABASE_URL must still point at localhost (the bootstrap refuses anything else).
# 2) Windows paths do not work here: make the CV path relative to this directory, e.g. "private/cv.pdf".
grep -n '"local_path"' candidate_documents.local.json
grep -nE 'C:\\|\\\\' candidate*.local.json .env || echo "no Windows paths left"
test -f "$(python3 -c 'import json;print(json.load(open("candidate_documents.local.json"))["documents"][0]["local_path"])')" && echo "CV found"
sudo /opt/ai-job-hunter/repo/deploy/linux/bootstrap.sh   # re-run: creates the role/database now that .env exists
```

Consider choosing a stronger database password than the compose default (`ai_job_hunter`): edit `DATABASE_URL` in the server `.env` and re-run the bootstrap, which syncs the role password. PostgreSQL only listens on localhost.

## 3. Database: dump on Windows, restore on the server

On Windows, in the repo root (the container is the `postgres` service of `compose.yml`). Do this after disabling the tasks (step 4).

```powershell
$name = "migrate-$(Get-Date -Format yyyyMMdd-HHmm).dump"
docker compose exec -T postgres pg_dump -U ai_job_hunter -d ai_job_hunter -Fc -f "/tmp/$name"
docker compose cp "postgres:/tmp/$name" ".\data\local\$name"
docker compose exec -T postgres rm -f "/tmp/$name"
scp @O ".\data\local\$name" "${S}:/opt/ai-job-hunter/shared/data/local/backups/$name"
```

On the server, restore into the empty database the bootstrap created (credentials come from `.env` into `PG*` variables, never argv):

```bash
cd /opt/ai-job-hunter/shared
eval "$(python3 /opt/ai-job-hunter/repo/deploy/linux/lib/dburl.py env .env)"
pg_restore --no-owner --no-privileges --exit-on-error -d "$PGDATABASE" data/local/backups/migrate-*.dump
psql -c '\dt'                                   # sanity check: tables are present
```

If you need to redo it on a non-empty database add `--clean --if-exists`. The first deploy runs `alembic upgrade head`, so a dump from an older schema is migrated forward.

## 4. Cut-over (order matters)

Telegram allows one `getUpdates` poller per bot. Two pollers make both lose taps, and two runners can double-alert, so the Windows side is stopped **first**.

1. **Windows, PowerShell as the same user** — disable and stop both tasks, and kill any bot already running:
   ```powershell
   Disable-ScheduledTask -TaskName "AI Job Hunter"
   Disable-ScheduledTask -TaskName "AI Job Hunter Bot"
   Stop-ScheduledTask -TaskName "AI Job Hunter" -ErrorAction SilentlyContinue
   Stop-ScheduledTask -TaskName "AI Job Hunter Bot" -ErrorAction SilentlyContinue
   Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match "run-bot.ps1|ai-job-hunter(\.exe)?\W+.*\bbot\b" } |
       ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
   Get-ScheduledTask "AI Job Hunter*" | Select TaskName, State      # both must be Disabled
   ```
   Leave the Windows Docker database running until the server is verified.
2. **Windows** — dump the database and copy files (steps 2 and 3).
3. **Server** — restore (step 3), then build and migrate **without starting anything**, and check:
   ```bash
   cd /opt/ai-job-hunter/repo && git pull --ff-only
   NO_START=1 ./deploy/linux/deploy.sh                # build, alembic upgrade head, switch current
   cd /opt/ai-job-hunter/shared
   ../current/.venv/bin/ai-job-hunter notify pending --limit 5
   ../current/.venv/bin/ai-job-hunter run --dry-run --limit-companies 3   # no DB writes, no Jev, no Telegram
   ```
4. **Server** — go live (starts the bot and both timers):
   ```bash
   ./deploy/linux/deploy.sh      # same release is reused; enables and starts bot + timers
   systemctl status ai-job-hunter-bot --no-pager
   systemctl list-timers 'ai-job-hunter-*'
   sudo systemctl start ai-job-hunter-run.service   # optional immediate run
   ```
5. Tap a button on a recent Telegram alert to confirm the bot answers; check `journalctl -u ai-job-hunter-bot -n 50`.
6. Keep the Windows tasks disabled and the Windows database untouched for a few days as the rollback.

## Schedule

`ai-job-hunter-run.timer` (times are Europe/Madrid, independent of the host timezone):

| Window | Frequency |
|---|---|
| Monday-Friday 06:45-01:00 | every 15 minutes |
| Saturday-Sunday 08:00-00:00 | hourly |
| Nights (01:00-06:45 weekdays, 01:00-08:00 weekends) | every 2 hours (01, 03, 05, and 07 on weekends) |

Each tick runs `ai-job-hunter run --limit-companies 1000 --max-jobs-per-company 500 --max-jev-jobs 40 --max-notifications 10 --retry-pending` under `flock` (`shared/data/local/run.lock`): a tick that finds a run or a deploy in progress logs and skips. A run is capped at 55 minutes. When the local hour is >= 20 it then runs `ai-job-hunter notify digest` (which itself sends at most one digest per 20 hours). A non-zero exit sends `ai-job-hunter notify system --text …` to Telegram, like `run-scheduled.ps1`.

Once a day, in the first run at or after 07:00, `run-scheduled.sh` also does source maintenance: `company_leads_cli import-hn --new-only` (the newest Hacker News "Who is hiring?" thread; re-imported daily, deduplicated, until it is 7 days old because comments keep arriving, then skipped until next month's thread), `company_leads_cli import-directories --if-due` (Manfred and Spanish Top Tech README snapshots: looked at at most weekly, imported only when the content changed or 30 days passed; state in `shared/data/local/lead-import-state.json`), `company_leads_cli resolve --limit 100` (new company leads), `sources sync` and `sources auto-activate --limit 40`. Auto-activation previews boards in REVIEW_SOURCE and activates those with at least one job the deterministic prefilter does not reject (the reason and numbers are stored on the source); boards without relevant jobs stay in review and are re-checked weekly; rejected or paused boards are never touched. The day is recorded in `shared/data/local/daily-maintenance.date`.

`ai-job-hunter-backup.timer` runs `backup-db.sh` daily at 23:50 (pg_dump `-Fc` into `shared/data/local/backups`, newest 14 kept; a failure sends a Telegram notice). `deploy.sh` also takes a dump before each migration.

**Change the schedule** without editing the repo:

```bash
sudo systemctl edit ai-job-hunter-run.timer
```
```ini
[Timer]
OnCalendar=
OnCalendar=*-*-* 08..22:00:00 Europe/Madrid
```
Check with `systemd-analyze calendar "<expr>" --iterations=5`. Run limits and digest hour are environment variables of the run service (`sudo systemctl edit ai-job-hunter-run.service`, `[Service]` then `Environment=MAX_JEV_JOBS=20 MAX_NOTIFICATIONS=10 DIGEST_FROM_HOUR=20 RUN_TIMEOUT=55m`). Note that 15-minute runs multiply Jev and Telegram usage versus the old 2-hour cadence; `--max-jev-jobs` is per run.

## Deploying changes

```bash
cd /opt/ai-job-hunter/repo
git pull --ff-only                 # refreshes the deploy scripts themselves
./deploy/linux/deploy.sh           # default ref origin/main; or: ./deploy/linux/deploy.sh origin/some-branch / a tag / a sha
```

It fetches, extracts that commit into `releases/<sha12>`, creates a fresh non-editable venv (`pip install ".[jev,llm]"`), waits for the run lock (up to 20 minutes), dumps the database, runs `alembic upgrade head` with the **new** code, and only then atomically switches `current`, reinstalls units if they changed and restarts the bot. A failure before the switch leaves the running release untouched. The deployed commit is recorded in `shared/data/local/stable-version.txt` (`<sha12> <timestamp>`), and the last four releases are kept.

## Logs and operations

```bash
journalctl -u ai-job-hunter-bot -f                  # bot, live
journalctl -u ai-job-hunter-run -n 200 --no-pager   # last runs
journalctl -u ai-job-hunter-run --since today
journalctl -u ai-job-hunter-run -p err --since "7 days ago"
journalctl -u ai-job-hunter-backup --since "2 days ago"
systemctl list-timers 'ai-job-hunter-*'
systemctl status ai-job-hunter-bot
sudo systemctl start ai-job-hunter-run.service      # run now
sudo systemctl disable --now ai-job-hunter-run.timer   # pause scheduled runs
sudo journalctl --vacuum-time=30d                   # trim logs (journald caps itself, but small disks fill)
cat /opt/ai-job-hunter/shared/data/local/stable-version.txt
```

CLI by hand (same environment as the services):

```bash
cd /opt/ai-job-hunter/shared && ../current/.venv/bin/ai-job-hunter notify history --limit 20
```

## Rollback

**Bad release** (code problem, schema unchanged or compatible):
```bash
/opt/ai-job-hunter/repo/deploy/linux/deploy.sh --rollback    # current <-> previous, restarts the bot
```
Migrations are not reverted. If a migration must be undone, restore the pre-deploy dump taken by `deploy.sh`: stop the services, `pg_restore --clean --if-exists --no-owner -d "$PGDATABASE" <dump>` (credentials as in step 3), then roll back the release.

**Back to Windows** (server abandoned or broken):
1. Stop the server first: `sudo systemctl disable --now ai-job-hunter-bot ai-job-hunter-run.timer ai-job-hunter-backup.timer`.
2. To keep what the server found since cut-over, dump it (`backup-db.sh`, or `pg_dump -Fc` as in step 3), `scp` it to Windows, then `docker compose cp` it into the container and `pg_restore --clean --if-exists --no-owner -U ai_job_hunter -d ai_job_hunter`. Also copy back `data/local/portal-state.json` and `data/local/telegram-bot-offset.json`. Skipping this means the Windows database is stale and may re-alert jobs the server already sent.
3. `Enable-ScheduledTask -TaskName "AI Job Hunter"; Enable-ScheduledTask -TaskName "AI Job Hunter Bot"; Start-ScheduledTask -TaskName "AI Job Hunter Bot"`.

## Security notes

- `shared/` and `.env` are mode 600/750 and owned by `ubuntu`; the repo's `.gitignore` already excludes all of it. Never commit `.env`, `*.local.*`, `private/` or `data/`.
- `ufw` allows only SSH; PostgreSQL is bound to localhost. Unattended-upgrades does not reboot automatically; reboot manually after kernel updates (all units are enabled and come back by themselves).
- Services run as `ubuntu` with `NoNewPrivileges`, `PrivateTmp`, `ProtectSystem=full`, `ProtectHome`.
