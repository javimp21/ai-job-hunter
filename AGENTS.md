# AI Job Hunter

Personal tool for discovering, filtering, evaluating and managing job opportunities.

## Source of truth

The current repository is the source of truth.

Before changing behavior, inspect the relevant implementation, configuration, tests and documentation.

Do not assume conversation context is newer than the repository.

## Workflow

### Small changes

Work directly.

Do not use subagents when the task is local and clearly understood.

### Non-trivial changes

Use subagents when delegation provides clear value.

Typical workflow:

1. `advisor` — architecture, plan and risks.
2. `worker` — scoped implementation.
3. `reviewer` — independent review.
4. Main session integrates and fixes.
5. Run the real project checks.

Do not delegate identical work to multiple agents.

### UI

Use `ui-claude` for substantial UI work.

Do not duplicate Python business logic in the frontend.

Review responsive behavior, accessibility, loading, empty, error and UNKNOWN states.

## Critical rules

- Never expose or commit secrets, credentials, tokens or candidate PII.
- Never perform external actions without explicit authorization.
- Never auto-submit applications.
- Avoid unnecessary live Jev calls.
- Avoid live job fetching in offline tests.
- Preserve provenance.
- Hints are not facts.
- UNKNOWN stays UNKNOWN.
- Do not widen APPLY merely to increase results.
- `priority` is review priority, not probability.
- Never invent jobs, contacts, emails, sources, tests or results.
- Preserve unrelated persistent data.
- Do not push unless explicitly requested.
- Do not add `.pi/` to Git unless explicitly requested.

## Validation

After changes:

- run relevant tests;
- run the full suite when shared logic changes;
- run `git diff --check`;
- run existing project quality gates when applicable.

Report exact tests executed, counts, warnings and anything that could not be verified.

## Context map

Read only when relevant:

- Architecture → `docs/ARCHITECTURE.md`
- Important decisions → `docs/DECISIONS.md`
- Job decisions/domain → `docs/DOMAIN.md`
- Jev → `docs/JEV.md`
- Company Intelligence/Leads → `docs/COMPANY_INTELLIGENCE.md`
- Company Hunter (company fit ranking, public contacts, outreach drafts, manual LinkedIn queue) → `docs/COMPANY_HUNTER.md`
- External actions/outreach → `docs/EXTERNAL_ACTIONS.md`
- Persistence/migrations → `docs/DATA.md`
- Testing → `docs/TESTING.md`
- Git/Docker/development → `docs/DEVELOPMENT.md`

When a repository graph/index is available, use it before broad repository exploration.

Read only the files necessary for the current task.

## Goal

Optimize for:

- less noise;
- better opportunities;
- fewer unnecessary Jev calls;
- explainability;
- fast human decisions;
- safety;
- idempotency;
- traceability.

Do not optimize merely for more features.