# Company Intelligence

Company Intelligence keeps attributable observations about employers separate from job decisions. `CompanyEvidence` stores a provider, source key and URL, optional external identifier, evidence type, structured facts, source metadata, and discovery/update timestamps. A company can have evidence from several providers. `CompanyFacts` derives career pages, recognizable ATS boards, remote-from-Spain and public-salary states, salary evidence and its context, source counts, and freshness. Missing evidence stays `UNKNOWN`; there is no company score or automatic company-type classification.

The additive Alembic migration is `0004_company_evidence`. Apply it to the configured database before using the CLI:

```powershell
alembic upgrade head
```

Refresh sources only when explicitly requested. Online refresh makes two bounded GET requests, to the supported source READMEs, and writes ignored local snapshots under `data/local/company-intelligence/source-snapshots/`. Replay uses those snapshots without network:

```powershell
python -m ai_job_hunter.company_cli refresh
python -m ai_job_hunter.company_cli refresh --offline
python -m ai_job_hunter.company_cli summary
python -m ai_job_hunter.company_cli show "New Relic"
python -m ai_job_hunter.company_cli show-job JOB_UUID
python -m ai_job_hunter.company_cli find --public-salary --supported-ats
```

The CLI accepts `--database-url` before or after the subcommand, which is useful for a local SQLite catalog. `find` requires at least one structured filter from `--spanish-top-tech`, `--remote-from-spain`, `--has-career-page`, `--supported-ats`, `--public-salary`, `--compensation-evidence`, or `--multiple-evidence-sources`. It lists matches alphabetically, without a ranking. Greenhouse, Lever, and Ashby are supported ATS connectors.

## ATS discovery and public job monitoring

ATS discovery matches exact known public hostnames only: `boards.greenhouse.io` and `job-boards.greenhouse.io` (board token), `jobs.lever.co` and `jobs.eu.lever.co` (site slug plus global/EU region), and `jobs.ashbyhq.com` (board name). LinkedIn, generic career pages, malformed URLs, and lookalike hostnames stay `UNKNOWN`. Discovery does not fetch or scrape career pages. Evidence from a persisted `JobSource` or a saved normalized jobs snapshot is recorded as `ATS_OBSERVED` and takes precedence over simple URL inference; support references retain source IDs, URLs, and discovery times. Reprocessing merges references into the same evidence row.

Use a structured filter and a company cap when monitoring. The command fetches only supported Greenhouse, Lever, and Ashby public APIs, writes a local multi-source snapshot, and can optionally run the deterministic pre-filter using a candidate config. It never calls Jev. The default cap is ten distinct companies; choose a smaller cap for a smoke test.

```powershell
python -m ai_job_hunter.company_cli monitor `
  --supported-ats `
  --limit-companies 10 `
  --max-jobs-per-company 100 `
  --candidate-config candidate.local.json
```

The command passes fetched normalized offers through the existing ingestion/deduplication pipeline in an in-memory database for a bounded sample report; it does not write those jobs to the configured database. Snapshot paths under `data/local/` are ignored by Git. Ashby uses its documented [public Job Posting API](https://developers.ashbyhq.com/docs/public-job-posting-api) and requests structured compensation where available. Remote workplace mode does not imply eligible countries; compensation is accepted only when the public API provides an unambiguous salary component, currency, interval, and range.

## Source scope and limits

| Source | Imported evidence | License and constraints |
| --- | --- | --- |
| [Spanish Top Tech Companies](https://github.com/pugarte7/spanish-top-tech-companies) | The README's published aggregate company tables: their stated base/total pay metric, sample count, observation period, population context, share above the stated threshold, source links, and jobs links when present. The importer does not retrieve Levels.fyi pages or the repository's CSV. | The repository labels its generated tables and companies.csv CC BY-SA 4.0, while explicitly excluding underlying third-party Levels.fyi submissions from that license. Attribution and the license URL are retained with imported evidence; salary observations remain scoped to the source's experienced-engineer population and are not junior salary estimates. At review time, the README reported a last run of 2026-09-23 and GitHub showed a repository update on 2026-09-24. See the [data license](https://github.com/pugarte7/spanish-top-tech-companies/blob/main/LICENSE-DATA). |
| [Manfred public-salary companies](https://github.com/getmanfred/companies-with-public-salary) | Company name and careers URL from its README table, as evidence that the directory identifies the company as publishing salary ranges. No salary amount, sample size, or period is inferred. | The repository provides an Apache-2.0 license; repository and license URLs are retained. GitHub showed a repository update on 2026-09-02 during this review; no fixed refresh cadence or salary observation period is stated in the README. See its [license](https://github.com/getmanfred/companies-with-public-salary/blob/main/LICENSE). |
| [Remote ES](https://github.com/remote-es/remotes) | Not imported. | The public README describes a list of companies with remote work under Spanish contracts, but no explicit data license was found in the repository's root files or GitHub license metadata during this review. A repository update cadence was not established. The list is not copied, refreshed, or used to assert remote-from-Spain evidence. Reassess its terms before a future import. |

README snapshots and source manifests are local ignored data. Tests use versioned, small fixtures and make no network requests. Company identity uses exact conservative name normalization (including known legal suffix removal) and exact website hostname when supplied. Conflicting domains are kept separate and surfaced as possible matches; text similarity alone does not merge companies. A career page URL can be stored even when it is not an ATS URL. Greenhouse, Lever, and Ashby hostnames are recognized without following links or scraping pages; `UNKNOWN` remains explicit when no supported evidence exists.

Remote-from-Spain is modeled as company-level evidence only. It does not establish that an individual role supports Spain, and is not propagated to `Job.remote_eligibility`. Company facts are not inputs to APPLY / REVIEW / SKIP, Jev, either decision rubric, candidate profile data, or candidate preferences.
