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

Supported ATS providers (public, keyless connectors): Greenhouse, Lever, Ashby, Teamtailor (`{company}.teamtailor.com/jobs.rss`), SmartRecruiters (`api.smartrecruiters.com/v1/companies/{companyId}/postings`), Workable (`apply.workable.com/api/v1/widget/accounts/{slug}?details=true`) and Personio (`{company}.jobs.personio.de/xml`, region `com` for `.jobs.personio.com`). Discovery matches exact hosts only (`jobs.`/`careers.smartrecruiters.com/{CompanyId}`, `{company}.teamtailor.com`, `apply.workable.com/{slug}`, `{company}.jobs.personio.de|com`); custom career domains are not detected and stay UNKNOWN. No connector derives remote eligibility: Teamtailor's `remoteStatus`, SmartRecruiters' `remote` flag and Workable's `telecommuting=true` only describe work mode (Workable `false` and Personio, which has no work-mode field, stay unknown). Workday (`{tenant}.{wdN}.myworkdayjobs.com/{site}`, public CXS JSON: `POST /wday/cxs/{tenant}/{site}/jobs` with 20-posting pages, one `GET` detail per posting that passes the title pre-filter; identifier `tenant/site`, region = data centre `wdN`, both required and validated; `published_at` is approximated (day precision) from the list's relative text ("Posted 3 Days Ago", "30+" as a lower bound); by default only Spain and the preferred relocation countries (Luxembourg, Switzerland, Netherlands, Ireland) are fetched, using the site's own location facets (their `locationCountry` ids, else `locations` values naming them or a main city; a site with location facets but nothing there returns no jobs); discovery matches `{tenant}.wdN.myworkdayjobs.com/[locale/]{site}` only). Workday `remoteType` is mapped only when it is an explicit Remote/Hybrid/On-site label and never sets remote eligibility. SAP SuccessFactors, Oracle Recruiting, Eightfold, Avature, iCIMS and Phenom are not supported: no public structured source was verified. Factorial HR (`{slug}.factorialhr.com`, region `com`, and `{slug}.factorial.es`, region `es`; identifier = slug) has no feed, API or JSON-LD, so the connector parses server-rendered HTML with the standard library only: it reads `/robots.txt` first and refuses to continue if it disallows the careers page (e.g. `factorial.factorialhr.com` itself disallows everything and is therefore not fetched), makes one request for the listing page (job cards: `data-job-postings-url`, `data-is-remote`, `data-contract-type`, visible title, team and work-mode cells, office `h3` heading as location), and fetches a detail page (description from `styledText`, full location and Full/Part time schedule when stated) only for titles passing `title_may_be_relevant`, at most 25 per run, 1 s apart, with 2 MB listing / 1 MB detail size caps and no redirect following (a host that redirects to the other region, such as `nextaillabs.factorialhr.com` to `nextaillabs.factorial.es`, fails with a hint to use the right region). Only explicit work-mode labels (Remote/Hybrid/Onsite, or Remoto/Híbrido/Presencial) set `remote_policy`; contract type (`indefinite`) is kept in metadata and not mapped to an employment type; `published_at` is left unknown (the sitemap `lastmod` is not a publication date) and remote eligibility is never derived. Discovery matches `{slug}.factorialhr.com` and `{slug}.factorial.es` exactly (not `www`, `app`, `api`, `help`, `blog`, `support`, `assets`).

## Job portals

Besides ACTIVE company boards, `refresh`/`run` query the job portals listed in `JOB_PORTALS` (default `himalayas,manfred`; set it empty in `.env` to disable). Portals are searched with filters (country Spain, backend/software/platform/Java keywords), not crawled, and each one is queried at most once per polling interval (Himalayas: 20 h, state in `data/local/portal-state.json`; `--dry-run` never advances it).

Himalayas gives each remote job's allowed countries: an empty list is worldwide, `Spain` alone is Spain-only, and any other list is country-restricted, so a list without Spain is a deterministic geography SKIP. Salary ranges are kept when published. Its terms require a visible credit, so alerts from it show "Fuente: Himalayas". Portal jobs go through the normal ingestion, deduplication, prefilter, Jev and notification pipeline.

Manfred (getmanfred.com, Spanish tech jobs) is read from the public JSON its own site uses (`/api/v2/public/offers`, undocumented, so any shape change fails the portal with a clear error and the refresh continues). The listing holds every offer ever published; only `ACTIVE` ones are kept (about 20 at a time) and each one's detail supplies the description, technologies and `lastStatusChange`, used as the publication date (when the offer last became active; `updatedAt` is only the last edit). `remotePercentage` maps 100 to remote, 0 to on-site and anything between to hybrid; salaries are gross annual and kept only with a known currency. Polled at most hourly; alerts show "Fuente: Manfred".

### Additional portals

Enable them with `JOB_PORTALS` (comma-separated); the default is `himalayas,manfred,remotive,jobicy,adzuna,arbeitnow,fourdayweek` (`adzuna` is skipped until its keys are set; `remoteok` is off because applying through it requires a paid plan; `weworkremotely` is opt-in, see below). Each is throttled through `data/local/portal-state.json` and shows a visible credit and link in alerts and digests (`portal_credit` in `services/notifications.py`).

| Portal | Interval | Notes |
| --- | --- | --- |
| `adzuna` | 12 h | Adzuna API Spain. Needs `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` (secrets, blank in `.env.example`); without them the portal is skipped with a warning and nothing is recorded. 8 searches (backend / Java / Python / AI engineer in Madrid, and the same with "remoto" nationwide) x up to 2 pages of 50 = at most 16 calls per run, far under the ~250/day free tier. Salary is kept only when `salary_is_predicted` is not set (predicted salaries are estimates). It has no work-mode or eligibility field, so both stay unknown; descriptions are truncated snippets. Credit: "Jobs by Adzuna". |
| `remoteok` | 4 h | `https://remoteok.com/api`; the legal-notice element is skipped. The apply link is the Remote OK listing (terms require linking back). Only an explicit "worldwide" location sets eligibility; other text stays in `location`. Salary is yearly USD when non-zero. |
| `remotive` | 6 h | Reuses `RemotiveConnector` with one request for category `software-dev`. |
| `jobicy` | 4 h | `https://jobicy.com/api/v2/remote-jobs?count=50&geo=spain`; the listing URL (which leads to the original posting) is the apply link. "Anywhere" is worldwide and exactly "Spain" is Spain-only; any other `jobGeo` (e.g. "Europe") stays in `location` as unknown for the geography check. |
| `arbeitnow` | 3 h | `https://www.arbeitnow.com/api/job-board-api`, first page only (~325 newest jobs, refreshed hourly; mostly Germany/EU on-site). Terms section 11 allow API use with a link back to Arbeitnow.com; robots.txt allows everything. The feed also holds the `.co.uk`, `.fr` and `.ch` mirrors, accepted as the portal's own hosts. Nothing is filtered here: `remote: true` sets REMOTE, `remote: false` leaves the work mode unknown, eligibility stays unknown and the prefilter decides. Credit: "Arbeitnow". |
| `fourdayweek` | 6 h | `https://4dayweek.io/api/v2/jobs?work_arrangement=remote&category=engineering&posted_after=7&limit=100`, up to 3 pages 2 s apart (docs: free, no auth, 60 req/min/IP, link back requested; robots.txt allows `/api/v2`). Eligibility comes from `locations[]` entries that allow remote work (countries stay in `location`; exactly Spain is Spain-only). Salary is not mapped: the live values look like minor units while the docs say dollars, so they stay in `raw_metadata`. Credit: "4dayweek.io". |
| `weworkremotely` | 4 h | Opt-in (add it to `JOB_PORTALS`). Three category RSS feeds (back-end, full-stack, devops) 2 s apart; robots.txt allows them and the feeds have `ttl` 60. Its terms page returns 403 to automated clients, so the terms could not be read: enable it only after reading https://weworkremotely.com/terms yourself. "Anywhere in the World" without a country list is worldwide; any other region or country list is a restriction kept in `location`. Credit: "We Work Remotely". |

Arbeitnow, 4dayweek.io and We Work Remotely were checked against live responses on 2026-10-04 (shapes in `tests/test_more_portals.py`). Response shapes of the older portals were written from each provider's public documentation; were written from each provider's public documentation; they were not verified against live responses from the development sandbox (network policy blocked these hosts), so run `refresh --dry-run` once with the portal enabled and check the first results.

### Regional portals evaluated and not integrated (checked 2026-10-04)

Luxembourg, Switzerland, the Netherlands, Ireland and EU-wide portals were checked with read-only `robots.txt`/homepage requests. None offers a documented public feed or API for third parties, so none is a portal here; reaching them would mean scraping listings.

| Portal | Result |
| --- | --- |
| jobs.lu | No feed or API found; `robots.txt` redirects to `en.jobs.lu`, which returned an error page. |
| moovijob.com | No RSS/API (`/rss` is the homepage); `robots.txt` blocks offer-detail paths. A sitemap exists but is for search engines. |
| ADEM (adem.public.lu) | No postings feed; its open-data set on data.public.lu is only skills statistics. `robots.txt` blocks query URLs. |
| jobs.ch / jobup.ch | No public API; `robots.txt` disallows `/api/` and vacancy detail pages. |
| job-room.ch (SECO) | `robots.txt` asks crawlers not to read job adverts. |
| swissdevjobs.ch | Cloudflare challenge (403) for non-browser clients; not bypassed. |
| werk.nl | No public vacancy API found; the site answers non-browser requests with a session redirect. |
| nationalevacaturebank.nl, werkzoeken.nl | Web application firewall returns 403 to non-browser clients; not bypassed. |
| irishjobs.ie / jobs.ie | No feed or API found; `robots.txt` restricts search/filter URLs and `/jobs/permanent` for general crawlers and disallows everything for several named bots. |
| EURES | No documented third-party API. The portal's search endpoint is an undocumented frontend API (the published specs are community reverse-engineering); the legal notice allows reuse with acknowledgement of ELA but says nothing about automated access. Needs an explicit decision before use. |
| germantechjobs.de | Not one of the four target countries; its JSON endpoint is undocumented. |

Adzuna's documented API also searches the Netherlands (`nl`) and Switzerland (`ch`, salaries in CHF); the default searches include both (Adzuna has no Ireland or Luxembourg site).

Employers in these countries are covered through their ATS boards instead: see `config/leads/high-pay-europe-2026-10.json`.

## Closed postings

Every ingest updates a job source's `last_seen_at` and clears `closed_at`. After a refresh, a posting of an ACTIVE company board is marked closed (`closed_at`) when that board was fetched successfully and completely but no longer lists it. Boards that failed, returned nothing, or hit `--max-jobs-per-company` (a truncated listing) never close anything, and portal results (search-based) never do either. A job whose sources are all closed leaves the feed and cannot alert; if it is listed again it reopens automatically.
