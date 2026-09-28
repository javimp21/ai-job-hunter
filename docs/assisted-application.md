# Assisted application preparation

This workflow prepares a private, reviewable application package and can
inspect a hosted ATS form in assisted browser mode. It does not submit an
application, upload a file, change the opportunity decision, or update
Application tracking status.

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
Assisted browser inspection and safe factual fill
  ↓
Human review in the saved local session
  ↓
[STOP — no application submission operation]
```

## Local package

`ApplicationPackage` ties a job UUID to an optional existing Application UUID,
records a package version and fingerprints for the candidate profile and
preferences, and stores the job URLs, ATS, extracted requirements, fit map,
missing information, document recommendation, questions/answers, notes, and
readiness. The profile and preferences themselves are not copied into the
package. The package JSON is stored at
`data/local/application-packages.local.json`; `/data/` is ignored by Git.

The package lifecycle is `DRAFT`, `READY_FOR_REVIEW`, `READY_TO_SUBMIT`, and
`CANCELLED`. `SUBMITTED` is reserved vocabulary only; validation and the CLI do
not permit it. `READY_TO_SUBMIT` requires an explicit `apply ready` command and
a passing readiness result. That operation records review only.

Browser sessions are a separate local record in
`data/local/application-sessions.local.json`. Each session stores redacted form
metadata, field mappings, and IDs of fields filled; it never stores entered
field values, cookies, HTML, screenshots, traces, or browser storage. Session
statuses are `CREATED`, `INSPECTED`, `PARTIALLY_FILLED`, `NEEDS_INPUT`,
`READY_FOR_FINAL_REVIEW`, `BLOCKED`, and `CANCELLED`.
The default session file is local plaintext and Git-ignored. It can contain
review drafts derived from configured candidate facts or projects; protect it
like other local candidate data. A custom `--sessions-path` is stored wherever
that path points.

## Requirements and fit

Requirements are extracted from saved public posting text. Explicit minimum or
required language can classify a statement as `MUST_HAVE`; explicit nice-to-have
language is `PREFERRED`. Responsibilities and benefits stay separate. Generic
mentions remain `UNKNOWN`. Candidate evidence is limited to configured profile
facts, preferences explicitly marked as willingness to learn, and configured
projects. Missing evidence is not treated as proof that a skill is absent.

Question extraction reads structured form data already present in ATS metadata.
It does not infer form questions from job descriptions. A question with no
matching type is `UNKNOWN`. Legal and sensitive questions remain unanswered by
automatic drafting. Salary expectations can only be suggested from preference
thresholds and always require human review. Work authorization is never inferred
from location, eligible-country lists, or broad profile labels.

## Local candidate configuration

The following files are optional and ignored by the existing `*.local.json`
rule:

- `candidate_writing.local.json`: personal writing preferences. Copy
  `config/examples/candidate_writing.example.json` to start with fictional
  values; no personal style is checked in.
- `candidate_documents.local.json`: document IDs, types, local paths and
  matching metadata for CVs, cover letters, portfolios, or other documents.
  Copy `config/examples/candidate_documents.example.json` and add only real
  local documents. Keep document files under the ignored `private/` directory.
  The workflow reads metadata only; it does not read, modify, copy, or upload
  document contents.
- `candidate_application.local.json`: optional, explicit first/last name,
  email, phone and profile URLs. Copy
  `config/examples/candidate_application.example.json` and add only facts you
  want to use. Missing values remain blank; the profile loader never invents
  them.
- `candidate_projects.local.json`: existing local project metadata is reused.

CV recommendations need matching configured metadata. A cover letter is drafted
only when the posting explicitly requires one or `--cover-letter` is passed.
The draft is text for review; no real file is modified.

## CLI

```text
ai-job-hunter apply prepare JOB_ID
ai-job-hunter apply show JOB_ID
ai-job-hunter apply questions JOB_ID
ai-job-hunter apply answer JOB_ID QUESTION_ID
ai-job-hunter apply ready JOB_ID --confirm-reviewed
ai-job-hunter apply cancel JOB_ID
ai-job-hunter apply browser JOB_ID
ai-job-hunter apply fill-safe JOB_ID
ai-job-hunter apply inspect JOB_ID
ai-job-hunter apply pending JOB_ID
ai-job-hunter apply review JOB_ID
```

`apply answer` accepts `--value` or prompts locally. Legal and sensitive fields
also require `--confirm-sensitive`; the answer remains marked for human review.
File fields cannot be answered because document upload is not supported. The
legacy `ai-job-hunter apply JOB_ID` behavior is preserved for recording a
manually completed application.

## Browser-assisted inspection

Install the optional local browser tools with `pip install -e ".[browser]"`
and `python -m playwright install chromium`. Importing the project does not
import Playwright or start a browser. `apply browser` performs visible, local
inspection. `apply fill-safe` also fills exact, empty factual fields only when
an explicit configured value is available. It does not overwrite existing
values. Supported facts are first/last name, email, phone, city, country,
LinkedIn, GitHub, portfolio, current role, and overall years of experience.
Skill-specific experience, generic job title, and location fields remain for
review.

Salary preferences produce suggestions with currency and period and are never
inserted. Legal, work-authorization, sponsorship, demographic, health and
other sensitive questions remain pending. Free-text drafts use the existing
local drafting rules and require human review. A configured CV can be
recommended by metadata, but browser file fields are never populated.

The browser runs in a new, non-persistent context with downloads and service
workers disabled. Only HTTPS Greenhouse, Lever and Ashby hosts are accepted.
The first read-only GET page load is allowed. Once the automation touches a
field or attempts to advance, all network requests are blocked. A submit-event
handler blocks native form submission and Enter; `form.submit()` and
`requestSubmit()` are disabled. The browser layer exposes only inspection,
factual fill, and a gated exact `Next`/`Continue` action. It advances only for
an explicit non-submit button when all current required fields are resolved
and no submission control is visible. No generic click, keyboard, JavaScript,
submit, login, CAPTCHA, or file-upload operation is exposed.

The current adapters identify supported ATS domains and use generic visible
DOM extraction; there are no special ATS selectors. Authentication, MFA,
CAPTCHA, unsupported redirects, unknown fields, and uncertain next steps stop
for manual intervention.

Playwright's Python library supports creating isolated, non-persistent browser
contexts that do not share cookies or cache. This project uses that context
boundary and adds request and form-event guards for the assisted flow. See the
official [Playwright Python browser API](https://playwright.dev/python/docs/api/class-browser),
[BrowserContext API](https://playwright.dev/python/docs/api/class-browsercontext),
[network routing](https://playwright.dev/python/docs/network), and
[Service Worker controls](https://playwright.dev/python/docs/service-workers).

## ATS capabilities

| ATS | Public posting data | Application form questions/schema | Submission and authentication | Candidate-facing use |
|---|---|---|---|---|
| Greenhouse | Unauthenticated Job Board GET for published postings | `questions=true` can return custom, location, compliance, and demographic questions. | A separate POST requires an employer Job Board API key; its documentation describes the key as a secret. | Public questions can inform preparation when available; otherwise use the hosted form. Direct submission is not available to an unaffiliated candidate. |
| Lever | Public Postings API exposes published postings and `applyUrl`. | The official documentation says custom questions are not exposed by the Postings API. | The application POST needs an API key generated by that Lever account's Super Admin. | Use the hosted `applyUrl` and review its form manually. |
| Ashby | Unauthenticated public job-board GET exposes postings and `applyUrl`. | The public endpoint has no form schema. A separate employer custom-careers flow returns `applicationFormDefinition`. | Form-schema access requires employer API credentials; `applicationForm.submit` requires `candidatesWrite`. | Public listing and link-out are appropriate; form schema and submission are employer-authorized. |

Official documentation: [Greenhouse Job Board API](https://docs.greenhouse.io/job-board.html),
[Lever Postings API](https://github.com/lever/postings-api),
[Ashby Public Job Posting API](https://developers.ashbyhq.com/docs/public-job-posting-api),
[Ashby custom careers page](https://developers.ashbyhq.com/docs/creating-a-custom-careers-page),
[Ashby application form submit permissions](https://developers.ashbyhq.com/reference/applicationformsubmit),
[Ashby authentication](https://developers.ashbyhq.com/reference/authentication).

ATS adapters currently provide host recognition only. Public job-board API
capabilities above remain unchanged; browser inspection operates on the
hosted application URL already saved in the package and adds no ATS API fetch
or submission code.
