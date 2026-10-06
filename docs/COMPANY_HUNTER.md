# Company Hunter

Surfaces companies that fit the candidate **even when they have no matching open role**, finds verifiable public contacts, prepares (never sends) short outreach drafts, and runs a manual LinkedIn connection queue. It extends the existing outreach subsystem (`Contact`, `Outreach`, `OutreachEvent`, `outreach` CLI) and Company Intelligence (company leads, monitored sources); it does not replace them.

Code: `src/ai_job_hunter/company_hunter/` (`ranking`, `fetching`, `people`, `contacts`, `writing`, `service`, `queue`, `notify`, `bot`, `cli`). Migration: `0014_company_hunter`.

## Safety guarantees

- **Nothing is ever sent to a company or to LinkedIn.** Drafts are `Outreach` rows in `DRAFT`; the only transmissions are Telegram messages to the candidate's *own* chat (`weekly --send`, `connections --send`, bot replies), and they require `--send` or the running bot. No `send`/`connect` command exists (tested).
- **LinkedIn is never fetched, scraped or logged into.** `PoliteFetcher` refuses every `linkedin.com` host. A LinkedIn profile URL is stored/shown only if it is linked from a public non-LinkedIn page we already fetched (company team page, JSON-LD `sameAs`, GitHub profile `blog`); otherwise Telegram shows name, role and company so the candidate can search.
- **No invented contacts.** A contact needs a name *and* a stated role found on a public page. Emails are stored only from a `mailto:` link on an official company-domain page next to that person; no `firstname.lastname@` guessing exists. Nothing verifiable → nothing stored.
- **Polite fetching** (`fetching.py`): robots.txt checked for every request and redirect hop (404 = allow, 5xx/unreachable/redirected robots = do not crawl, `Crawl-delay` honoured up to 10 s), at least 1.5 s between requests to a host, at most 8 pages and 7 GitHub API calls per company, 3 MB per page, public hosts only (SSRF guard shared with career-page discovery), no cookies/JS.
- **No claims beyond the base CV.** Prompts require CV-only facts and forbid placeholders/years of experience; code then rejects any text that mentions a technology or a number found in none of the inputs (CV, company facts, person facts, pasted post), retrying with the reasons (max 3 attempts, then it fails and stores nothing). This check is deliberately limited to technologies/numbers; the human review of each draft remains the real gate.
- `priority`/fit is **review priority, not probability**; hints are labelled hints; UNKNOWN scores 0.

## 1. Ranking (`outreach companies`)

Candidates: companies linked from a `CompanyLead` or having a non-`REJECTED` monitored source. Score (0–100), each factor with reason and provenance:

| Factor | Max | Evidence |
| --- | --- | --- |
| sector (fintech, AI, banking, developer tools) | 20 | company description / evidence `sector`; curated-list note = hint, 10 |
| product company | 10 | `company_type` evidence; list note is a hint (5); consultancy/agency = 0 |
| Spain presence | 20 | remote-from-Spain evidence or `SPAIN_ONLY` posting or Madrid posting = 20; other Spain 15; EU/EMEA/worldwide remote 10; lead location hint 8 (hint) |
| stack | 30 | stored postings (open or closed): Java/Spring/Kotlin 22 (+4 per extra posting, max 30); only Python/Go 10 (+3, max 16) |
| size/stage | 20 (can be negative) | favours startups/scale-ups for cold outreach, see below |

**Size/stage** (`ranking.estimate_size`, every step keeps its provenance in the explanation). Basis, strongest first: *evidence* (`employee_count` / `size_bucket` / `stage` in company evidence), *curated-list hint* (notes such as "startup", "Series B", "11-50 employees"), *job-count proxy* (largest `last_job_count` of the company's monitored boards, or stored postings: 300+ postings = large and overrides a startup hint, 100–299 = mid/large, fewer = only "not huge"). Points: evidence ≤200 employees 20, 201–500 14, 501–1000 8, 1001–5000 −4, >5000 −10, <10 employees 14; a hint earns half; the proxy earns +6 (small board), 0 (100–299) or −6 (300+); unknown 0. Only *evidence* of ≤50 employees (or a startup/seed bucket) makes a company "known small"; hints and proxies never do.

Stage (draft variants, from evidence only): `EARLY_STAGE` (<30 employees or bucket startup/seed), `MID_SIZE` (≥30), else `UNKNOWN` (treated with the shorter early-stage rules, size never stated). Excluded: any non-DRAFT application (already applied), dismissal with reason `company`/`not_interesting`, every known job dismissed, a `DECLINED` outreach. Leads not yet linked to a company are only counted (resolve them first). Weights are constants at the top of `ranking.py`.

## 2. Contacts (`outreach find-contacts <company>|--top N`, `outreach prune-contacts`)

Reads the company website's home page, up to 3 team/about pages, one blog index and 2 posts, and the first GitHub org linked from the company's own site (`public_members` + `users/{login}`, ≤6 members; only profiles whose bio states a role).

**What counts as a person** (`people.py`, regression-tested on real excerpts of databricks.com and raisin.com/es-es/acerca-raisin/ in `tests/fixtures/company_hunter/`):

1. Structured data first: JSON-LD `Person` (also `employee`/`member`/`founder` of an Organization and article authors) and schema.org microdata `Person`, each with a `jobTitle`.
2. Otherwise a *card*: the smallest element holding exactly one person-looking name (2–4 capitalised words, no digits, no product/navigation/marketing words such as Platform, Cloud, Data, Intelligence, Academy…, not an acronym, not identical to a menu/link text) next to a recognised role in its own text blocks (≤6 text blocks, ≤2 role-like). A wrapper holding several people is skipped, never guessed.
3. Cards are read **only on team/about-style URLs** (team, equipo, about, acerca, leadership, people, management…), never on a home page, and never inside `nav`/`footer`/`aside`/`menu`/`dialog`, `role=navigation|banner|contentinfo|menu`, class/id containing nav/menu/footer/dropdown/breadcrumb/cookie/sitemap, or a page-level `<header>`. LinkedIn URLs and `mailto:` addresses are taken only from inside the person's own card (email only on the company's domain; a LinkedIn link needs a LinkedIn label or a slug naming the person).
4. A role that names another company ("CEO at X", "CFO, X", "CTO X"; typical of customer testimonials) is rejected unless the tail is our company, a role or department words. After a comma or dash (never "at"/"@"), a tail of up to 4 words following a non-C-level engineering title is read as the team or product ("Director of Engineering, Mail", "Staff Engineer - VPN"); executive titles keep the strict rule.

**Who is worth storing** (`relevance.py`), for a junior backend candidate. Scores: CTO/VP Engineering 100 at companies known small (≤50 employees by evidence) and **not a target otherwise**; Head/Director of Engineering 90; Engineering Manager 85; Tech Lead 80; **Staff/Principal/Senior Engineer: not a target** (they do not hire and rarely answer a junior); Engineer 60; Talent/Tech Recruiter 55; **non-engineering C-level** (CEO, CFO, COO, CRO, CMO, founders, president, managing director, general manager) 20 and **stored/suggested only when the company is known small by evidence**. Sales/support/marketing/solutions/QA engineers and other functions are not targets. At most 12 people are stored per company (most relevant first); `find-contacts` prints each person stored and each one skipped with the reason and the size basis. `prune-contacts` re-checks contacts already stored by Company Hunter with these rules (dry run by default, `--apply` deletes the invalid ones that no outreach or connection request references; manual contacts are never touched).

Stored in the existing `contacts` table: name, title, `contact_type`, source URL, `source_provider` (`company_site`/`github_org`), `external_id` (page URL + name, idempotent) and `evidence` (`quote`, `evidence_type`, `observed_at`, `language`, optional `topic`/`topic_url`).

## 3. Drafts (`outreach company-draft <company>`)

One Claude call (same request style as `services/cover_letters.py`: model, cached system prompt, fallback beta, safe error text) writes both variants as JSON: email (subject + body) and LinkedIn DM. Inputs: base CV `private/cv/CV_base_<LANG>.md` (the other language's CV is used if missing; **no CV → error before any model call**), style guide `private/WRITING.md` (optional), company facts (hints labelled), best contact for the stage. Rules from the cold-outreach guide are in the prompt and checked in code: early-stage/unknown email ≤110 words, one overlap, ≤3 bullets; mid-size email ≤170 words, 3 pointers about the candidate + 1 about the company; DM single line ≤300 chars. Stored as two `Outreach` rows (`COLD_OUTREACH`, `EMAIL` and `LINKEDIN`, status `DRAFT`, rationale = overlap + fit + provenance). Existing active drafts are returned without a model call; `--force` cancels `DRAFT/APPROVED` ones and regenerates (a `SENT` one blocks it). Migration 0013 made the company-level uniqueness per channel so both variants coexist.

## 4. Telegram weekly message (`outreach weekly [--find-contacts] [--send]`)

"🏹 Company Hunter": top 5 with score, stage, why (reasons), unknowns and contact found/not, plus buttons "✍️ 1…5" (`ch:<company id>`). The `bot` command answers a tap by generating (or re-sending) the drafts as a **reply to that message**. CLI equivalent: `company-draft`. Without `--send` the message is only printed.

## 5. Manual LinkedIn connection queue

Daily (weekdays, scheduled after 09:00 Madrid by `deploy/linux/run-scheduled.sh`; Mondays also run `find-contacts --top 15` and `weekly --send`): `outreach connections [--count 1-5] [--send]`.

- People come only from stored verified contacts of ranked companies (top 30), ordered by the relevance above: engineering heads/managers, tech leads, engineers, tech recruiters. Non-engineering C-level people (CEO, CFO, COO, founders…) are **never** suggested unless the company is known by evidence to have ≤50 employees; the check uses the title at suggestion time, so contacts stored earlier are also covered.
- Hard rules: at most 5 per day (Madrid date, enforced across runs), at most 1 per company per day, a company stops being suggested once 2 of its people are `SENT`/`ACCEPTED`, a contact is not re-suggested while an unanswered suggestion is <14 days old, after being sent, or for 60 days after "Saltar". Re-running the same day is idempotent (no second model call, no second Telegram message).
- Each person is its **own Telegram message** (so a reply identifies them) after a header, with name, role, company, public source link, LinkedIn URL only when stored (else a "search for…" line), and a ready-to-paste note in `<code>`. Notes: ≤300 characters (enforced in code after generation with retries, and by the DB check `ck_connection_requests_note_length`), in the person's language (stored evidence language, else detected from their quote/topic, else English), casual and specific (company/product, team tech, or their public article/talk).
- Buttons: "✅ Enviada" (logs `sent_at`), "🤝 Aceptó" (logs `accepted_at`, replies with a casual one-line follow-up draft under the LinkedIn DM rules, stored once), "⏭️ Saltar" (`skip_until` = +60 days). Replying to a person's message with the text of one of their LinkedIn posts regenerates that note grounded in the post (only while still suggested; the pasted post is stored). The bot now also receives `message` updates and ignores anything that is not a text reply to one of these messages in the configured chat.
- CLI: `outreach connection sent|accepted|skip|post|followup|show <request-id>` records state by hand (`post` takes `--text`/`--file`).
- Persistence: table `connection_requests` (person via `contact_id`, company, note, language, status, `suggested_at`/`sent_at`/`accepted_at`/`skipped_at`/`skip_until`, `telegram_message_id`, `grounding_post`, `follow_up_draft`); survives restarts (tested with a file database). A Telegram delivery whose outcome is ambiguous is marked `unknown` and never retried, to avoid duplicate messages.

## Operating notes

- `pip install -e ".[dev,jev,llm]"` needs Python 3.13 (the project's `requires-python`).
- Everything needs `ANTHROPIC_API_KEY` for writing and the Telegram settings for `--send`; none is needed for `companies`, `find-contacts`, `connection …` or the tests.
- The Windows `scripts/run-scheduled.ps1` was not changed; only the Linux timer/script schedules Company Hunter.
