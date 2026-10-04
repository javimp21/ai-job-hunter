# External Actions

External actions require explicit authorization.

Examples:

- job applications;
- Telegram messages;
- emails;
- LinkedIn messages;
- forms;
- document uploads;
- consent;
- sharing candidate data.

## Before execution

Show clearly:

- what will be sent;
- where;
- relevant recipient;
- important personal data included.

## Applications

Never auto-submit an application.

Preparing/drafting an application is different from submitting it.

## Outreach

Never invent contact details.

Do not perform aggressive LinkedIn scraping.

Company Hunter (`docs/COMPANY_HUNTER.md`) only prepares drafts and suggestions. It never sends anything to a company, never contacts LinkedIn (linkedin.com is refused by the fetcher) and never sends email. Its only transmissions are Telegram messages to the candidate's own chat, started explicitly (`outreach weekly --send`, `outreach connections --send`, the running bot, or the scheduled script). A LinkedIn connection is always made by the candidate by hand; the tool only records what the candidate reports (sent/accepted/skipped).

## Testing

Mocks/test environments must be preferred over real external actions.

Clearly report when a real action was performed.
