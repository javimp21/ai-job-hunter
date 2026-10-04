# Data & Persistence

## Safety

Before modifying persistent data, determine what will be affected.

This includes:

- PostgreSQL;
- local databases;
- snapshots;
- benchmarks;
- persisted evaluations.

Preserve unrelated data.

## Migrations

Prefer additive migrations.

Destructive migrations require an explicit reason and review.

Inspect affected models and existing migrations before changing schema.

## Company Hunter data

Migration `0013_company_hunter` adds `connection_requests` (the manual LinkedIn pipeline: contact, company, note ≤300 characters, language, status `SUGGESTED|SENT|ACCEPTED|SKIPPED`, timestamps, Telegram message id, optional pasted post and follow-up draft) and makes the company-level active-outreach uniqueness per channel (so an EMAIL and a LINKEDIN draft coexist). Contacts and drafts reuse `contacts` / `outreaches` / `outreach_events`. The migration is SQLite-safe (only indexes are recreated; no CHECK is altered).

## Secrets

Never print complete connection strings containing credentials.

Never commit:

- `.env`;
- credentials;
- local databases;
- candidate PII;
- ignored `*.local.*` artifacts.

## Docker/PostgreSQL

Do not assume services are available.

Check first and use project-documented commands and configuration.
