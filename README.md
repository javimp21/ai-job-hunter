# AI Job Hunter

AI Job Hunter is the foundation for a personal system that discovers job opportunities, helps decide which ones deserve attention, and tracks the search process. It is intended to support deliberate decisions, not mass application.

## Current architecture

The package has typed configuration, SQLAlchemy models, a PostgreSQL-ready engine/session factory, and Alembic migrations. A small connector protocol accepts any source adapter that yields `NormalizedJob` records. A connector is responsible for translating its own source-specific/raw data into that provider-independent Pydantic model; the core does not know about a particular provider.

`run_ingestion_pipeline` fetches normalized offers and passes each to the ingestion service. The service resolves a company when a name is present, then creates or refreshes the canonical `Job` and its `JobSource` occurrence in one transaction. `FakeJobConnector` is an in-memory development/test adapter. Tests exercise a batch with two jobs from one company and a repeated source ID.

## Normalized offers and persistence

`NormalizedJob` validates common offer fields before persistence. It includes title/company/location, source identity and URL, salary, employment type, published/discovered timestamps, raw metadata, and two separate remote-work classifications: `remote_policy` (`ONSITE`, `HYBRID`, `REMOTE`) and `remote_eligibility` (`SPAIN_ONLY`, `EU_REMOTE`, `EMEA_REMOTE`, `WORLDWIDE`, `COUNTRY_RESTRICTED`, `UNKNOWN`). No automatic classification from free text is implemented.

The canonical `Job` keeps title, description, location, and its current remote policy. `JobSource` keeps provider-specific identity, URL, discovery time, raw metadata, salary/currency/period, employment type, published time, and the source's remote-work classifications. Those values can differ between appearances of the same canonical job, so they belong to the occurrence rather than being columns on `Job`.

## Current identity and refresh behavior

The only job identity check is the exact pair `(provider, external_id)`. Reingesting that pair reuses its existing `Job` and `JobSource`; the service refreshes the source snapshot and updates the canonical title plus any non-null description, location, or remote policy. It keeps the original `discovered_at` timestamp. Missing canonical fields do not erase values already stored. A company is reused by case-insensitive name, and a missing website can be filled in later.

When `external_id` is null or blank, the service does not guess identity: each ingestion creates a new `Job` and `JobSource`. There is no semantic or cross-provider deduplication yet. `(provider, external_id)` is only the first simple identity mechanism; deduplication between sources belongs to a later phase.

Each offer is committed in its own transaction. A failed offer is rolled back and reported in the pipeline summary, while later offers can continue. A connector-level failure is also captured in the summary.

There is no real source connection, scraping, LLM integration, Jev integration, application tracking, outreach, or automatic application behavior in this iteration.

## Stack

- Python 3.13
- PostgreSQL
- SQLAlchemy 2.x and Alembic
- Pydantic Settings v2
- pytest

## Setup (Windows PowerShell)

Create and activate a virtual environment, then install the package and test dependency:

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

Edit `.env` and set a private `DATABASE_URL`. `.env` is ignored by Git. Do not put candidate profile data or credentials in tracked files.

### PostgreSQL

With Docker installed, start a local PostgreSQL 17 container:

```powershell
docker run --name ai-job-hunter-postgres `
  -e POSTGRES_DB=ai_job_hunter `
  -e POSTGRES_USER=ai_job_hunter `
  -e POSTGRES_PASSWORD=change-me `
  -p 5432:5432 `
  -d postgres:17
```

Use the matching local connection string in `.env`:

```dotenv
DATABASE_URL=postgresql+psycopg://ai_job_hunter:change-me@localhost:5432/ai_job_hunter
```

To stop and restart the same container, run `docker stop ai-job-hunter-postgres` and `docker start ai-job-hunter-postgres`. For a local PostgreSQL installation, create a database and user, then set `DATABASE_URL` to match those values.

## Migrations

Apply the checked-in schema migration:

```powershell
alembic upgrade head
```

After changing a model, create and review a migration before applying it:

```powershell
alembic revision --autogenerate -m "describe the schema change"
alembic upgrade head
```

## Tests

```powershell
python -m pytest
```

Tests use in-memory SQLite and do not require Internet access or a running PostgreSQL server. The PostgreSQL migration chain can be rendered offline with `alembic upgrade head --sql`; applying it requires the database configured in `.env`.

## Data model and design choices

- `Company` is independent of jobs so a company can be recorded before a suitable role appears.
- `Job` is the canonical opportunity and may have an unknown company (`company_id` is nullable).
- `JobSource` records each provider occurrence, including its provider, optional external identifier, original URL, discovery time, optional raw metadata, and normalized fields that may differ between sources.
- UUID primary keys are generated in Python. They provide stable identifiers without depending on database sequences and work across the supported SQLAlchemy dialects.
- Connector implementations share a structural `JobConnector` protocol and return `NormalizedJob`; provider-specific enums and connector classes are added only when a real source is introduced.
- Candidate profile, preferences, and other personal information are not included in the code or example configuration.

## Roadmap (indicative)

1. Phase 1 - Core/domain/persistence
2. Phase 2 - Job ingestion + normalization
3. Phase 3 - Deduplication
4. Phase 4 - Company Intelligence
5. Phase 5 - Decision Engine + Jev
6. Phase 6 - Application Tracking
7. Phase 7 - Outreach / Referrals
8. Phase 8 - Assisted Application Agent

Future applications, outreach, and messages should require explicit user approval before they are sent.
