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

Successful deliveries are deduplicated by opportunity evaluation and channel. A changed evaluation can produce a new notification. `retry-failed` resumes safe retries left pending by an interrupted retry. A retry only applies where the stored delivery failure is safe; an uncertain network outcome must not be blindly resent because Telegram does not provide an idempotency key for `sendMessage`.

## Periodic local run on Windows

The `run` command refreshes already monitored supported ATS sources through the existing opportunity pipeline, then handles notifications. It does not resolve Company Leads on each run. Configure the notification credentials in `.env` before enabling delivery.

```powershell
ai-job-hunter run --limit-companies 10 --max-jobs-per-company 100 --max-jev-jobs 20 --max-notifications 20
```

To schedule it about every two hours from 08:00 through 22:00:

1. Open **Task Scheduler** and choose **Create Task**.
2. On **General**, select the Windows account that owns this checkout and choose **Run only when user is logged on** if the local environment is not available to background tasks.
3. On **Triggers**, create a daily trigger at 08:00. Enable **Repeat task every: 2 hours** and set **for a duration of: 14 hours**.
4. On **Actions**, use the installed command path `<project>\.venv\Scripts\ai-job-hunter.exe`, arguments `run --limit-companies 10 --max-jobs-per-company 100 --max-jev-jobs 20 --max-notifications 20`, and **Start in** the repository root. If the console entry point is unavailable, use `<project>\.venv\Scripts\python.exe -m ai_job_hunter.cli` with those arguments.
5. On **Settings**, choose **Do not start a new instance** if the task is already running. Review **Last Run Result** after the first scheduled run.

Use `--no-notifications` to schedule refreshes without Telegram delivery. Use `--dry-run` only to inspect a refresh plan; it does not persist refresh/evaluation/notification changes or send messages.
