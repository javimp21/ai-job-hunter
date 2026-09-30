# AI Job Hunter

AI Job Hunter is an intelligent job discovery, evaluation, and assisted-application system. It helps candidates find opportunities, assess fit, organize applications, and prepare next steps with human oversight.

## Features

- Job discovery from Greenhouse, Lever, Ashby, and Remotive.
- Normalization and deduplication across sources.
- Deterministic candidate prefiltering followed by structured Jev evaluation.
- Company Intelligence and an Opportunity Feed for finding and reviewing roles.
- Application Tracking for managing opportunities through the search process.
- Outreach and referral preparation with local drafts.
- Assisted Application Preparation for reviewing questions and selecting candidate documents.
- Playwright browser-assisted workflows with a submission guard.

## Architecture

```text
Job Sources
    |
    v
Normalization
    |
    v
Deduplication
    |
    v
Deterministic Prefilter
    |
    v
Jev Evaluation
    |
    v
Opportunity Feed
    |-- Application Tracking
    |-- Outreach / Referrals
    `-- Assisted Apply
```

The pipeline keeps deterministic filtering separate from model-based evaluation, then exposes the resulting opportunities through human-reviewed workflows rather than treating model output as an automatic application decision.

## Safety and privacy

- No mass automatic applications or automatic message sending.
- No LinkedIn scraping.
- Candidate facts are never invented; application decisions stay human-in-the-loop, and uncertain or sensitive answers stay for review.
- A submit guard blocks application submission during browser-assisted preparation.
- Private candidate configuration, local application data, credentials, databases, documents, and browser state are excluded by `.gitignore`.
- `config/examples/` contains fictional configuration examples. Automated tests use synthetic data and do not call live job APIs or Jev.

## Technology

Python 3.13, PostgreSQL, SQLAlchemy, Alembic, Pydantic Settings, httpx, Playwright, pytest, and TypeSafe/Jev.

## Local setup

Before running the source commands, create the ignored `job_sources.local.json` from `config/examples/job_sources.example.json` and replace the example board identifiers with the public ATS boards you want to monitor.

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,browser,jev]"
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
docker compose up -d
alembic upgrade head
python -m ai_job_hunter.jobs_cli --sources job_sources.local.json --ingest
python -m ai_job_hunter.company_cli monitor --supported-ats --limit-companies 3 --max-jobs-per-company 30
ai-job-hunter refresh --limit-companies 3 --max-jobs-per-company 30 --max-jev-jobs 5
```

The Compose service provides a persistent local PostgreSQL 16 database on port `5432` with fictional development credentials. The copied `.env.example` already points to it. `python -m ai_job_hunter.jobs_cli --sources ... --ingest` fetches and stores actual postings; `company_cli monitor` synchronizes ATS evidence from those persisted postings so `refresh` has monitored targets. The `job_sources` table stores individual job postings, not board configuration. Set optional TypeSafe credentials in `.env`; never commit `.env` or candidate-specific `*.local.*` files. The checked-in templates in `config/examples/` use fictional values. Stop PostgreSQL with `docker compose stop` when you are done; its named volume keeps local database data between runs.

Company leads are an explicit discovery input, separate from ATS job boards. Copy `config/examples/company_leads.example.json` to the ignored `company_leads.local.json`, replace its example with companies and public URLs you have verified, then run:

```powershell
python -m ai_job_hunter.company_leads_cli import --file company_leads.local.json
python -m ai_job_hunter.company_leads_cli resolve --limit 10
python -m ai_job_hunter.company_cli monitor --supported-ats --limit-companies 10 --max-jobs-per-company 30
```

Import is idempotent and never runs as part of `refresh`. Resolution inspects supplied public websites/careers pages with bounded requests and recognizes only the existing Greenhouse, Lever, and Ashby URL patterns. Company/location/hiring hints remain discovery hints and do not establish remote eligibility or other Company Intelligence facts.

## CLI examples

Refresh monitored job sources and update the opportunity feed:

```powershell
ai-job-hunter refresh --limit-companies 10 --max-jev-jobs 20
```

Review the highest-priority opportunities currently classified as `APPLY`:

```powershell
ai-job-hunter opportunities --decision apply --limit 10
```

Inspect one opportunity and its saved application history:

```powershell
ai-job-hunter show <JOB_ID>
```

Prepare application materials locally, then inspect the hosted form without submitting it:

```powershell
ai-job-hunter apply prepare <JOB_ID>
ai-job-hunter apply browser <JOB_ID>
```

Preview which factual fields the browser workflow could fill without changing the form:

```powershell
ai-job-hunter apply fill-safe <JOB_ID> --dry-run
```

Create an outreach draft for human review:

```powershell
ai-job-hunter outreach draft <JOB_ID> --channel linkedin
```

The CLI intentionally separates discovery, evaluation, review, outreach, and application preparation. Browser-assisted commands do not submit applications or upload documents.

## Tests

```powershell
python -m pytest
```

The test suite is designed to run offline with synthetic fixtures. It does not require a real API key, live provider APIs, a browser smoke session, or PostgreSQL.
