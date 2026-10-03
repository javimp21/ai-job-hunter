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

Supported ATS providers (public, keyless connectors): Greenhouse, Lever, Ashby, Teamtailor (`{company}.teamtailor.com/jobs.rss`) and SmartRecruiters (`api.smartrecruiters.com/v1/companies/{companyId}/postings`). Discovery matches exact hosts only (`jobs.`/`careers.smartrecruiters.com/{CompanyId}`, `{company}.teamtailor.com`); custom career domains are not detected and stay UNKNOWN. Neither connector derives remote eligibility: Teamtailor's `remoteStatus` and SmartRecruiters' `remote` flag only describe work mode.

## Job portals

Besides ACTIVE company boards, `refresh`/`run` query the job portals listed in `JOB_PORTALS` (default `himalayas`; set it empty in `.env` to disable). Portals are searched with filters (country Spain, backend/software/platform/Java keywords), not crawled, and each one is queried at most once per polling interval (Himalayas: 20 h, state in `data/local/portal-state.json`; `--dry-run` never advances it).

Himalayas gives each remote job's allowed countries: an empty list is worldwide, `Spain` alone is Spain-only, and any other list is country-restricted, so a list without Spain is a deterministic geography SKIP. Salary ranges are kept when published. Its terms require a visible credit, so alerts from it show "Fuente: Himalayas". Portal jobs go through the normal ingestion, deduplication, prefilter, Jev and notification pipeline.

## Closed postings

Every ingest updates a job source's `last_seen_at` and clears `closed_at`. After a refresh, a posting of an ACTIVE company board is marked closed (`closed_at`) when that board was fetched successfully and completely but no longer lists it. Boards that failed, returned nothing, or hit `--max-jobs-per-company` (a truncated listing) never close anything, and portal results (search-based) never do either. A job whose sources are all closed leaves the feed and cannot alert; if it is listed again it reopens automatically.
