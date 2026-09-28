# AI Job Hunter

AI Job Hunter is the foundation for a personal system that discovers job opportunities, helps decide which ones deserve attention, and tracks the search process. It is intended to support deliberate decisions, not mass application.

## Current architecture

The package has typed configuration, SQLAlchemy models, a PostgreSQL-ready engine/session factory, Alembic migrations, and a structural connector protocol. Sources include Remotive, a job aggregator, and public employer job boards hosted by Greenhouse, Lever, or Ashby (ATS platforms). Each adapter translates public postings into provider-independent `NormalizedJob` records. The fake in-memory connector remains available for tests and development.

```text
External source -> connector -> NormalizedJob
                                      +-> deduplication -> ingestion -> database
                                      +-> candidate pre-filter -> preview output
```

Company Intelligence can also discover a bounded set of employer boards without page scraping:

```text
Company Intelligence -> ATS URL/evidence discovery -> monitor target
  -> Greenhouse / Lever / Ashby public API -> NormalizedJob
  -> existing deduplication pipeline -> candidate pre-filter -> optional Jev
```

ATS discovery recognizes exact public board hosts in career URLs and direct ATS providers already recorded by existing job sources. LinkedIn and generic career pages remain `UNKNOWN`; no ATS is guessed by fetching a page. Observed job-source evidence takes precedence over a career-URL hostname inference.

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

## Greenhouse and Lever sources

Remotive is an **aggregator**: one API supplies jobs from many employers. Greenhouse, Lever, and Ashby are **ATS platforms**: each configured source points to one employer's publicly published job board. Add or remove employers in a local source list; no connector code changes are needed.

```text
Sources
├── Remotive — aggregator
├── Greenhouse — employer ATS
├── Lever — employer ATS
└── Ashby — employer ATS
```

The Greenhouse connector calls the public Job Board API at `https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true`. The board token is the slug from the company's public Greenhouse job-board URL. Its GET endpoints require no authentication. The jobs response does not document pagination; `content=true` includes descriptions, departments, and offices. A job post's `id`, `title`, `location.name`, `updated_at`, `absolute_url`, and optional `content`/`metadata` are mapped when present. The board API supplies one job URL, so the connector does not invent a separate apply URL. Employment type, salary, remote work, and eligibility remain unknown unless the API provides a structured field (custom board metadata is preserved in `raw_metadata`).

The Lever connector calls the public Postings API, normally `https://api.lever.co/v0/postings/{site}?mode=json`; use `https://api.eu.lever.co` for EU-hosted boards. The `site` is the public site slug. The public feed contains published postings; internal, draft, and other hidden postings are not returned. It supports `skip`/`limit` pagination (up to 100 per request) and documented filters such as location, commitment, team, department, and level. The connector reads all pages unless `max_jobs` is set. It maps the structured hosted/apply URLs, location, workplace type, commitment, optional salary range, and timestamps where available. Remote workplace mode does not establish which countries are eligible; `remote_eligibility` therefore stays unknown. Original JSON is kept in `raw_metadata`.

Both connectors make read-only GET requests to these public postings interfaces. They do not submit applications. Greenhouse's public GET documentation lists no attribution requirement or rate limit; Lever documents public postings and pagination, but no read-request rate limit in the Postings API guide. The runner uses bounded timeouts and does not retry requests automatically. Keep the request volume small and use the employer listing URL when sharing an individual offer.

Copy `config/examples/job_sources.example.json` to the ignored local path `job_sources.local.json`, then change the provider and public board identifier. The example names and IDs are fictitious. `company_name` is an optional display label; `region` is only used by Lever, and `max_jobs` caps normalized results (Lever can also stop fetching pages at that cap; Greenhouse exposes its jobs as one list). `job_sources.local.*` is ignored by Git.

Fetch and review configured boards, saving a private multi-source snapshot:

```powershell
python -m ai_job_hunter.jobs_cli --sources job_sources.local.json --candidate-config candidate.local.json --save-snapshot data/local/startup-jobs.local.json
```

Replay the snapshot offline without calling Greenhouse, Lever, or Remotive:

```powershell
python -m ai_job_hunter.jobs_cli --snapshot data/local/startup-jobs.local.json --candidate-config candidate.local.json
```

The snapshot stores each provider on each normalized offer. The runner reports `TOTAL`, deterministic `HARD SKIP`, and `JEV ELIGIBLE` counts and details. It does not call Jev. `--ingest` may be added to pass the fetched or replayed batch through the existing idempotent ingestion and cross-source matching pipeline after configuring the database. The previous Remotive snapshot format remains readable by the generic offline runner.

Documentation: [Greenhouse Job Board API](https://docs.greenhouse.io/job-board.html), [Lever Postings API](https://github.com/lever/postings-api), [Lever Postings API FAQ](https://hire.lever.co/developer/support).

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

There is no LinkedIn/Indeed/Wellfound job connector or browser scraping. Outreach can prepare local drafts, and assisted application preparation can draft a private review package; this project does not send messages, submit applications, or upload documents.

## Company Intelligence

Company Intelligence stores source-backed company evidence independently from candidate preferences and job decisions. It can build monitor targets for supported ATS boards, save normalized snapshots, and optionally run the deterministic pre-filter. It does not assign a company score or change Jev, `job_decision_v1`, or `job_decision_v2`. See [the Company Intelligence guide](docs/company-intelligence.md) for source scope, refresh behavior, and query examples.

## Candidate profile and deterministic pre-filter

`CandidateProfile` stores facts about a fictional or real candidate: experience, current role and salary, skills, technologies, languages, education, location, work authorization, eligible countries, and remote-work capability. `CandidatePreferences` stores search choices separately: salary floor and target, role/location preferences, acceptable employment types, work mode, relocation, technologies to prioritize or learn, seniority boundaries, and openness to international remote work. The configuration is validated with Pydantic and loaded from UTF-8 JSON; candidate data is not written to PostgreSQL.

The tracked example at [`config/examples/candidate.example.json`](config/examples/candidate.example.json) uses fictional values. Copy it to a local file before entering personal information:

```powershell
Copy-Item config/examples/candidate.example.json candidate.local.json
```

`candidate.local.*` and `candidate.*.local.json` / YAML files are ignored by Git. The loader rejects unknown fields, malformed JSON, salary thresholds without currency and period, and minimums above targets with a path and field-level error. Example usage:

```powershell
python -m ai_job_hunter.remotive_cli --candidate-config candidate.local.json --limit 20 --show 5
```

With `--candidate-config`, the CLI fetches Remotive offers once, prints PASS / REVIEW / REJECT counts, and shows a few titles, companies, decisions, reasons, and attributed Remotive links. This is preview-only and cannot be combined with `--ingest`; it does not connect to PostgreSQL or persist candidate or offer data.

For each offer, `JobFacts` reuses the deduplication title normalizer for title tokens and seniority, then carries the existing remote, location, structured salary, and employment fields. A small explicit technology vocabulary extracts names such as Python, Go/Golang, Node.js, AWS, PostgreSQL, and Kubernetes case-insensitively. It does not use AI or infer technologies from synonyms. A technology is treated as mandatory only when a nearby explicit phrase says `required`, `must have`, `mandatory`, `essential`, or similar. A missing required technology is a critical mismatch only if it is neither in the candidate profile, marked as learnable, nor covered by a same-family or backend foundation. An ordinary mention is a possible gap, never proof that the role requires that technology.

The pre-filter returns structured signal assessments and plain-language reasons:

- **PASS:** no configured hard mismatch or material unknown signal was found.
- **REVIEW:** a relevant signal is missing or ambiguous, or the offer has a non-critical stack gap, transferable stack gap, or learnable technology.
- **REJECT:** a clear conflict was found, such as an explicit country restriction excluding the candidate, a work mode or employment type outside configured limits, salary entirely below the configured floor in the same currency and period, seniority outside configured bounds, or a clearly mandatory technology absent without a transferable/learnable match.

Geography uses only known country aliases and the existing `RemoteEligibility` / `RemotePolicy` fields. Worldwide offers are compatible; EU and Spain restrictions are checked against the candidate's configured country; an explicit US-only restriction does not fit a candidate in Spain; unrecognized or absent geography is UNKNOWN and leads to review rather than rejection. There is no geocoding or external lookup. Preferred locations are soft signals; `acceptable_locations` constrains onsite/hybrid locations by direct text/country match only.

Salary is compared only when offer and preference currencies and periods match exactly. No currency or annualization conversions are made. A range wholly below the minimum is `BELOW_MINIMUM`; a range whose floor meets the configured target (or minimum, when no target exists) is `MEETS_TARGET`; a range that crosses the floor or target without guaranteeing it is `BETWEEN_MINIMUM_AND_TARGET`; absent or incompatible salary data is `UNKNOWN`. Unknown salary is never rejected.

This is an explainable first layer, not a final apply/no-apply recommendation. It does not calculate an arbitrary percentage score. Company-type, startup/product, and consulting preferences are deferred because current offer facts do not classify companies consistently.

## Jev decision engine

The optional Jev layer adds semantic judgments only after deterministic filtering:

```text
Job
  -> deterministic pre-filter
       -> hard REJECT / exact duplicate / clearly unrelated title: SKIP, no Jev call
       -> PASS or REVIEW: eligible for Jev
            -> typed Jev signals
                 -> deterministic APPLY / REVIEW / SKIP policy
```

The pre-filter keeps control of explicit geography, configured salary arithmetic, seniority boundaries, technology extraction, and repeated source IDs or job URLs. A small safe title rule also skips clear sales, customer support/service/success, writing/copywriting, and assistant roles without treating the word `Engineer` as evidence of backend fit. An unknown preferred-role match stays eligible for Jev.

### What Jev evaluates

One TypeSafe System One request asks seven independent typed questions. The state is compact and omits source URLs, candidate current salary, authorization details, and unrelated profile fields. It includes approximate experience, current/preferred roles, primary/secondary skills, technologies and willing-to-learn technologies; relevant salary preferences only when the offer has a comparable structured salary; current country and deterministic geography signals; offer title/company/location/work mode/employment type/description/structured salary/technologies/seniority; and the pre-filter outcome, reasons, and `JobFacts`.

The rubric is versioned as `job_decision_v1`. The exact prompts and score anchors live in [`src/ai_job_hunter/rubric.py`](src/ai_job_hunter/rubric.py) and are also included in the decision-cache key.

| Name / type | Question sent to Jev |
| --- | --- |
| `role_relevance` / Noul | Is this role substantively relevant to a software/backend engineering candidate? Assess the actual work and domain; penalize sales, customer support, copywriting, office-assistant, and unrelated duties. Do not treat a shared word such as Engineer as sufficient. |
| `experience_accessibility` / Noul | Given approximately this candidate's experience and the job requirements, is this role realistically accessible enough to justify applying? Requirements of 2 years or 2–3 years are not automatically hard blockers. Staff, Principal, Engineering Manager, or clearly senior roles requiring many years are normally inaccessible. Consider the offer's actual requirements and stated flexibility. |
| `backend_relevance` / Score 0–4 | How strongly does this role involve backend/software systems work relevant to this candidate? Consider full-stack, platform, generic software-engineer, AI-engineer, and support-engineering-like titles by the work described, not title keywords alone. |
| `stack_transferability` / Noul | Can the candidate's current backend foundation plausibly transfer to this job's core technology stack? Treat Java/Spring as a possible foundation for adjacent backend stacks such as Kotlin, Scala, Go, Python, Node.js, and cloud/backend work when the responsibilities support that transfer; do not imply transfer to a substantially different discipline. |
| `requirements_flexibility` / Noul | Do the stated requirements appear flexible enough that the candidate could reasonably apply despite not matching every listed technology or year requirement? Distinguish strict hard requirements from wish lists, broad marketplace technology catalogs, and generic mentions. |
| `career_value` / Score 0–4 | How much technical growth value could this role offer this candidate, based only on evidence in the offer? Consider production ownership, architecture, CI/CD, cloud, testing, backend systems, distributed systems, deployment, small engineering teams, and meaningful responsibility. If the offer does not provide enough information, reflect that uncertainty through low answer confidence. |
| `observable_role_quality` / Score 0–4 | How strong is the observable quality of this role description and role scope for this candidate? Use only information present in the offer. Do not use prior knowledge of the company name or infer company reputation, funding, culture, salary, or other company facts that are not stated. Sparse or generic information should have low confidence. |

Noul values are the SDK's 0–1 yes probability. Score answers use the five ordered rubric levels (0–4), normalized to 0–1 for the local policy; the SDK's score confidence and score probability distribution are retained when provided. The result stores all seven signals, confidence/probabilities, actual model returned by TypeSafe, SDK/model configuration, token counts when reported, rubric version, deterministic evidence, and evaluation timestamp. These signals are not claims about hiring probability.

### Final recommendation policy

The program, not Jev, chooses the final recommendation:

- A deterministic hard rejection or exact duplicate is `SKIP` without an engine call.
- Jev role relevance below `0.20` is `SKIP`; experience accessibility below `0.15` is `SKIP`.
- Any missing signal, or missing/less-than-`0.40` confidence on one of the three Score answers, yields `REVIEW` unless one of the two preceding Jev signals already justifies `SKIP`.
- `APPLY` requires role relevance ≥ `0.70`, experience accessibility ≥ `0.60`, backend relevance ≥ `0.60`, stack transferability ≥ `0.55`, requirements flexibility ≥ `0.45`, and observable role quality ≥ `0.35`, with adequate Score confidence.
- Career value ≥ `0.80` may lower the stack threshold to `0.45` and requirements-flexibility threshold to `0.35`. It cannot override relevance, accessibility, backend, quality, or deterministic constraints.
- Contradictory role/backend, backend/stack, or experience/career-value signals yield `REVIEW`. Other results that do not meet all `APPLY` gates are also `REVIEW` with reasons constructed from the signal values.

Jev handles ambiguous role relevance, experience accessibility, backend relevance, stack transferability, requirement flexibility, career value, and observable role-description quality. It does not enforce geography, perform salary arithmetic, infer seniority tokens, extract technologies, identify source records, deduplicate, decide database behavior, auto-apply, or estimate the probability of getting hired. The evaluation path does not perform external Company Intelligence, application submission, or outreach.

## Opportunity feed and application tracking

The local workflow composes the existing monitor and decision layers:

```text
Company Monitor -> ATS fetch -> ingestion/deduplication -> new or changed source facts
  -> deterministic prefilter -> Jev + job_decision_v2 -> opportunity feed
  -> human review -> application tracking
```

Run the Alembic migration before the first refresh, then use the unified CLI:

```powershell
alembic upgrade head
python -m ai_job_hunter.cli refresh --limit-companies 10 --max-jobs-per-company 100 --max-jev-jobs 20
python -m ai_job_hunter.cli opportunities --decision apply --limit 10
python -m ai_job_hunter.cli opportunities --decision review --limit 10
python -m ai_job_hunter.cli opportunities --status new --remote --company Example --technology python
python -m ai_job_hunter.cli show JOB_ID
python -m ai_job_hunter.cli seen JOB_ID
python -m ai_job_hunter.cli save JOB_ID
python -m ai_job_hunter.cli dismiss JOB_ID
python -m ai_job_hunter.cli apply JOB_ID --source "company site" --url https://example.test/apply
python -m ai_job_hunter.cli application JOB_ID --status interview --note "First interview"
```

`--no-jev` records uncached eligible jobs as `PENDING`; pending work is not represented as `REVIEW`. `--max-jev-jobs` bounds new Jev calls for one refresh while usable cache entries are still read. Jobs deferred by that budget stay pending on an identical refresh; raise the budget or pass `--retry-pending` to explicitly resume them. `--dry-run` fetches and prefilters without database or Jev writes. The refresh is limited to currently monitored Greenhouse, Lever, and Ashby boards and does not call Remotive.

`JobEvaluation` is versioned by a fingerprint covering source/job facts, candidate profile and preferences, prefilter/policy, rubric, and relevant engine configuration. A changed input gets a new evaluation; an unchanged evaluated fingerprint is reused. `JobReview` independently stores `NEW`, `SEEN`, `SAVED`, or `DISMISSED`, so system `SKIP` and human dismissal remain distinct. Repeated ingestion and another source deduplicated to the same job do not reset that state. Applications are separate and keep an append-only status event history.

The feed hides system `SKIP`, dismissed jobs, and jobs with a tracked application by default; explicit filters can show those records. Within visible `APPLY` and `REVIEW`, priority is the rounded equal-weight mean of `role_relevance`, `backend_relevance`, `stack_transferability`, `experience_accessibility`, `requirements_flexibility`, and `career_value`, scaled to 0–100. If any signal is missing, priority is `UNKNOWN`. This is a deterministic ordering aid, not an estimate of hiring probability. `APPLY` means the system recommends considering an application; it does not submit one. Company salary/evidence, ATS support, and freshness appear as context only and do not alter `job_decision_v2`.

## Assisted application preparation

The local-only `apply prepare JOB_ID` workflow extracts requirements and
structured questions already present in saved ATS data, maps them to configured
candidate facts, and prepares draft answers and document recommendations for
human review. It does not change APPLY/REVIEW/SKIP decisions, use browser
automation, submit forms, or upload documents. Packages are kept in the ignored
`data/local/application-packages.local.json` file. See
[`docs/assisted-application.md`](docs/assisted-application.md) for the full
workflow, local configuration, readiness rules, and ATS capability comparison.

```text
Opportunity
 ↓
Application Preparation
 ↓
Requirements
 ↓
Candidate Fit
 ↓
Questions
 ↓
Draft Answers
 ↓
Document Recommendation
 ↓
Human Review
 ↓
READY_TO_SUBMIT
 ↓
[Future Assisted Browser Submission]
```

## Outreach and referrals

Outreach is a separate, conservative workflow. It does not modify `job_decision_v2` or the candidate profile/preferences:

```text
Opportunity
  -> outreach recommendation
  -> contact strategy
  -> ContactProvider
  -> local draft
  -> human approval
  -> [future sending integration]
```

**No messages are sent by AI Job Hunter.** There is no send command or delivery client. `approve` only changes the saved draft's lifecycle state. The `SENT` state is reserved for a future manual record of a message sent outside the application.

The initial recommendation rules are deterministic: `APPLY` with no application record and no active outreach is `OUTREACH_RECOMMENDED`; `REVIEW` is `OUTREACH_OPTIONAL` only when priority is at least 70, role relevance is at least 0.75, there is no strong mismatch, and no application or active outreach exists; `SKIP`, an existing application record, active outreach, or an unmet/unknown `REVIEW` gate produces `NO_OUTREACH`. This is an eligibility rule, not a probability or a change to the job decision.

Contact roles are suggested from the job title and any explicit company-size evidence; the order is contextual rather than a universal ranking. The provider interface currently ships only `ManualContactProvider` and `FakeContactProvider`. They make no network requests. There is no LinkedIn scraping, private API use, or live contact search. Existing local contacts can be reviewed with `outreach contacts JOB_ID`.

The deterministic templates cover recruiter introductions, referral requests, hiring-manager introductions, engineer/potential-referral messages, and cold outreach when no job is attached. Drafts use only configured candidate facts, job facts, explicitly entered contact facts, and at most one relevant configured project. No candidate identity, relationship, email address, job requirement, or prior familiarity is invented. If no local contact exists, a draft records only a contact-type placeholder; it does not create a fictional person.

Copy [`config/examples/candidate_projects.example.json`](config/examples/candidate_projects.example.json) to `candidate_projects.local.json` only if you want to configure public project details. The local file is ignored by Git. Contact records and saved drafts live in the ignored local database; do not add them to fixtures or tracked configuration.

```powershell
python -m ai_job_hunter.cli outreach candidates
python -m ai_job_hunter.cli outreach strategy JOB_ID
python -m ai_job_hunter.cli outreach contacts JOB_ID
python -m ai_job_hunter.cli outreach draft JOB_ID
python -m ai_job_hunter.cli outreach show OUTREACH_ID
python -m ai_job_hunter.cli outreach approve OUTREACH_ID
```

Apply the new additive migration with `alembic upgrade head` before using outreach persistence. The feed displays a compact `RECOMMENDED`, `OPTIONAL`, or `NO` outreach label. No contacts are looked up automatically, and no drafts are approved automatically.

### Official SDK and authentication

The implementation uses TypeSafe AI's official [`typesafe-sdk` Python SDK](https://github.com/typesafe-ai/typesafe-sdk-python), pinned to **0.7.1**. Its client reads `TYPESAFE_API_KEY` from the process environment and defaults to the currently recommended `jev-latest` model; the CLI records the concrete model name returned by each request. Sync `TypeSafeClient.system_one(state=..., questions=...)` accepts named `Noul` and `Score` question objects and returns typed answers, model metadata, and reported token usage. The official `system-one-adapter-python` was reviewed, but is not installed: it requires configuring a separate LLM provider and is unnecessary for offline tests or the Jev integration.

Install the development/test and Jev extras:

```powershell
python -m pip install -e ".[dev,jev]"
```

Set the key only in the current PowerShell process before live evaluation; do not put it in source control:

```powershell
$env:TYPESAFE_API_KEY = "<your TypeSafe API key>"
```

An offline dry-run over a saved snapshot makes no Remotive or Jev requests:

```powershell
python -m ai_job_hunter.remotive_cli `
  --candidate-config candidate.local.json `
  --snapshot data/local/remotive-snapshot-2026-09-24.local.json `
  --dry-run-jev --max-jev-jobs 1
```

To deliberately enable live Jev evaluation, use `--decision-engine jev`. If the key is missing, the CLI exits with an explicit error and never falls back to another engine. `--max-jev-jobs N` limits new evaluations; valid cached results do not consume the limit. `--jev-model` selects a model name, and its configured value participates in cache identity.

The JSON decision cache defaults to `data/local/job-decision-cache.local.json`, which is ignored with the private local data directory. It stores structured results, not the full prompt state. Its key covers source identity and effective job facts/description, the candidate profile and preferences, deterministic result, SDK/model configuration, rubric version, prompts, and score anchors. Changing any of these produces a cache miss. The concrete model returned by TypeSafe is retained for audit; pin `--jev-model` to a concrete model name when you want to avoid following the `jev-latest` alias.

Tests use a fake engine or synthetic SDK response and never need an API key or network access.

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
- Candidate-specific runtime data belongs in ignored local configuration; the checked-in profile example is fictional.

## Roadmap (indicative)

1. Phase 1 - Core/domain/persistence
2. Phase 2 - Job ingestion + normalization
3. Phase 3 - Deterministic deduplication (initial conservative rules implemented)
4. Phase 4 - Company Intelligence
5. Phase 5 - Decision Engine + Jev (implemented)
6. Phase 6 - Application Tracking
7. Phase 7 - Outreach / Referrals (local draft workflow implemented; sending remains future work)
8. Phase 8 - Assisted application preparation (local drafts only; submission remains future work)

Future applications, outreach, and messages should require explicit user approval before they are sent.
