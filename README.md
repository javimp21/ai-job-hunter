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

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev,browser,jev]"
Copy-Item .env.example .env
```

Set local database and optional TypeSafe credentials in `.env`. Never commit `.env` or candidate-specific `*.local.*` files. The checked-in templates in `config/examples/` use fictional values.

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
