from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx

from ai_job_hunter.decision_engine import FinalDecision
from ai_job_hunter.models import Company, Job, JobSource
from ai_job_hunter.services.direct_postings import (
    DirectPostingResolver,
    company_slugs,
    paywalled_portal,
    same_title,
)
from ai_job_hunter.services.notifications import _paywalled_copy_suppression, _job_identity, format_notification_message
from tests.test_notifications import _opportunity

WWR_URL = "https://weworkremotely.com/remote-jobs/acme-backend-engineer"
NOW = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


def test_paywalled_portals_titles_and_slugs():
    assert paywalled_portal(WWR_URL) == "We Work Remotely"
    assert paywalled_portal("https://remoteok.com/remote-jobs/1") == "Remote OK"
    assert paywalled_portal("https://job-boards.greenhouse.io/acme/jobs/1") is None
    assert paywalled_portal(None) is None
    assert same_title("Backend Engineer (Python) - Remote", "Backend Engineer, Python")
    assert not same_title("Senior Backend Engineer", "Backend Engineer")
    assert not same_title("Backend Engineer", "Frontend Engineer")
    assert company_slugs("The Browser Company Inc.") == ["thebrowsercompany", "the-browser-company"]
    assert company_slugs("Acme") == ["acme"]


def _client(routes, requests):
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        for prefix, payload in routes.items():
            if str(request.url).startswith(prefix):
                return httpx.Response(200, json=payload)
        return httpx.Response(404, json={})

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_resolver_finds_the_posting_on_the_company_ats_and_caches_it(db_session, tmp_path):
    requests: list[str] = []
    client = _client(
        {"https://api.ashbyhq.com/posting-api/job-board/acme": {"jobs": [
            {"title": "Frontend Engineer", "jobUrl": "https://jobs.ashbyhq.com/acme/1"},
            {"title": "Backend Engineer (Python)", "jobUrl": "https://jobs.ashbyhq.com/acme/2"},
        ]}},
        requests,
    )
    state = tmp_path / "direct.json"
    resolver = DirectPostingResolver(db_session, state_path=state, client=client, now=lambda: NOW)
    job_id = uuid4()

    found = resolver(job_id, "Acme Inc.", "Backend Engineer, Python")

    assert found.url == "https://jobs.ashbyhq.com/acme/2" and found.source == "ashby:acme"
    assert requests == [
        "https://boards-api.greenhouse.io/v1/boards/acme/jobs",
        "https://api.ashbyhq.com/posting-api/job-board/acme",
    ]
    # Cached on disk: a new resolver makes no request, even offline.
    again = DirectPostingResolver(db_session, state_path=state, client=client, online=False)
    assert again(job_id, "Acme Inc.", "Backend Engineer, Python").url == found.url
    assert len(requests) == 2


def test_resolver_remembers_misses_for_a_day_and_offline_mode_never_requests(db_session, tmp_path):
    requests: list[str] = []
    client = _client({}, requests)
    clock = [NOW]
    state = tmp_path / "direct.json"
    job_id = uuid4()

    offline = DirectPostingResolver(db_session, state_path=state, client=client, online=False)
    assert offline(job_id, "Acme", "Backend Engineer") is None
    assert requests == []

    resolver = DirectPostingResolver(db_session, state_path=state, client=client, now=lambda: clock[0])
    assert resolver(job_id, "Acme", "Backend Engineer").url is None
    first = len(requests)
    assert first == 4  # one slug x Greenhouse, Ashby, Workable, SmartRecruiters
    clock[0] = NOW + timedelta(hours=2)
    assert resolver(job_id, "Acme", "Backend Engineer").url is None
    assert len(requests) == first
    clock[0] = NOW + timedelta(hours=25)
    resolver(job_id, "Acme", "Backend Engineer")
    assert len(requests) == 2 * first


def test_resolver_prefers_a_free_copy_already_in_the_database(db_session, tmp_path):
    company = Company(name="Acme GmbH")
    db_session.add(company)
    db_session.flush()
    board_job = Job(company=company, title="Backend Engineer")
    db_session.add(board_job)
    db_session.flush()
    db_session.add(JobSource(job=board_job, provider="greenhouse", external_id="1",
                             original_url="https://job-boards.greenhouse.io/acme/jobs/1"))
    db_session.flush()
    requests: list[str] = []
    resolver = DirectPostingResolver(
        db_session, state_path=tmp_path / "d.json", client=_client({}, requests), now=lambda: NOW
    )

    found = resolver(uuid4(), "Acme", "Backend Engineer")

    assert found.url == "https://job-boards.greenhouse.io/acme/jobs/1" and found.source == "database"
    assert requests == []


def test_alert_links_the_employer_posting_or_a_search_for_paywalled_jobs():
    item = replace(_opportunity(uuid4(), FinalDecision.APPLY, 90, company="Acme"), url=WWR_URL)

    direct = format_notification_message(item, direct_url="https://jobs.ashbyhq.com/acme/2")
    assert 'href="https://jobs.ashbyhq.com/acme/2">Ver oferta en la web de la empresa' in direct
    assert "We Work Remotely, que cobra por aplicar" in direct

    fallback = format_notification_message(item)
    assert f'href="{WWR_URL}">Ver oferta' in fallback
    assert "🔒 We Work Remotely cobra por aplicar" in fallback and "duckduckgo.com" in fallback

    free = replace(item, url="https://job-boards.greenhouse.io/acme/jobs/1")
    assert "cobra por aplicar" not in format_notification_message(free, direct_url="https://x.test/ignored")


def test_paywalled_copy_is_suppressed_when_a_free_copy_exists():
    paid = replace(_opportunity(uuid4(), FinalDecision.APPLY, 90, company="Acme"), url=WWR_URL)
    free = replace(_opportunity(uuid4(), FinalDecision.APPLY, 90, company="Acme"),
                   url="https://job-boards.greenhouse.io/acme/jobs/1")

    assert _paywalled_copy_suppression(paid, {_job_identity(free)}) == "paywalled_copy_of_free_posting"
    assert _paywalled_copy_suppression(paid, set()) is None
    assert _paywalled_copy_suppression(free, {_job_identity(free)}) is None
