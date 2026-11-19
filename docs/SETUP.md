# Setting the hunter up for a different candidate

Everything personal lives in files that stay on your machine, never in Git: `candidate.local.json`, `.env`,
`private/` (CV, writing style) and the company and source lists. The code itself carries no names, employers
or CV facts.

## Quick start

1. `ai-job-hunter-init` (or `python -m ai_job_hunter.init_wizard`): a few questions write a validated
   `candidate.local.json`. Use `--answers answers.json` to run without questions, `--force` to overwrite.
2. Put your CV in `private/cv/CV_base_EN.md` (and `CV_base_ES.md` or another language you use) and, optionally,
   a style guide in `private/WRITING.md`.
3. Copy `.env.example` to `.env`: `DATABASE_URL`, `ANTHROPIC_API_KEY` (letters, application packs),
   `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` (alerts), `SCHEDULE_TIMEZONE`.
4. `alembic upgrade head`, then add the companies and portals you care about (`config/examples/`,
   `docs/COMPANY_INTELLIGENCE.md`) and run `ai-job-hunter run --dry-run`.

## Data engineering

On a shared Telegram bot, deploy this version and append `jobr_data` to the existing `JOB_PORTALS`.
On the Linux scheduled deployment, set `USER_ALERTS_ENABLED=1` to send alerts to invited users.
From the owner's chat, send `/invite` and share the one-use link. The invitee accepts consent, submits a CV,
checks the extracted skills and languages, and selects **Ingeniería de datos**. They then enter their target role,
locations, relocation preference, salary and work mode. They use their own chat and need no credentials or local files.
Invitations and trials follow the [standard Telegram onboarding flow](ONBOARDING_DESIGN.md).

For a separate installation, follow Quick start, use [the data profile example](../config/examples/candidate.data-engineering.example.json)
as `candidate.local.json`, and customize skills, languages, work authorization, locations, relocation and salary.
Its `preferences.sector` is `data_engineering`; existing profiles that omit `sector` still use software.

`jobr_data` searches Jobr for Data Engineer and Analytics Engineer listings in Spain, Ireland, the Netherlands,
Switzerland and the United Kingdom. It supplements other enabled sources, does not require a key or account,
and does not feed software profiles. These countries are search coverage, not work authorization or remote eligibility.
No TheirStack subscription is necessary. Existing bot and model credentials still apply to the host installation.

## What you can tune without touching code

`candidate.local.json` has a `tuning` section (all optional, neutral defaults). It only reorders results; it is
read when a feed is shown, so changing it never triggers a re-evaluation:

| Key | Effect |
| --- | --- |
| `relocation_penalty` | priority points lost by an on-site/hybrid role in an acceptable place that needs a move (default 15) |
| `preferred_relocation_penalty` | the same for destinations in `relocation_preferred_locations` (default 5) |
| `language_required_penalty` / `language_written_penalty` | points lost when a posting requires, or is written in, a language you do not list in `profile.languages` (25 / 15) |
| `salary_guide` | per country (`"Spain"`): `low`, `answer`, `high`, `currency`; alerts for postings without a published salary suggest the answer for that country |

Environment settings: `SCHEDULE_TIMEZONE`, `NOTIFY_REVIEW_MIN_PRIORITY`, `NOTIFY_MAX_AGE_DAYS`, `JOB_PORTALS`, and for
TheirStack `THEIRSTACK_COUNTRIES`, `THEIRSTACK_TITLES`, `THEIRSTACK_SENIORITY`, `THEIRSTACK_WATCH_COMPANIES`.

## What is still tied to the original profile

- Role-family filtering and the fit rubric depend on the profile's sector. Unsupported fields need their own templates.
- Alert, digest and bot texts are in Spanish.
- Default portals (Adzuna ES/NL/CH, Workday ES/LU/CH/NL/IE) and the source lists in `config/leads/` reflect the
  original search; replace them with your own countries and companies.
- The Company Hunter ranking and the cold-outreach rules assume a junior engineering search.

Use Telegram invitations or separate installations when sharing. Do not share your private profile, CV, or API keys.
