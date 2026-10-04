from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest
from pydantic import SecretStr

from ai_job_hunter.connectors.adzuna import AdzunaConnector, AdzunaConnectorError, AdzunaNotConfigured
from ai_job_hunter.connectors.jobicy import JobicyConnector, JobicyConnectorError
from ai_job_hunter.connectors.remoteok import RemoteOKConnector, RemoteOKConnectorError
from ai_job_hunter.domain.normalized_job import EmploymentType, RemoteEligibility, SalaryPeriod
from ai_job_hunter.services import job_portals
from ai_job_hunter.services.job_portals import PORTALS, fetch_portals, parse_portal_names
from ai_job_hunter.services.notifications import portal_credit


def client_for(handler):
    requests = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    return httpx.Client(transport=httpx.MockTransport(wrapped)), requests


def adzuna_job(job_id="1", **changes):
    job = {
        "id": job_id,
        "title": "Backend Engineer",
        "description": "Java and Spring &amp; more…",
        "created": "2026-10-01T08:00:00Z",
        "redirect_url": f"https://www.adzuna.es/land/ad/{job_id}?se=abc",
        "company": {"display_name": "Acme"},
        "location": {"display_name": "Madrid, Comunidad de Madrid", "area": ["Spain", "Madrid"]},
        "salary_min": 45000.0,
        "salary_max": 60000.0,
        "salary_is_predicted": "0",
        "contract_time": "full_time",
    }
    job.update(changes)
    return job


def adzuna(client, **kwargs):
    return AdzunaConnector(app_id="the-id", app_key=SecretStr("the-secret-key"), pause_seconds=0, client=client, **kwargs)


def test_adzuna_maps_fields_and_only_keeps_published_salary():
    client, requests = client_for(
        lambda request: httpx.Response(
            200,
            json={"results": [adzuna_job("1"), adzuna_job("2", salary_is_predicted="1"), adzuna_job("3", salary_min=None, salary_max=None), "junk"]},
        )
    )
    jobs = {job.external_id: job for job in adzuna(client, searches=(("java developer", "Madrid"),)).fetch_jobs()}

    params = requests[0].url.params
    assert requests[0].url.path == "/v1/api/jobs/es/search/1"
    assert (params["what"], params["where"], params["sort_by"], params["max_days_old"]) == ("java developer", "Madrid", "date", "7")
    first = jobs["1"]
    assert (first.salary_min, first.salary_max, first.currency, first.salary_period) == (
        Decimal("45000"), Decimal("60000"), "EUR", SalaryPeriod.YEAR,
    )
    assert first.employment_type is EmploymentType.FULL_TIME
    assert first.company_name == "Acme" and first.location.startswith("Madrid")
    assert first.remote_policy is None and first.remote_eligibility is RemoteEligibility.UNKNOWN
    assert first.published_at == datetime(2026, 10, 1, 8, tzinfo=UTC)
    assert jobs["2"].salary_min is None and jobs["2"].currency is None  # predicted, not published
    assert jobs["3"].salary_min is None
    assert "the-secret-key" not in repr(first.raw_metadata)


def test_adzuna_paginates_only_full_pages_and_dedupes_across_searches():
    full = [adzuna_job(str(index)) for index in range(50)]

    def handler(request):
        return httpx.Response(200, json={"results": full if request.url.path.endswith("/1") else [adzuna_job("0")]})

    client, requests = client_for(handler)
    jobs = adzuna(client, searches=(("a", "Madrid"), ("b", None))).fetch_jobs()

    assert len(jobs) == 50
    assert [r.url.path[-1] for r in requests] == ["1", "2", "1", "2"]
    assert "where" not in requests[2].url.params


def test_adzuna_without_credentials_is_skipped_without_requests():
    client, requests = client_for(lambda request: httpx.Response(200, json={}))
    for app_id, app_key in ((None, None), ("", "key"), (SecretStr(""), SecretStr(" "))):
        with pytest.raises(AdzunaNotConfigured, match="ADZUNA_APP_ID"):
            AdzunaConnector(app_id=app_id, app_key=app_key, client=client).fetch_jobs()
    assert requests == []


def test_adzuna_errors_never_include_credentials():
    client, _ = client_for(lambda request: httpx.Response(401, text="bad app_key=the-secret-key"))
    with pytest.raises(AdzunaConnectorError, match="401") as caught:
        adzuna(client, searches=(("a", None),)).fetch_jobs()
    assert "the-secret-key" not in str(caught.value) and "the-id" not in str(caught.value)

    def boom(request):
        raise httpx.ConnectError("failed for " + str(request.url))

    client, _ = client_for(boom)
    with pytest.raises(AdzunaConnectorError) as caught:
        adzuna(client, searches=(("a", None),)).fetch_jobs()
    assert "the-secret-key" not in str(caught.value) and caught.value.__cause__ is None


def test_adzuna_settings_are_secret_and_blank_by_default(monkeypatch):
    from ai_job_hunter.config import Settings

    monkeypatch.setenv("ADZUNA_APP_ID", "id-value")
    monkeypatch.setenv("ADZUNA_APP_KEY", "key-value")
    settings = Settings(_env_file=None)
    assert "key-value" not in repr(settings) and "id-value" not in repr(settings)
    monkeypatch.delenv("ADZUNA_APP_ID")
    monkeypatch.delenv("ADZUNA_APP_KEY")
    assert Settings(_env_file=None).adzuna_app_key is None


REMOTEOK_FEED = [
    {"last_updated": 1790927730, "legal": "https://remoteok.com/legal - please link back and mention Remote OK"},
    {
        "id": "100", "slug": "remote-backend-100", "date": "2026-10-01T10:00:00+00:00",
        "company": "Acme", "position": "Senior Backend Engineer", "location": "Worldwide",
        "description": "<p>Build <b>APIs</b></p>", "salary_min": 90000, "salary_max": 120000,
        "url": "https://remoteok.com/remote-jobs/remote-backend-100",
        "apply_url": "https://remoteok.com/l/100",
    },
    {"id": "101", "company": "Beta", "position": "Python Dev", "location": "United States", "salary_min": 0, "salary_max": 0,
     "url": "https://remoteok.com/remote-jobs/remote-python-101"},
    {"id": "102", "position": "Off host", "url": "https://evil.example/x"},
    {"id": "103", "position": "No location", "url": "https://remoteok.com/remote-jobs/remote-103"},
]


def test_remoteok_skips_legal_notice_links_back_and_maps_conservatively():
    client, requests = client_for(lambda request: httpx.Response(200, json=REMOTEOK_FEED))
    jobs = {job.external_id: job for job in RemoteOKConnector(client=client).fetch_jobs()}

    assert set(jobs) == {"100", "101", "103"}
    worldwide = jobs["100"]
    assert worldwide.remote_eligibility is RemoteEligibility.WORLDWIDE
    assert worldwide.apply_url == worldwide.source_url == "https://remoteok.com/remote-jobs/remote-backend-100"
    assert (worldwide.salary_min, worldwide.currency, worldwide.salary_period) == (Decimal("90000"), "USD", SalaryPeriod.YEAR)
    assert "Build" in worldwide.description and "<" not in worldwide.description
    assert jobs["101"].remote_eligibility is RemoteEligibility.UNKNOWN and jobs["101"].location == "United States"
    assert jobs["101"].salary_min is None and jobs["101"].currency is None
    assert jobs["103"].location is None
    assert all("apply_url" not in (job.raw_metadata or {}) for job in jobs.values())


def test_remoteok_unexpected_payload_and_status_are_safe_errors():
    client, _ = client_for(lambda request: httpx.Response(200, json={"jobs": []}))
    with pytest.raises(RemoteOKConnectorError, match="unexpected"):
        RemoteOKConnector(client=client).fetch_jobs()
    client, _ = client_for(lambda request: httpx.Response(429))
    with pytest.raises(RemoteOKConnectorError, match="429"):
        RemoteOKConnector(client=client).fetch_jobs()


def jobicy_job(job_id, geo, **changes):
    job = {
        "id": job_id, "url": f"https://jobicy.com/jobs/{job_id}-backend", "jobTitle": "Backend Engineer",
        "companyName": "Acme", "jobType": ["Full-Time"], "jobGeo": geo,
        "jobExcerpt": "short", "jobDescription": "<p>Java <i>services</i></p>", "pubDate": "2026-10-01 09:30:00",
        "annualSalaryMin": "50000", "annualSalaryMax": "70000", "salaryCurrency": "EUR",
    }
    job.update(changes)
    return job


def test_jobicy_requests_geo_and_maps_eligibility_only_from_explicit_values():
    payload = {"jobs": [
        jobicy_job(1, "Anywhere"), jobicy_job(2, "Spain"), jobicy_job(3, "Europe", annualSalaryMin=None, annualSalaryMax=None),
        jobicy_job(4, ["Germany", "Spain"]), jobicy_job(5, "", jobType="x", pubDate="2026-10-01T09:30:00Z"),
        {"id": 6, "jobTitle": "Bad", "url": "https://elsewhere.example/6"}, "junk",
    ]}
    client, requests = client_for(lambda request: httpx.Response(200, json=payload))
    jobs = {job.external_id: job for job in JobicyConnector(client=client).fetch_jobs()}

    assert dict(requests[0].url.params) == {"count": "50", "geo": "spain"}
    assert set(jobs) == {"1", "2", "3", "4", "5"}
    assert jobs["1"].remote_eligibility is RemoteEligibility.WORLDWIDE
    assert jobs["2"].remote_eligibility is RemoteEligibility.SPAIN_ONLY
    assert jobs["3"].remote_eligibility is RemoteEligibility.UNKNOWN and jobs["3"].location == "Remote — Europe"
    assert jobs["3"].salary_min is None
    assert jobs["4"].remote_eligibility is RemoteEligibility.UNKNOWN and jobs["4"].location == "Remote — Germany, Spain"
    assert jobs["1"].salary_min == Decimal("50000") and jobs["1"].currency == "EUR"
    assert jobs["1"].employment_type is EmploymentType.FULL_TIME
    assert jobs["1"].apply_url == jobs["1"].source_url
    assert jobs["1"].published_at is None  # naive timestamp is not guessed
    assert jobs["5"].published_at == datetime(2026, 10, 1, 9, 30, tzinfo=UTC) and jobs["5"].location is None


def test_jobicy_bad_payload_is_a_safe_error():
    client, _ = client_for(lambda request: httpx.Response(200, json={"jobs": "nope"}))
    with pytest.raises(JobicyConnectorError, match="unexpected"):
        JobicyConnector(client=client).fetch_jobs()


def test_remotive_portal_makes_one_category_request():
    payload = {"jobs": [{
        "id": 1, "url": "https://remotive.com/remote-jobs/software-dev/backend-1", "title": "Backend",
        "company_name": "Acme", "candidate_required_location": "Worldwide", "description": "<p>x</p>",
        "publication_date": "2026-10-01T08:00:00", "job_type": "full_time", "salary": "",
    }]}
    client, requests = client_for(lambda request: httpx.Response(200, json=payload))
    (job,) = PORTALS["remotive"].build(client).fetch_jobs()

    assert len(requests) == 1 and requests[0].url.params["category"] == "software-dev"
    assert job.remote_eligibility is RemoteEligibility.WORLDWIDE


def test_registry_intervals_and_selection():
    assert parse_portal_names("Himalayas, adzuna,remoteok,remotive,jobicy") == (
        "himalayas", "adzuna", "remoteok", "remotive", "jobicy",
    )
    for name in ("remoteok", "remotive", "jobicy"):
        assert timedelta(hours=2) <= PORTALS[name].min_interval <= timedelta(hours=6)
    assert PORTALS["adzuna"].min_interval >= timedelta(hours=12)


def test_missing_adzuna_credentials_fail_softly_and_are_not_recorded(tmp_path, monkeypatch):
    monkeypatch.delenv("ADZUNA_APP_ID", raising=False)
    monkeypatch.delenv("ADZUNA_APP_KEY", raising=False)
    monkeypatch.chdir(tmp_path)  # no .env here
    state = tmp_path / "state.json"
    client, requests = client_for(lambda request: httpx.Response(200, json={}))

    offers, failures = fetch_portals(["adzuna"], client=client, state_path=state)

    assert offers == [] and [f.error_type for f in failures] == ["AdzunaNotConfigured"]
    assert requests == []
    assert job_portals.due_portals(["adzuna"], state_path=state) == ["adzuna"]


@pytest.mark.parametrize(
    ("url", "name"),
    [
        ("https://www.adzuna.es/land/ad/1", "Jobs by Adzuna"),
        ("https://remoteok.com/remote-jobs/x", "Remote OK"),
        ("https://remotive.com/remote-jobs/x", "Remotive"),
        ("https://jobicy.com/jobs/1", "Jobicy"),
        ("https://himalayas.app/companies/a/jobs/b", "Himalayas"),
    ],
)
def test_portal_credit_names_the_portal(url, name):
    assert portal_credit(url)[0] == name
    assert portal_credit("https://notremoteok.com/x") is None
    assert portal_credit(None) is None
