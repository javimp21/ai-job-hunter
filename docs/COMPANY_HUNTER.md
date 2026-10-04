# Company Hunter

Surfaces companies that fit the candidate **even when they have no matching open role**, finds verifiable public contacts, prepares (never sends) short outreach drafts, and runs a manual LinkedIn connection queue. It extends the existing outreach subsystem (`Contact`, `Outreach`, `OutreachEvent`, `outreach` CLI) and Company Intelligence (company leads, monitored sources); it does not replace them.

Code: `src/ai_job_hunter/company_hunter/` (`ranking`, `fetching`, `people`, `contacts`, `writing`, `service`, `queue`, `notify`, `bot`, `cli`). Migration: `0013_company_hunter`.

## Safety guarantees

- **Nothing is ever sent to a company or to LinkedIn.** Drafts are `Outreach` rows in `DRAFT`; the only transmissions are Telegram messages to the candidate's *own* chat (`weekly --send`, `connections --send`, bot replies), and they require `--send` or the running bot. No `send`/`connect` command exists (tested).
- **LinkedIn is never fetched, scraped or logged into.** `PoliteFetcher` refuses every `linkedin.com` host. A LinkedIn profile URL is stored/shown only if it is linked from a public non-LinkedIn page we already fetched (company team page, JSON-LD `sameAs`, GitHub profile `blog`); otherwise Telegram shows name, role and company so the candidate can search.
- **No invented contacts.** A contact needs a name *and* a stated role found on a public page. Emails are stored only from a `mailto:` link on an official company-domain page next to that person; no `firstname.lastname@` guessing exists. Nothing verifiable → nothing stored.
- **Polite fetching** (`fetching.py`): robots.txt checked for every request and redirect hop (404 = allow, 5xx/unreachable/redirected robots = do not crawl, `Crawl-delay` honoured up to 10 s), at least 1.5 s between requests to a host, at most 8 pages and 7 GitHub API calls per company, 1.5 MB per page, public hosts only (SSRF guard shared with career-page discovery), no cookies/JS.
- **No claims beyond the base CV.** Prompts require CV-only facts and forbid placeholders/years of experience; code then rejects any text that mentions a technology or a number found in none of the inputs (CV, company facts, person facts, pasted post), retrying with the reasons (max 3 attempts, then it fails and stores nothing). This check is deliberately limited to technologies/numbers; the human review of each draft remains the real gate.
- `priority`/fit is **review priority, not probability**; hints are labelled hints; UNKNOWN scores 0.

## 1. Ranking (`outreach companies`)

Candidates: companies linked from a `CompanyLead` or having a non-`REJECTED` monitored source. Score (0–100), each factor with reason and provenance:

| Factor | Max | Evidence |
| --- | --- | --- |
| sector (fintech, AI, banking, developer tools) | 25 | company description / evidence `sector`; curated-list note = hint, 12 |
| product company | 10 | `company_type` evidence; list note is a hint (5); consultancy/agency = 0 |
| Spain presence | 20 | remote-from-Spain evidence or `SPAIN_ONLY` posting or Madrid posting = 20; other Spain 15; EU/EMEA/worldwide remote 10; lead location hint 8 (hint) |
| stack | 35 | stored postings (open or closed): Java/Spring/Kotlin 25 (+5 per extra posting, max 35); only Python/Go 12 (+4, max 20) |
| size/stage | 10 | evidence `employee_count`/`size_bucket`: 20–1000 employees 10, other known sizes 5, >5000 0 |

Stage (draft variants): `EARLY_STAGE` (<30 employees or bucket startup/seed), `MID_SIZE` (≥30), else `UNKNOWN` (treated with the shorter early-stage rules, size never stated). Excluded: any non-DRAFT application (already applied), dismissal with reason `company`/`not_interesting`, every known job dismissed, a `DECLINED` outreach. Leads not yet linked to a company are only counted (resolve them first). Weights are constants at the top of `ranking.py`.

## 2. Contacts (`outreach find-contacts <company>|--top N`)

Reads the company website's home page, up to 3 team/about pages, one blog index and 2 posts (JSON-LD/`meta author` for authorship and topic), and the first GitHub org linked from the company's own site (`public_members` + `users/{login}`, ≤6 members; only profiles whose bio states a role). Stored in the existing `contacts` table: name, title, `contact_type`, source URL, `source_provider` (`company_site`/`github_org`), `external_id` (page URL + name, so re-runs are idempotent) and `evidence` (`quote`, `evidence_type`, `observed_at`, `language`, optional `topic`/`topic_url`). Roles map to ENGINEERING_MANAGER (incl. CTO/head of eng), ENGINEER (incl. tech lead), FOUNDER, TALENT/RECRUITER; other roles (marketing…) are ignored. `_sanitize_contact_metadata` gained the safe keys `quote`, `language`, `topic`, `topic_url`.

## 3. Drafts (`outreach company-draft <company>`)

One Claude call (same request style as `services/cover_letters.py`: model, cached system prompt, fallback beta, safe error text) writes both variants as JSON: email (subject + body) and LinkedIn DM. Inputs: base CV `private/cv/CV_base_<LANG>.md` (the other language's CV is used if missing; **no CV → error before any model call**), style guide `private/WRITING.md` (optional), company facts (hints labelled), best contact for the stage. Rules from the cold-outreach guide are in the prompt and checked in code: early-stage/unknown email ≤110 words, one overlap, ≤3 bullets; mid-size email ≤170 words, 3 pointers about the candidate + 1 about the company; DM single line ≤300 chars. Stored as two `Outreach` rows (`COLD_OUTREACH`, `EMAIL` and `LINKEDIN`, status `DRAFT`, rationale = overlap + fit + provenance). Existing active drafts are returned without a model call; `--force` cancels `DRAFT/APPROVED` ones and regenerates (a `SENT` one blocks it). Migration 0013 made the company-level uniqueness per channel so both variants coexist.

## 4. Telegram weekly message (`outreach weekly [--find-contacts] [--send]`)

"🏹 Company Hunter": top 5 with score, stage, why (reasons), unknowns and contact found/not, plus buttons "✍️ 1…5" (`ch:<company id>`). The `bot` command answers a tap by generating (or re-sending) the drafts as a **reply to that message**. CLI equivalent: `company-draft`. Without `--send` the message is only printed.

## 5. Manual LinkedIn connection queue

Daily (weekdays, scheduled after 09:00 Madrid by `deploy/linux/run-scheduled.sh`; Mondays also run `find-contacts --top 15` and `weekly --send`): `outreach connections [--count 1-5] [--send]`.

- People come only from stored verified contacts of ranked companies (top 30): engineering managers (0), tech leads (1), engineers (2). Founders/recruiters are never queued.
- Hard rules: at most 5 per day (Madrid date, enforced across runs), at most 2 per company per day, a company stops being suggested once 2 of its people are `SENT`/`ACCEPTED`, a contact is not re-suggested while an unanswered suggestion is <14 days old, after being sent, or for 60 days after "Saltar". Re-running the same day is idempotent (no second model call, no second Telegram message).
- Each person is its **own Telegram message** (so a reply identifies them) after a header, with name, role, company, public source link, LinkedIn URL only when stored (else a "search for…" line), and a ready-to-paste note in `<code>`. Notes: ≤300 characters (enforced in code after generation with retries, and by the DB check `ck_connection_requests_note_length`), in the person's language (stored evidence language, else detected from their quote/topic, else English), casual and specific (company/product, team tech, or their public article/talk).
- Buttons: "✅ Enviada" (logs `sent_at`), "🤝 Aceptó" (logs `accepted_at`, replies with a casual one-line follow-up draft under the LinkedIn DM rules, stored once), "⏭️ Saltar" (`skip_until` = +60 days). Replying to a person's message with the text of one of their LinkedIn posts regenerates that note grounded in the post (only while still suggested; the pasted post is stored). The bot now also receives `message` updates and ignores anything that is not a text reply to one of these messages in the configured chat.
- CLI: `outreach connection sent|accepted|skip|post|followup|show <request-id>` records state by hand (`post` takes `--text`/`--file`).
- Persistence: table `connection_requests` (person via `contact_id`, company, note, language, status, `suggested_at`/`sent_at`/`accepted_at`/`skipped_at`/`skip_until`, `telegram_message_id`, `grounding_post`, `follow_up_draft`); survives restarts (tested with a file database). A Telegram delivery whose outcome is ambiguous is marked `unknown` and never retried, to avoid duplicate messages.

## Operating notes

- `pip install -e ".[dev,jev,llm]"` needs Python 3.13 (the project's `requires-python`).
- Everything needs `ANTHROPIC_API_KEY` for writing and the Telegram settings for `--send`; none is needed for `companies`, `find-contacts`, `connection …` or the tests.
- The Windows `scripts/run-scheduled.ps1` was not changed; only the Linux timer/script schedules Company Hunter.
