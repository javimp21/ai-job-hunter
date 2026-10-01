# Development

## Git

Before committing:

1. inspect the diff;
2. run relevant tests;
3. run `git diff --check`.

Do not push unless explicitly requested.

Never force push unless explicitly requested and justified.

Do not automatically delete or clean:

- `.pi/`;
- `AGENTS.md`;
- local development artifacts that may contain useful work.

Do not commit:

- `.env`;
- secrets;
- candidate PII;
- local databases;
- local snapshots;
- ignored `*.local.*` files.

## Local repository tools

Graphify is an optional local navigation aid, not a runtime dependency or source
of truth. `graphify-out/` and `.graphifyignore` are ignored by `.gitignore`;
keep generated graphs, reports, caches, and machine-specific paths local.
Do not publish them or rebuild them merely to commit documentation.

Personal `.pi/` state and `AGENTS.md` stay local via `.git/info/exclude`.
For a fresh checkout, add these root-anchored patterns to that local file if
using Pi:

```gitignore
/.pi/
/AGENTS.md
```

These exclusions preserve local files; they do not delete them. Shared project
rules and documentation live in the versioned `docs/` files linked from README.
Confirm with `git status --short` and `git check-ignore -v` before staging;
stage explicit paths rather than `git add .`.

## Changes

Keep changes scoped to the request.

Follow existing repository patterns.

Avoid unrelated refactors.

## Docker

Check Docker availability before relying on it.

Use repository-documented commands.

## Quality

Prefer automated checks already adopted by the repository.

Do not introduce new tooling merely for the sake of having more tooling.
