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
