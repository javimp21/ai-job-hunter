# Project State

## Current focus
Validate explicit experience-years filtering for real use: floors and ranges have different candidate-relative stretch tolerances; STRETCH/UNKNOWN cannot become APPLY from a high Jev score. See [experience rules](DOMAIN.md#explicit-experience-requirements). Keep external actions human-approved.

## Recently completed
- Explicit experience parser, prefilter/final-policy ceilings, cached-feed rechecks and public requirement display are implemented locally (uncommitted). Independent review and follow-up covered extraction, cache/feed, notification pending/retry and application-prep. Company introductions/repeated-unit range findings were fixed; two follow-up P2 consistency issues (heading resets and scoped application-fit duration) were also fixed and validated by the main session with regressions. Tests and read-only smoke are recorded below.
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
- Earlier real-use refresh: 3 companies, 68 fetched offers, 2 new Jev evaluations, 5 cache hits, no notifications sent in that cycle. The user confirmed receipt of the two earlier Telegram alerts; this is not a new delivery test.
- The ledger keeps those two real Telegram deliveries (2026-10-01: Duna — Backend Engineer; Notion — Software Engineer, Early Career) and one suppressed row (fal — Creative Technologist) as valid history. They were sent before the experience and role/geography tightening; under the current prefilter both are deterministic SKIP (Duna requires 3–5+ years; Notion is San Francisco only), so they cannot notify again. Ledger deduplication is per job *and* evaluation fingerprint: a future current evaluation of a previously sent job is a new notification candidate.
- Experience-policy version changes deliberately leave historical semantic evaluations STALE; there is no offline backfill/migration of unproven old Jev evidence. This validation did not refresh candidate-specific database results, so stale rows remain stale pending an explicitly authorized evaluation. No automatic new Jev calls were made.
- Two pre-existing notification noise issues remain: applied/dismissed jobs can alert, and a changed evaluation can notify again with the same decision. Resolve before relying on scheduled sends.
- Live browser/ATS submission interactions remain unverified; no application submission is authorized.
- Existing Alembic configuration emits a `path_separator` deprecation warning. The local pytest cache is not writable by the current Windows user; this did not prevent tests from passing.
- Keep notification and assisted-application flows human-in-the-loop; do not widen APPLY merely to increase results.

## Next steps
1. Start continuation work with `git status`, the relevant linked docs, and the specific service/CLI/tests.
2. For shared evaluation, persistence, notification, outreach, or application-preparation changes, run focused regressions and then the offline suite.
3. Update this file only when the active focus, pending work, decisions, or verification state materially changes.

## Last verified
2026-10-03, branch `main`, baseline `9f463ad`, experience changes validated before commit. Focused Python 3.13 suite: **278 passed, 1 pytest cache-permission warning**. Full offline suite: **588 passed, 6 warnings** (5 existing Alembic `path_separator` deprecations, 1 pytest cache-permission warning). `git diff --check` passed (Git emits LF→CRLF notices). This validation did not inspect or modify PostgreSQL and made no live ATS, Jev or Telegram calls. The local `origin/main` tracking ref matched `main`; a fresh `git fetch origin` could not be completed in this session.
