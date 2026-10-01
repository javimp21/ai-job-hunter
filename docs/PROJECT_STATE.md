# Project State

## Current focus
Maintain a safe, explainable job-opportunity workflow: discover jobs, evaluate fit, surface APPLY opportunities, prepare outreach/application materials locally, and keep consequential external actions human-approved.

## Recently completed
- Opportunity notifications are implemented in `1cb048a` (`feat: add opportunity notifications`); see [notification workflow](notifications.md).
- Company Intelligence/lead discovery, reproducible source initialization, outreach drafts, and assisted application preparation are implemented. See [README](../README.md#project-documentation) for documentation entry points.
- Shared principles, safety boundaries, development guidance, and testing documentation are intentionally versioned under `docs/`.

## Important active decisions
- Repository is source of truth; see [decisions](DECISIONS.md).
- Deterministic filters precede Jev where possible; UNKNOWN remains UNKNOWN; `priority` is review priority, not probability.
- External applications, outreach, and consequential actions require explicit human approval; never auto-submit applications.
- Preserve provenance and avoid unnecessary live Jev/API calls.
- Graphify output and indexing configuration remain local and Git-ignored. Personal `AGENTS.md` and `.pi/` remain locally excluded; see [development](DEVELOPMENT.md#local-repository-tools).

## Pending / limits
- Live Telegram delivery, live ATS/browser interactions, and PostgreSQL deployment were not verified during the documentation/publication checks.
- Existing Alembic configuration emits a `path_separator` deprecation warning. The local pytest cache is not writable by the current Windows user; this did not prevent tests from passing.
- Keep notification and assisted-application flows human-in-the-loop; do not widen APPLY merely to increase results.

## Next steps
1. Start continuation work with `git status`, the relevant linked docs, and the specific service/CLI/tests.
2. For shared evaluation, persistence, notification, outreach, or application-preparation changes, run focused regressions and then the offline suite.
3. Update this file only when the active focus, pending work, decisions, or verification state materially changes.

## Last verified
2026-10-01, branch `main`: inspected repository state, the pending notification commit, README and project Markdown documentation. Ran in Git Bash: `TYPESAFE_API_KEY='' TELEGRAM_BOT_TOKEN='' TELEGRAM_CHAT_ID='' .venv/Scripts/python.exe -m pytest -q`: **481 passed, 6 warnings** (5 Alembic deprecation warnings and 1 pytest cache permission warning). No live provider checks were run. Publication status is recorded by Git, not by a hard-coded ahead/behind claim in this file.
