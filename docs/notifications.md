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

Alerts are Telegram HTML messages in Spanish: decision and priority, title, company, location and work mode, salary band (or "Salario no publicado"), the public experience requirement, technologies, Jev strengths (signals ≥ 0.75), review concerns, and a link. All job text is escaped. A named city with no stated work mode outside your preferred locations gets a ⚠️ warning; such a REVIEW does not alert (`uncertain_location`) and goes to the daily digest instead, while an APPLY still alerts with the warning.

Public experience-years requirements are checked against the current candidate policy before selection; incompatible experience cannot alert from an old saved APPLY/REVIEW. Alerts show the public floor/range and a generic stretch/UNKNOWN label, never candidate years or a numerical personal shortfall. See [experience rules](DOMAIN.md#explicit-experience-requirements). STALE evaluations are not eligible; this change does not globally suppress non-stale UNKNOWN reviews.

Each job alerts at most once per channel: a later evaluation of an already-notified job (new description, new prefilter version, new config) is suppressed as `already_notified`, unless the decision upgrades from REVIEW to APPLY, which alerts once more. Jobs you dismissed or have an application for are suppressed (`dismissed`, `already_applied`). Fully on-site roles alert only when they are APPLY or reach priority 85 (`onsite_not_exceptional`). The same posting seen through two sources (e.g. Himalayas and the company's ATS, which deduplication keeps as separate jobs without a shared URL) alerts once: same company + normalized title + seniority is `already_notified_elsewhere` or, within one run, `duplicate_in_batch`. Each run sends at most two alerts per company (`company_cap`); the rest follow in later runs. The scheduled script sends at most 10 alerts per run. Suppressed rows stay in the ledger for audit. `retry-failed` resumes safe retries left pending by an interrupted retry. A retry only applies where the stored delivery failure is safe; an uncertain network outcome must not be blindly resent because Telegram does not provide an idempotency key for `sendMessage`.

## Daily digest

Second-tier opportunities are listed once in an evening Telegram digest instead of alerting one by one: a REVIEW from priority 50 up to the alert threshold, on-site roles from priority 70 that did not reach the on-site alert bar, REVIEWs with an uncertain location, and alert-worthy jobs that were first seen too late to alert (`older_than_max_age`). Jobs older than 7 days, dismissed or applied jobs, jobs already alerted, and jobs held back only by the per-company cap are left out. At most 12 jobs, best first; each line shows the review priority, linked title, company, location and work mode, and the message carries one row of buttons per job (`n ✍️`, `n 👍`, `n 👎`) that work like the alert buttons. Each job appears in at most one digest (rows with channel `TELEGRAM_DIGEST` in the notification ledger, which never count as alerts), and at most one digest is sent per 20 hours. If delivery fails nothing is recorded.

```powershell
ai-job-hunter notify digest --dry-run
ai-job-hunter notify digest
```

`scripts\run-scheduled.ps1` runs it after the 20:00 and 22:00 runs, so the digest arrives with the first of them that runs.

## Weekly report

A concise Spanish Telegram message (HTML, phone-sized) summarising the last 7 days, sent on Sunday evening by the scheduled script. Every figure is computed from stored rows; nothing is estimated, and a section with no data says so.

- **Funnel**: jobs first seen in the window, how many passed the deterministic prefilter (not `REJECT`), how many have a current evaluation, and how many are `APPLY` / `REVIEW`; alerts (`TELEGRAM`) and daily-digest items (`TELEGRAM_DIGEST`) actually sent in the window.
- **Relevant jobs** (`APPLY` or `REVIEW`, first seen in the window): top 5 companies and top 5 sources (a job seen through two providers counts once for each).
- **Technologies**: most frequent in relevant jobs, marked ✅ when they are in the candidate's profile (`technologies`, `primary_skills`, `secondary_skills`), plus the technologies of the jobs you saved (👍) and dismissed (👎) in the window.
- **Salaries**: published ranges of relevant jobs in EUR only, yearly (monthly values are multiplied by 12; other periods and other currencies are skipped, with no conversion): median of each job's midpoint, lowest and highest published figure, and how many relevant jobs carry one.
- **Feedback**: 👍 / 👎 counts (saved / dismissed reviews updated in the window) and their reasons.
- **Failing sources**: active boards with 6+ consecutive failed fetches (same rule as the digest).
- **Suggestions** (at most 3, plain rules over the figures above): a technology missing from your stack in at least 3 relevant jobs and 25% of them; one dismissal reason behind at least 3 and 40% of your 👎; failing sources; no relevant jobs, or no new jobs at all. With no pattern the report says there are not enough data.

```powershell
ai-job-hunter notify weekly --dry-run
ai-job-hunter notify weekly
ai-job-hunter notify weekly --force
```

At most one report per 6 days: the marker is a row in `report_deliveries` (kind `WEEKLY`, written only after Telegram accepted the message; a failed delivery records nothing). It is a table of its own rather than a new notification channel because the notification ledger is keyed by job (`job_id` is required), and a report is not about one job. `--dry-run` never contacts Telegram or writes anything; `--force` ignores the 6-day marker. On Linux `deploy/linux/run-scheduled.sh` calls it on Sundays from 20:00 Europe/Madrid (see [SERVER.md](SERVER.md#schedule)); on Windows run it manually or from a Task Scheduler entry.

## Cover letters from alerts

Every alert carries two inline buttons: "✍️ Cover letter" (the letter follows the language of the posting) and "🇪🇸 En español" (always Spanish, whatever the posting language). Tapping one asks the local bot to draft a cover letter for that job with Claude; the bot replies to that alert (quoting it) with the letter as one grouped Word (.docx) + PDF message (name, contact line, date and body; A4) and a one-line caption, so the alert feed is not interleaved with long letter texts. The same files are saved next to the Markdown draft; `ai-job-hunter cover-letter <job_id> --language {auto,es,en}` does the same from the CLI. If the files cannot be rendered or uploaded, the letter text is sent instead, still as a reply to the alert. The bot is a separate long-polling process; it does nothing unless it is running:

```powershell
ai-job-hunter bot
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\run-bot.ps1
```

`scripts\run-bot.ps1` keeps the bot running, appends its output to `data\local\logs\bot-YYYY-MM.log` and restarts it 30 seconds after any exit. Drafts (`.md`, `.docx` and `.pdf`, named with the language) are saved under `data/local/cover-letters` and are never sent to anyone; review them before use. The bot only answers the chat configured in `TELEGRAM_CHAT_ID` (callbacks from any other chat are ignored), ignores unknown buttons, and resends the letter and files it already generated for that language (in the same bot session) instead of paying for a new one when a button is tapped again. Taps made while the bot was off are processed when it starts. Each letter costs roughly $0.05 with Claude Opus 5.5. Its update offset is kept in `data/local/telegram-bot-offset.json`, so restarts do not replay old taps. Alerts sent before this feature have no buttons, and alerts sent with the earlier single button keep working (it maps to the auto language).

## Preparar candidatura

Every alert (and every digest line, as `n 📝`) also has "📝 Preparar candidatura". The bot replies to the alert with one grouped message: a CV tailored to the posting and the cover letter, each as Word and PDF, followed by a text message with answers for typical application-form questions and the apply link. Nothing is submitted. `ai-job-hunter prepare-application <job_id> [--language auto|es|en]` does the same from the CLI.

- The CV is tailored by Claude from the candidate's own base CV, `private/cv/CV_base_EN.md` / `CV_base_ES.md` (a small Markdown subset rendered single-column with standard bullets, ATS-friendly). It may retarget the headline and summary, reorder bullets and skills, and lightly rephrase with the posting's vocabulary. A validator rejects any tailored CV that changes the sections, the name or the contact/role/date/education lines, introduces a number that is not in the base CV, or lists a skill or headline technology that is not in it; the base CV is then sent instead, with the reason in the caption.
- "Why this company / role" answers come from Claude in the candidate's voice; notice period, work authorization and relocation come verbatim from `candidate_application.local.json`, and the salary line shows the candidate's target next to the posting's published range. Missing facts say "(completa tú)".
- Files are saved under `data/local/applications/<timestamp>-<company>-<title>/`. Each pack costs two Claude calls (letter + CV), roughly $0.10–0.15. A second tap in the same bot session resends the same pack.

## Preparar entrevista

After tapping 👍 on an alert, the follow-up "¿Qué te gusta de esta oferta?" message also has "🎯 Preparar entrevista" (callback `ip:<job_id>`). The bot replies to the alert with the brief as one grouped Word + PDF message; nothing is sent anywhere. `ai-job-hunter interview-prep <job_id> [--language auto|es|en]` does the same from the CLI.

- Language follows the posting (`auto`) or is forced; the base CV `private/cv/CV_base_<ES|EN>.md` of that language is required.
- The brief has: what the company does (only from the posting text and the stored website URL, which is never fetched; "no consta" when unknown), what the role involves, 8-12 likely questions (technical ones tied to the posting's stack, plus behavioural) each with the real CV experience to use, honest gaps with a positive but truthful framing, and 4-5 questions to ask. Claude is instructed never to add experience that is not in the base CV; there is no automatic validator as for tailored CVs, so contrast the company facts and the CV references before the interview.
- Files are saved under `data/local/interviews/<timestamp>-<company>-<title>/` as `entrevista_<LANG>.md/.docx/.pdf`. One Claude call per brief; a second tap in the same bot session resends it. Without Word/PDF the text is sent instead.

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

## Feedback buttons

Every alert also carries "👍 Me interesa" and "👎 No me interesa". A tap marks the job SAVED or DISMISSED (dismissed jobs leave the feed and never alert) and the bot asks why with reason buttons (dismiss: salary, location, role, seniority, experience, stack, company, not interested, other; save: company, stack, salary, learning, product, remote, career, other). The reason is stored on the job review (`job_reviews.reason`) as data for future ranking; it never relaxes hard constraints. The bot must be running for buttons to work.
