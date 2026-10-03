# Telegram opportunity notifications

Telegram delivery is optional. Copy the blank settings from `.env.example` into the ignored `.env` file and set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` there. Never commit `.env` or paste the token into a command line, issue, or log. The review threshold is configured with `NOTIFY_REVIEW_MIN_PRIORITY` and defaults to `70`; every `APPLY` is eligible, and a `REVIEW` is eligible only at or above that threshold. `SKIP` and `PENDING` are never eligible.

Preview candidates without writing notification rows or contacting Telegram:

```powershell
ai-job-hunter notify send --dry-run
```

Inspect the queue and delivery history, explicitly deliver eligible notifications, or retry failed deliveries:

```powershell
ai-job-hunter notify pending --limit 20
ai-job-hunter notify send --limit 20
ai-job-hunter notify history --limit 20
ai-job-hunter notify retry-failed --limit 20
```

Alerts are Telegram HTML messages in Spanish: decision and priority, title, company, location and work mode, salary band (or "Salario no publicado"), the public experience requirement, technologies, Jev strengths (signals ≥ 0.75), review concerns, and a link. All job text is escaped. A named city with no stated work mode outside your preferred locations gets a ⚠️ warning (interim until a daily digest exists).

Public experience-years requirements are checked against the current candidate policy before selection; incompatible experience cannot alert from an old saved APPLY/REVIEW. Alerts show the public floor/range and a generic stretch/UNKNOWN label, never candidate years or a numerical personal shortfall. See [experience rules](DOMAIN.md#explicit-experience-requirements). STALE evaluations are not eligible; this change does not globally suppress non-stale UNKNOWN reviews.

Each job alerts at most once per channel: a later evaluation of an already-notified job (new description, new prefilter version, new config) is suppressed as `already_notified`, unless the decision upgrades from REVIEW to APPLY, which alerts once more. Jobs you dismissed or have an application for are suppressed (`dismissed`, `already_applied`). Fully on-site roles alert only when they are APPLY or reach priority 85 (`onsite_not_exceptional`). The same posting seen through two sources (e.g. Himalayas and the company's ATS, which deduplication keeps as separate jobs without a shared URL) alerts once: same company + normalized title + seniority is `already_notified_elsewhere` or, within one run, `duplicate_in_batch`. Each run sends at most two alerts per company (`company_cap`); the rest follow in later runs. The scheduled script sends at most 10 alerts per run. Suppressed rows stay in the ledger for audit. `retry-failed` resumes safe retries left pending by an interrupted retry. A retry only applies where the stored delivery failure is safe; an uncertain network outcome must not be blindly resent because Telegram does not provide an idempotency key for `sendMessage`.

## Cover letters from alerts

Every alert carries two inline buttons: "✍️ Cover letter" (the letter follows the language of the posting) and "🇪🇸 En español" (always Spanish, whatever the posting language). Tapping one asks the local bot to draft a cover letter for that job with Claude and to reply in the same chat with the text, followed by the same letter as a Word (.docx) and a PDF attachment (name, contact line, date and body; A4). The same files are saved next to the Markdown draft; `ai-job-hunter cover-letter <job_id> --language {auto,es,en}` does the same from the CLI. If the files cannot be rendered, the text is still sent with a one-line notice. The bot is a separate long-polling process; it does nothing unless it is running:

```powershell
ai-job-hunter bot
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-bot.ps1
```

`scripts\run-bot.ps1` keeps the bot running, appends its output to `data\local\logs\bot-YYYY-MM.log` and restarts it 30 seconds after any exit. Drafts (`.md`, `.docx` and `.pdf`, named with the language) are saved under `data/local/cover-letters` and are never sent to anyone; review them before use. The bot only answers the chat configured in `TELEGRAM_CHAT_ID` (callbacks from any other chat are ignored), ignores unknown buttons, and resends the letter and files it already generated for that language (in the same bot session) instead of paying for a new one when a button is tapped again. Taps made while the bot was off are processed when it starts. Each letter costs roughly $0.05 with Claude Opus 5.5. Its update offset is kept in `data/local/telegram-bot-offset.json`, so restarts do not replay old taps. Alerts sent before this feature have no buttons, and alerts sent with the earlier single button keep working (it maps to the auto language).

## Periodic local run on Windows

The `run` command refreshes already monitored supported ATS sources through the existing opportunity pipeline, then handles notifications. It does not resolve Company Leads on each run. Configure the notification credentials in `.env` before enabling delivery.

```powershell
ai-job-hunter run --limit-companies 10 --max-jobs-per-company 100 --max-jev-jobs 20 --max-notifications 20
```

`scripts/run-scheduled.ps1` wraps `run` for Task Scheduler: it checks every monitored company (`--limit-companies 1000`), allows `-MaxJevJobs` new Jev calls per run (default 20), and appends each run's output and exit code to a monthly log in the Git-ignored `data\local\logs`. Test it without writes, Jev calls or Telegram:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-scheduled.ps1 -DryRun
```

Register it every two hours from 08:00 to 22:00 (run from the repository root; it runs only while you are logged on, and a run still in progress is never started twice):

```powershell
$root = (Get-Location).Path
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$root\scripts\run-scheduled.ps1`"" -WorkingDirectory $root
# One fixed daily trigger per run: a single trigger with "repeat every 2 hours"
# silently stopped repeating after the task was edited during the day.
$triggers = foreach ($h in 8,10,12,14,16,18,20,22) { New-ScheduledTaskTrigger -Daily -At ("{0:D2}:00" -f $h) }
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 1) -StartWhenAvailable -WakeToRun
Register-ScheduledTask -TaskName "AI Job Hunter" -Action $action -Trigger $triggers -Settings $settings -Description "Fetch monitored ATS jobs, evaluate and send Telegram alerts"
```

Pause with `Disable-ScheduledTask -TaskName "AI Job Hunter"`, resume with `Enable-ScheduledTask`, remove with `Unregister-ScheduledTask -TaskName "AI Job Hunter"`. `Get-ScheduledTaskInfo -TaskName "AI Job Hunter"` shows the last result (0 means success); details are in the log file.

Use `--no-notifications` to schedule refreshes without Telegram delivery. Use `--dry-run` only to inspect a refresh plan; it does not persist refresh/evaluation/notification changes or send messages.
