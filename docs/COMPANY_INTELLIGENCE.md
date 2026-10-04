# Company Intelligence & Leads

## Evidence

Discovery hints are not facts.

Examples:

- EU remote;
- global;
- hiring;
- curated-list descriptions;
- inferred technologies.

Do not infer without evidence:

- ATS;
- remote-from-Spain eligibility;
- salary;
- company size/type;
- contacts;
- email addresses.

## Provenance

Preserve the origin of important company intelligence.

Prefer evidence that can later be inspected or refreshed.

## Contacts

Never invent:

- people;
- titles;
- emails;
- LinkedIn profiles;
- social handles.

Do not generate guessed addresses such as:

`firstname.lastname@company.com`

and represent them as discovered contacts.

Prefer authorized providers/connectors over aggressive scraping.

`outreach find-contacts` (Company Hunter) is the only discovery of people. It reads the company's own public pages (team/about, engineering-blog authors, a GitHub org the company's site links to) with robots.txt respected, spacing and page budgets, stores a contact only with a name and a stated role plus source URL and evidence, stores an email only when an official company-domain page links it next to that person, and stores nothing otherwise. See `docs/COMPANY_HUNTER.md`.

## Leads

Keep discovery, enrichment and final decision logically separate.

A promising signal may justify further investigation without becoming a verified fact.

## Monitored sources (review lifecycle)

`refresh`/`run` fetch only company boards in `monitored_sources` with state `ACTIVE`. Leads cover the earlier steps (`NEW` ≈ discovered, `SUPPORTED_ATS`/`RESOLVED` ≈ resolved); every supported board found in company evidence is recorded once in `REVIEW_SOURCE` and is **never fetched until explicitly activated**. `PAUSED` and `REJECTED` boards are not fetched. A board is unique by provider + identifier + region, so it cannot be monitored twice.

```powershell
ai-job-hunter sources list --state review_source
ai-job-hunter sources activate <source-id> --reason "backend roles, remote EU"
ai-job-hunter sources reject <source-id> --reason "mostly sales roles"
```

Each refresh records new boards for review, fetches ACTIVE boards least-recently-fetched first (so `--limit-companies` rotates through all of them) and stores the last fetch time, status, job count and consecutive failures. `sources sync --activate-current` exists only for the one-time adoption of boards that were monitored before this lifecycle existed (done 2026-10-03 for the 11 original companies).

Supported ATS providers (public, keyless connectors): Greenhouse, Lever, Ashby, Teamtailor (`{company}.teamtailor.com/jobs.rss`), SmartRecruiters (`api.smartrecruiters.com/v1/companies/{companyId}/postings`), Workable (`apply.workable.com/api/v1/widget/accounts/{slug}?details=true`) and Personio (`{company}.jobs.personio.de/xml`, region `com` for `.jobs.personio.com`). Discovery matches exact hosts only (`jobs.`/`careers.smartrecruiters.com/{CompanyId}`, `{company}.teamtailor.com`, `apply.workable.com/{slug}`, `{company}.jobs.personio.de|com`); custom career domains are not detected and stay UNKNOWN. No connector derives remote eligibility: Teamtailor's `remoteStatus`, SmartRecruiters' `remote` flag and Workable's `telecommuting=true` only describe work mode (Workable `false` and Personio, which has no work-mode field, stay unknown). Workday (`{tenant}.{wdN}.myworkdayjobs.com/{site}`, public CXS JSON: `POST /wday/cxs/{tenant}/{site}/jobs` with 20-posting pages, one `GET` detail per posting that passes the title pre-filter; identifier `tenant/site`, region = data centre `wdN`, both required and validated; `published_at` is approximated (day precision) from the list's relative text ("Posted 3 Days Ago", "30+" as a lower bound); by default only Spain is fetched, using the site's own location facets (the `locationCountry` Spain id, else Spanish `locations` values; a site with location facets but nothing in Spain returns no jobs); discovery matches `{tenant}.wdN.myworkdayjobs.com/[locale/]{site}` only). Workday `remoteType` is mapped only when it is an explicit Remote/Hybrid/On-site label and never sets remote eligibility. SAP SuccessFactors, Oracle Recruiting, Eightfold, Avature, iCIMS and Phenom are not supported: no public structured source was verified. Factorial HR careers sites (`*.factorialhr.com`, `*.factorial.es`) are not supported: they expose no feed, API or JSON-LD, only HTML.

## Job portals

Besides ACTIVE company boards, `refresh`/`run` query the job portals listed in `JOB_PORTALS` (default `himalayas,manfred`; set it empty in `.env` to disable). Portals are searched with filters (country Spain, backend/software/platform/Java keywords), not crawled, and each one is queried at most once per polling interval (Himalayas: 20 h, state in `data/local/portal-state.json`; `--dry-run` never advances it).

Himalayas gives each remote job's allowed countries: an empty list is worldwide, `Spain` alone is Spain-only, and any other list is country-restricted, so a list without Spain is a deterministic geography SKIP. Salary ranges are kept when published. Its terms require a visible credit, so alerts from it show "Fuente: Himalayas". Portal jobs go through the normal ingestion, deduplication, prefilter, Jev and notification pipeline.

Manfred (getmanfred.com, Spanish tech jobs) is read from the public JSON its own site uses (`/api/v2/public/offers`, undocumented, so any shape change fails the portal with a clear error and the refresh continues). The listing holds every offer ever published; only `ACTIVE` ones are kept (about 20 at a time) and each one's detail supplies the description, technologies and `lastStatusChange`, used as the publication date (when the offer last became active; `updatedAt` is only the last edit). `remotePercentage` maps 100 to remote, 0 to on-site and anything between to hybrid; salaries are gross annual and kept only with a known currency. Polled at most hourly; alerts show "Fuente: Manfred".

### Additional portals

Enable them with `JOB_PORTALS` (comma-separated); the default is `himalayas,manfred,remotive,jobicy,adzuna` (`adzuna` is skipped until its keys are set; `remoteok` is off because applying through it requires a paid plan) (add `adzuna` once its keys are set). Each is throttled through `data/local/portal-state.json` and shows a visible credit and link in alerts and digests (`portal_credit` in `services/notifications.py`).

| Portal | Interval | Notes |
| --- | --- | --- |
| `adzuna` | 12 h | Adzuna API Spain. Needs `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` (secrets, blank in `.env.example`); without them the portal is skipped with a warning and nothing is recorded. 8 searches (backend / Java / Python / AI engineer in Madrid, and the same with "remoto" nationwide) x up to 2 pages of 50 = at most 16 calls per run, far under the ~250/day free tier. Salary is kept only when `salary_is_predicted` is not set (predicted salaries are estimates). It has no work-mode or eligibility field, so both stay unknown; descriptions are truncated snippets. Credit: "Jobs by Adzuna". |
| `remoteok` | 4 h | `https://remoteok.com/api`; the legal-notice element is skipped. The apply link is the Remote OK listing (terms require linking back). Only an explicit "worldwide" location sets eligibility; other text stays in `location`. Salary is yearly USD when non-zero. |
| `remotive` | 6 h | Reuses `RemotiveConnector` with one request for category `software-dev`. |
| `jobicy` | 4 h | `https://jobicy.com/api/v2/remote-jobs?count=50&geo=spain`; the listing URL (which leads to the original posting) is the apply link. "Anywhere" is worldwide and exactly "Spain" is Spain-only; any other `jobGeo` (e.g. "Europe") stays in `location` as unknown for the geography check. |

Response shapes were written from each provider's public documentation; they were not verified against live responses from the development sandbox (network policy blocked these hosts), so run `refresh --dry-run` once with the portal enabled and check the first results.

## Closed postings

Every ingest updates a job source's `last_seen_at` and clears `closed_at`. After a refresh, a posting of an ACTIVE company board is marked closed (`closed_at`) when that board was fetched successfully and completely but no longer lists it. Boards that failed, returned nothing, or hit `--max-jobs-per-company` (a truncated listing) never close anything, and portal results (search-based) never do either. A job whose sources are all closed leaves the feed and cannot alert; if it is listed again it reopens automatically.
