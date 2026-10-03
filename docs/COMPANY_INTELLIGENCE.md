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
