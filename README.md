# AI Job Hunter

AI Job Hunter is the foundation for a personal system that discovers job opportunities, helps decide which ones deserve attention, and tracks the search process. It is intended to support deliberate decisions, not mass application.

## Current architecture

The package has typed configuration, SQLAlchemy models, a PostgreSQL-ready engine/session factory, Alembic migrations, and a structural connector protocol. The first real source is Remotive; its adapter translates the public JSON API response into provider-independent `NormalizedJob` records. The fake in-memory connector remains available for tests and development.

```text
External source -> connector -> NormalizedJob -> deduplication -> ingestion -> database
```

`run_ingestion_pipeline` fetches normalized offers and passes each to the ingestion service. The service resolves a company when a name is present, then creates or refreshes the canonical `Job` and its `JobSource` occurrence in one transaction.

## Normalized offers and persistence

`NormalizedJob` validates common offer fields before persistence. It includes title/company/location, source identity and URL, salary, employment type, published/discovered timestamps, raw metadata, and two separate remote-work classifications: `remote_policy` (`ONSITE`, `HYBRID`, `REMOTE`) and `remote_eligibility` (`SPAIN_ONLY`, `EU_REMOTE`, `EMEA_REMOTE`, `WORLDWIDE`, `COUNTRY_RESTRICTED`, `UNKNOWN`). No automatic classification from free text is implemented.

The canonical `Job` keeps title, description, location, and its current remote policy. `JobSource` keeps provider-specific identity and URLs (original, canonical and apply), company website evidence, discovery time, raw metadata, salary/currency/period, employment type, published time, and the source's remote-work classifications. Those values can differ between appearances of the same canonical job, so they belong to the occurrence rather than being columns on `Job`.

## Identity, matching, and refresh behavior

The system separates three identities:

- **Company identity:** names are case-folded and a small set of terminal legal forms (`Inc.`, `Ltd`, `S.L.`, and similar) is removed. A supplied exact website hostname is stronger evidence. Conflicting or ambiguous domains keep companies separate; this is deliberately conservative.
- **Identity within a source:** the exact pair `(provider, external_id)` takes precedence. Reingesting it reuses its `Job` and `JobSource`, refreshes non-null occurrence fields, and preserves its original `discovered_at`.
- **Identity across sources:** a deterministic matcher compares a new offer to existing canonical jobs and their occurrences. It removes a small set of title context suffixes, keeps seniority separate, and supports only a modest `developer` → `engineer` alias. It also records company, domain, location, work-policy, publication-date, salary, and stable-URL signals.

The matcher returns `MATCH`, `POSSIBLE_MATCH`, or `NO_MATCH` with the signals and plain-language reasons. It does not calculate a probability. `MATCH` is intentionally strict: a normalized, job-specific URL must be identical (canonical URL, apply URL, or source URL), and there must be no contradictory title, seniority, company/domain, known location, work policy, or stable canonical/apply URL evidence. This can merge a LinkedIn record with an ATS listing when both carry the same canonical/apply URL, even without an external ID.

Same company plus same/similar title is only a `POSSIBLE_MATCH`; it creates a separate `Job` and returns the candidate explanation for review. Seniority mismatches, clearly different roles or companies, and differing job-specific canonical/apply URLs are `NO_MATCH`. Distinct URL evidence helps keep simultaneous openings with the same title separate. Location, publication date (14-day proximity), and overlapping salary ranges are exposed as secondary signals but do not independently cause a merge.

URL normalization ignores URL fragments and common tracking parameters and makes scheme/host formatting consistent. A URL counts as job-specific only when it contains a recognized stable ID or a job/role/position/opening route. Career homepages do not qualify. No network lookup or public-suffix database is used, so hostnames such as `jobs.acme.example` and `acme.example` remain different domains.

For the canonical `Job`, ingestion fills missing description, location, and remote policy, and never replaces a non-empty canonical title. A later source cannot overwrite populated canonical data; its own snapshot remains available on `JobSource`. A previously unknown company or missing canonical value can be added when evidence permits.

`PipelineSummary` reports `created`, `already_known`, `matched_existing`, `possible_match`, and `failed` separately. Possible results include their candidate IDs, signals, and reasons in memory; possible matches are not persisted. The current candidate search scans the local job corpus, suitable for the early personal project but not yet optimized for a large database.

Each offer is committed in its own transaction. A failed offer is rolled back and reported in the pipeline summary, while later offers can continue. A connector-level failure is also captured in the summary.

This is deterministic deduplication only. There is no fuzzy-match library, semantic search, embeddings, or LLM matching; those may be considered in a later iteration with explicit review and evaluation.

## Remotive source

`RemotiveConnector` uses the official public endpoint `https://remotive.com/api/remote-jobs` through `httpx`. Remotive documents a single JSON response containing `jobs`; there is no page parameter or pagination. The optional `limit`, `search`, `category`, and `company_name` parameters are supported. In a live check, a request for three returned 19 offers; the connector therefore also applies the requested limit locally and logs when the endpoint over-delivers. The CLI requests five offers by default; `--all` omits the limit.

The connector maps the documented fields conservatively:

| Remotive field | Normalized field / behavior |
| --- | --- |
| `id`, `url`, `title`, `company_name` | `external_id`, Remotive `source_url`, title, company |
| `candidate_required_location` | `location`; exact `Spain` / `Worldwide` are mapped, other non-empty values become `COUNTRY_RESTRICTED`, absent values remain `UNKNOWN` |
| endpoint's remote-job listing | `remote_policy=REMOTE` |
| `job_type` | Known full-time, part-time, contract and internship values map directly; freelance maps to `OTHER`; unknown values remain null |
| `salary` | A clear two-value range with an explicit currency is parsed. A period is mapped only when explicitly stated. Ambiguous dollar signs and single figures remain unstructured; original text remains in metadata. |
| `publication_date` | Parsed only when it includes an explicit timezone; a timezone-naive source date remains in raw metadata and `published_at` is null. |
| `description` | Plain text is stored for canonical use; the original HTML remains in `raw_metadata`. |
| `company_logo`, category, and other response fields | Preserved in `raw_metadata`; a logo URL is not mistaken for a company website. |

The [official API documentation](https://github.com/remotive-com/remote-jobs-api) says the public API is intended to let developers share Remotive jobs, requires linking to each Remotive listing and naming Remotive as the source, and prohibits submitting its jobs to third-party job sites. It says listings are delayed by 24 hours, recommends no more than four requests per day, and warns that more than two requests per minute will be blocked. The [site terms](https://remotive.com/terms-of-use) also restrict scraping and redistribution. This connector uses the documented API only for the personal local database; do not publish, resell, or republish its listings. The preview CLI includes a Remotive attribution and direct listing link.

The API does not expose a company website or apply URL in its documented job record. These remain null rather than being guessed from the company logo or Remotive listing. The API's salary field is free text and publication timestamps may lack a timezone, so some structured salary/date fields will intentionally remain empty.

Preview a small sample without connecting to the database:

```powershell
python -m ai_job_hunter.remotive_cli --limit 3 --show 3
```

The optional source-side filters are general-purpose, not candidate preferences:

```powershell
python -m ai_job_hunter.remotive_cli --category software-dev --search "backend engineer" --limit 10
```

To persist a bounded sample, first configure `DATABASE_URL` and apply migrations, then run:

```powershell
alembic upgrade head
python -m ai_job_hunter.remotive_cli --limit 5 --ingest
```

`--ingest` uses the existing transaction, exact-ID idempotency and conservative cross-source matching, and logs the outcome counts. It does not apply to jobs or send messages. Tests use a small representative fixture and mocked HTTP responses, so normal test runs never call the network.

There is no LinkedIn/Indeed connector, browser scraping, Jev integration, LLM integration, frontend, application tracking, outreach, or automatic application behavior.

## Stack

- Python 3.13
- PostgreSQL
- SQLAlchemy 2.x and Alembic
- Pydantic Settings v2
- httpx
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
- `JobSource` records each provider occurrence, including its provider, optional external identifier, original/canonical/apply URLs, company website evidence, discovery time, optional raw metadata, and normalized fields that may differ between sources.
- UUID primary keys are generated in Python. They provide stable identifiers without depending on database sequences and work across the supported SQLAlchemy dialects.
- Connector implementations share a structural `JobConnector` protocol and return `NormalizedJob`; provider-specific enums and connector classes are added only when a real source is introduced.
- Candidate profile, preferences, and other personal information are not included in the code or example configuration.

## Roadmap (indicative)

1. Phase 1 - Core/domain/persistence
2. Phase 2 - Job ingestion + normalization
3. Phase 3 - Deterministic deduplication (initial conservative rules implemented)
4. Phase 4 - Company Intelligence
5. Phase 5 - Decision Engine + Jev
6. Phase 6 - Application Tracking
7. Phase 7 - Outreach / Referrals
8. Phase 8 - Assisted Application Agent

Future applications, outreach, and messages should require explicit user approval before they are sent.
