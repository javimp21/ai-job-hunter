from datetime import UTC, date, datetime

import httpx
import pytest
from pydantic import SecretStr

from ai_job_hunter.connectors.fantastic_jobs import (
    CreditBudget,
    FantasticJobsConnector,
    FantasticJobsConnectorError,
    FantasticJobsNotConfigured,
    build_query,
)
from ai_job_hunter.domain.normalized_job import RemoteEligibility
from ai_job_hunter.services import job_portals
from ai_job_hunter.services.job_portals import PORTALS

KEY = "fj-secret-key-123"


def raw_job(job_id=1, **changes):
    job = {
        "id": job_id,
        "source": "linkedin",
        "title": "Backend Engineer",
        "organization": "Acme",
        "url": f"https://es.linkedin.com/jobs/view/backend-engineer-{job_id}",
        "date_posted": "2026-10-06T18:13:39.317",
        "locations_derived": ["Madrid, Community of Madrid, Spain"],
        "countries_derived": ["Spain"],
        "description_text": "Build Java and Spring Boot services.",
        "ai_work_arrangement": "Remote OK",
        "ai_experience_level": "2-5",
        "ai_employment_type": ["FULL_TIME"],
        "ai_salary_min_value": 40000,
    }
    job.update(changes)
    return job


def make(handler, tmp_path, daily=70, **kwargs):
    requests: list[httpx.Request] = []

    def wrapped(request):
        requests.append(request)
        return handler(request)

    client = httpx.Client(transport=httpx.MockTransport(wrapped))
    budget = CreditBudget(tmp_path / "credits.json", daily, today=lambda: date(2026, 10, 6))
    return FantasticJobsConnector(api_key=SecretStr(KEY), budget=budget, client=client, **kwargs), requests, budget


def test_the_query_uses_or_lists_for_titles_and_countries_and_excludes_senior_words():
    query = build_query(titles=("backend engineer", "java developer"), countries=("Spain", "Ireland"), limit=50)

    assert query["title"].startswith('"backend engineer" OR "java developer" -senior')
    assert query["location"] == '"Spain" OR "Ireland"'
    assert query["time_frame"] == "24h" and query["limit"] == 50 and query["description_format"] == "text"


def test_jobs_keep_only_stated_facts_and_the_vendors_guesses_stay_as_metadata(tmp_path):
    headers = {"x-api-jobs-remaining": "400", "x-api-requests-remaining": "49"}
    connector, requests, budget = make(
        lambda request: httpx.Response(
            200, json=[raw_job(1), raw_job(2, url="http://insecure.test/x"), "junk"], headers=headers
        ),
        tmp_path,
    )

    (job,) = connector.fetch_jobs()

    request = requests[0]
    assert request.headers["authorization"] == f"Bearer {KEY}" and request.url.path == "/v1/active-jb"
    assert job.external_id == "fantastic:1" and job.company_name == "Acme"
    assert job.location == "Madrid, Community of Madrid, Spain"
    assert job.description == "Build Java and Spring Boot services."
    assert job.published_at == datetime(2026, 10, 6, 18, 13, 39, 317000, tzinfo=UTC)
    assert job.remote_policy is None and job.remote_eligibility is RemoteEligibility.UNKNOWN  # "Remote OK" is a guess
    assert job.salary_min is None  # the vendor's salary guess is not stored as a fact
    assert job.raw_metadata["aiExperienceLevel"] == "2-5" and KEY not in repr(job.raw_metadata)
    assert budget.used() == 3 and connector.last_headers["x-api-jobs-remaining"] == "400"  # every returned job costs one


def test_the_daily_budget_caps_the_page_and_a_spent_budget_makes_no_request(tmp_path):
    connector, requests, budget = make(
        lambda request: httpx.Response(200, json=[raw_job(n) for n in range(int(request.url.params["limit"]))]),
        tmp_path,
        daily=30,
    )

    assert len(connector.fetch_jobs()) == 30 and budget.used() == 30
    assert requests[0].url.params["limit"] == "30"
    assert connector.fetch_jobs() == [] and len(requests) == 1  # spent: no request at all


def test_an_empty_account_stops_further_requests_today(tmp_path):
    connector, _requests, budget = make(
        lambda request: httpx.Response(200, json=[raw_job(1)], headers={"x-api-jobs-remaining": "0"}), tmp_path
    )

    connector.fetch_jobs()

    assert budget.remaining() == 0


def test_missing_key_and_errors_never_expose_the_key(tmp_path):
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=[])))
    for key in (None, "", SecretStr(" ")):
        with pytest.raises(FantasticJobsNotConfigured, match="FANTASTIC_JOBS_API_KEY"):
            FantasticJobsConnector(api_key=key, client=client).fetch_jobs()

    connector, _, _ = make(lambda request: httpx.Response(401, text=f"bad key {KEY}"), tmp_path)
    with pytest.raises(FantasticJobsConnectorError, match="401") as caught:
        connector.fetch_jobs()
    assert KEY not in str(caught.value)

    def boom(request):
        raise httpx.ConnectError("failed " + str(request.headers))

    connector, _, _ = make(boom, tmp_path)
    with pytest.raises(FantasticJobsConnectorError) as caught:
        connector.fetch_jobs()
    assert KEY not in str(caught.value) and caught.value.__cause__ is None


def test_portal_is_registered_but_not_enabled_by_default(monkeypatch, tmp_path):
    from ai_job_hunter.config import Settings

    assert "fantastic_jobs" in PORTALS and PORTALS["fantastic_jobs"].min_interval.total_seconds() == 4 * 3600
    assert "fantastic_jobs" not in Settings().job_portals

    monkeypatch.setenv("FANTASTIC_JOBS_API_KEY", "")
    offers, failures = job_portals.fetch_portals(["fantastic_jobs"], state_path=tmp_path / "state.json", record=False)
    assert offers == [] and [f.portal for f in failures] == ["fantastic_jobs"]
