import json
from datetime import UTC, date, datetime

import httpx
import pytest
from pydantic import SecretStr

from ai_job_hunter.connectors.theirstack import (
    CreditBudget,
    TheirStackConnector,
    TheirStackConnectorError,
    TheirStackNotConfigured,
    build_search_body,
)
from ai_job_hunter.domain.normalized_job import EmploymentType, RemoteEligibility, RemotePolicy
from ai_job_hunter.services import job_portals
from ai_job_hunter.services.job_portals import PORTALS, fetch_portals

KEY = "ts-secret-key-123"


def raw_job(job_id=1, **changes):
    job = {
        "id": job_id,
        "job_title": "Backend Engineer",
        "url": f"https://www.linkedin.com/jobs/view/{job_id}",
        "final_url": f"https://job-boards.greenhouse.io/acme/jobs/{job_id}",
        "company": "Acme",
        "location": "Madrid, Spain",
        "country_code": "ES",
        "date_posted": "2026-10-05",
        "description": "<p>Build Java and Spring Boot services.</p>",
        "seniority": "junior",
        "remote": False,
        "employment_statuses": ["full_time"],
        "technology_slugs": ["java", "spring-boot"],
        "min_annual_salary_usd": 70000,
    }
    job.update(changes)
    return job


def make(handler, tmp_path, daily=100, **kwargs):
    requests: list[httpx.Request] = []

    def wrapped(request):
        requests.append(request)
        return handler(request)

    client = httpx.Client(transport=httpx.MockTransport(wrapped))
    budget = CreditBudget(tmp_path / "credits.json", daily, today=lambda: date(2026, 10, 5))
    return TheirStackConnector(api_key=SecretStr(KEY), budget=budget, client=client, **kwargs), requests, budget


def test_search_body_is_narrow_and_preview_costs_nothing():
    body = build_search_body(limit=25)
    assert body["job_country_code_or"] == ["ES", "NL", "CH", "IE", "LU"]
    assert body["posted_at_max_age_days"] == 1 and body["limit"] == 25
    assert body["job_seniority_or"] == ["junior", "mid_level"]
    assert "blur_company_data" not in body
    preview = build_search_body(limit=1, preview=True, include_total=True)
    assert preview["blur_company_data"] is True and preview["include_total_results"] is True


def test_jobs_link_to_the_employer_and_keep_only_stated_facts(tmp_path):
    connector, requests, _ = make(
        lambda request: httpx.Response(200, json={"data": [raw_job(1), raw_job(2, final_url=None, remote=True), "junk"]}),
        tmp_path,
    )
    jobs = {job.external_id: job for job in connector.fetch_jobs()}

    request = requests[0]
    assert request.method == "POST" and request.headers["authorization"] == f"Bearer {KEY}"
    assert json.loads(request.content)["limit"] == 50
    first = jobs["theirstack:1"]
    assert first.apply_url == first.canonical_url == "https://job-boards.greenhouse.io/acme/jobs/1"
    assert first.source_url == "https://www.linkedin.com/jobs/view/1"
    assert first.company_name == "Acme" and first.location == "Madrid, Spain"
    assert first.employment_type is EmploymentType.FULL_TIME
    assert first.remote_policy is None and first.remote_eligibility is RemoteEligibility.UNKNOWN
    assert first.salary_min is None and first.salary_max is None  # an estimate is not a published salary
    assert first.published_at == datetime(2026, 10, 5, tzinfo=UTC)
    assert "Build Java and Spring Boot services." in first.description and "<p>" not in first.description
    second = jobs["theirstack:2"]
    assert second.apply_url == "https://www.linkedin.com/jobs/view/2" and second.remote_policy is RemotePolicy.REMOTE
    assert KEY not in repr(first.raw_metadata)


def test_the_daily_credit_budget_caps_requests_across_runs(tmp_path):
    connector, requests, budget = make(
        lambda request: httpx.Response(200, json={"data": [raw_job(n) for n in range(json.loads(request.content)["limit"])]}),
        tmp_path,
        daily=60,
    )

    assert len(connector.fetch_jobs()) == 50 and budget.used() == 50
    assert len(connector.fetch_jobs()) == 10 and budget.used() == 60  # only what is left
    assert json.loads(requests[1].content)["limit"] == 10
    assert connector.fetch_jobs() == [] and len(requests) == 2  # spent: no request at all
    # A new day starts a new budget.
    tomorrow = CreditBudget(tmp_path / "credits.json", 60, today=lambda: date(2026, 10, 6))
    assert tomorrow.used() == 0 and tomorrow.remaining() == 60


def test_count_matches_uses_a_preview_request(tmp_path):
    connector, requests, budget = make(
        lambda request: httpx.Response(200, json={"metadata": {"total_results": 137}, "data": []}), tmp_path
    )

    assert connector.count_matches() == 137
    body = json.loads(requests[0].content)
    assert body["blur_company_data"] is True and body["limit"] == 1 and budget.used() == 0


def test_missing_key_is_skipped_without_requests(tmp_path):
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={})))
    for key in (None, "", SecretStr(" ")):
        with pytest.raises(TheirStackNotConfigured, match="THEIRSTACK_API_KEY"):
            TheirStackConnector(api_key=key, client=client).fetch_jobs()


def test_errors_never_include_the_key(tmp_path):
    connector, _, _ = make(lambda request: httpx.Response(401, text=f"bad key {KEY}"), tmp_path)
    with pytest.raises(TheirStackConnectorError, match="401") as caught:
        connector.fetch_jobs()
    assert KEY not in str(caught.value)

    def boom(request):
        raise httpx.ConnectError("failed " + str(request.headers))

    connector, _, _ = make(boom, tmp_path)
    with pytest.raises(TheirStackConnectorError) as caught:
        connector.fetch_jobs()
    assert KEY not in str(caught.value) and caught.value.__cause__ is None

    connector, _, _ = make(lambda request: httpx.Response(200, json={"unexpected": 1}), tmp_path)
    with pytest.raises(TheirStackConnectorError, match="unexpected payload"):
        connector.fetch_jobs()


def test_portal_is_registered_but_not_enabled_by_default(monkeypatch, tmp_path):
    from ai_job_hunter.config import Settings

    assert "theirstack" in PORTALS and PORTALS["theirstack"].min_interval.total_seconds() == 6 * 3600
    assert "theirstack" not in Settings().job_portals

    monkeypatch.setenv("THEIRSTACK_API_KEY", "")
    offers, failures = fetch_portals(["theirstack"], state_path=tmp_path / "state.json", record=False)
    assert offers == [] and [f.portal for f in failures] == ["theirstack"]
    assert job_portals.parse_portal_names("himalayas,theirstack") == ("himalayas", "theirstack")


def test_probe_counts_what_is_already_stored(db_session):
    from ai_job_hunter.models import Company, Job, JobSource
    from ai_job_hunter.theirstack_probe import known_identities, overlap
    from ai_job_hunter.connectors.theirstack import _normalize_job

    company = Company(name="Acme Inc.")
    db_session.add(company)
    db_session.flush()
    stored = Job(company=company, title="Backend Engineer")
    db_session.add(stored)
    db_session.flush()
    db_session.add(JobSource(job=stored, provider="greenhouse", external_id="1",
                             original_url="https://job-boards.greenhouse.io/acme/jobs/1"))
    db_session.flush()
    now = datetime(2026, 10, 5, tzinfo=UTC)
    jobs = [
        _normalize_job(raw_job(1), discovered_at=now),  # same employer URL
        _normalize_job(raw_job(2, final_url="https://x.example/jobs/2"), discovered_at=now),  # same company + title
        _normalize_job(raw_job(3, final_url="https://x.example/jobs/3", job_title="Data Engineer"), discovered_at=now),
        _normalize_job(raw_job(4, final_url=None, job_title="Java Developer"), discovered_at=now),
    ]

    counts = overlap(jobs, *known_identities(db_session))

    assert (counts["fetched"], counts["known_by_url"], counts["known_by_company_and_title"], counts["new"]) == (4, 1, 1, 2)
    assert counts["with_employer_link"] == 3
