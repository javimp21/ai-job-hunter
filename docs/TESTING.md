# Testing

## After changes

Run the smallest relevant test set first.

Run the full suite when changes affect shared/core behavior.

Always run:

`git diff --check`

when code changes are complete.

Use additional quality gates already configured by the repository.

## Existing automated gate

Use the Python 3.13 virtual environment and dependencies documented in
[README](../README.md#local-setup). The existing GitHub Actions workflow
[Offline tests](../.github/workflows/tests.yml) runs:

```powershell
python -m pytest
```

For a focused check, pass the relevant test paths, for example:

```powershell
python -m pytest tests/test_notifications.py tests/test_notification_run_cli.py
```

The offline suite uses synthetic fixtures and does not require PostgreSQL,
a live API key, or a real browser session. This does not verify a live
Telegram delivery, ATS interaction, or PostgreSQL deployment.

Company Hunter tests (`tests/test_company_hunter_*.py`, shared fakes in `tests/company_hunter_support.py`) are fully offline: pages and the GitHub API are served by `httpx.MockTransport`, the model is a scripted fake client, Telegram is a fake provider/bot, and databases are in-memory or temporary SQLite files (including the `0013` upgrade/downgrade).

## Network boundaries

Offline tests must not unexpectedly perform:

- live job fetches;
- live Jev calls;
- real Telegram messages;
- applications;
- other external actions.

## Reporting

Always report:

- commands executed;
- exact test count;
- failures;
- warnings;
- checks not executed;
- reason they were not executed.

Never invent test results.

A reviewer agent does not replace real test execution.
