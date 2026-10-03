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

Public experience-years requirements are checked against the current candidate policy before selection; incompatible experience cannot alert from an old saved APPLY/REVIEW. Alerts show the public floor/range and a generic stretch/UNKNOWN label, never candidate years or a numerical personal shortfall. See [experience rules](DOMAIN.md#explicit-experience-requirements). STALE evaluations are not eligible; this change does not globally suppress non-stale UNKNOWN reviews.

Each job alerts at most once per channel: a later evaluation of an already-notified job (new description, new prefilter version, new config) is suppressed as `already_notified`, unless the decision upgrades from REVIEW to APPLY, which alerts once more. Jobs you dismissed or have an application for are suppressed (`dismissed`, `already_applied`). Suppressed rows stay in the ledger for audit. `retry-failed` resumes safe retries left pending by an interrupted retry. A retry only applies where the stored delivery failure is safe; an uncertain network outcome must not be blindly resent because Telegram does not provide an idempotency key for `sendMessage`.

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
$trigger = New-ScheduledTaskTrigger -Daily -At 08:00
$trigger.Repetition = (New-ScheduledTaskTrigger -Once -At 08:00 -RepetitionInterval (New-TimeSpan -Hours 2) -RepetitionDuration (New-TimeSpan -Hours 14)).Repetition
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 1) -StartWhenAvailable
Register-ScheduledTask -TaskName "AI Job Hunter" -Action $action -Trigger $trigger -Settings $settings -Description "Fetch monitored ATS jobs, evaluate and send Telegram alerts"
```

Pause with `Disable-ScheduledTask -TaskName "AI Job Hunter"`, resume with `Enable-ScheduledTask`, remove with `Unregister-ScheduledTask -TaskName "AI Job Hunter"`. `Get-ScheduledTaskInfo -TaskName "AI Job Hunter"` shows the last result (0 means success); details are in the log file.

Use `--no-notifications` to schedule refreshes without Telegram delivery. Use `--dry-run` only to inspect a refresh plan; it does not persist refresh/evaluation/notification changes or send messages.
