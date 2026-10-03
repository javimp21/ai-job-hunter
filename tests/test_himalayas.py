from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from ai_job_hunter.candidates import JobFacts, evaluate_job, load_candidate_config
from ai_job_hunter.candidates.prefilter import SignalStatus
from ai_job_hunter.connectors.himalayas import HimalayasConnector, HimalayasConnectorError
from ai_job_hunter.decision_engine import DecisionCache
from ai_job_hunter.domain.normalized_job import EmploymentType, RemoteEligibility, SalaryPeriod
from ai_job_hunter.models import Job
from ai_job_hunter.services import job_portals, opportunities
from ai_job_hunter.services.job_portals import due_portals, fetch_portals, parse_portal_names

EXAMPLE_CANDIDATE = Path(__file__).parents[1] / "config" / "examples" / "candidate.example.json"


def raw_job(slug: str, countries: list[str], **changes):
    job = {
        "title": "Backend Engineer",
        "companyName": "Acme",
        "guid": f"https://himalayas.app/companies/acme/jobs/{slug}",
        "applicationLink": f"https://himalayas.app/companies/acme/jobs/{slug}",
        "locationRestrictions": countries,
        "minSalary": 60000,
        "maxSalary": 80000,
        "currency": "eur",
        "salaryPeriod": "annual",
        "employmentType": "Full Time",
        "pubDate": 1790927730,
        "description": "<p>Build Java services.</p><ul><li>2+ years</li></ul>",
    }
    job.update(changes)
    return job


def client_for(pages):
    """Serve successive pages per query; records requests."""

    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        cursor = request.url.params.get("cursor")
        return httpx.Response(200, json=pages[cursor])

    return httpx.Client(transport=httpx.MockTransport(handler)), requests


def test_search_paginates_with_cursor_and_normalizes_fields():
    client, requests = client_for({
        None: {"jobs": [raw_job("a", []), raw_job("b", ["Spain"])], "nextCursor": "next"},
        "next": {"jobs": [raw_job("c", ["Germany", "Spain"], minSalary=None, maxSalary=None), "junk"]},
    })
    connector = HimalayasConnector(queries=("backend engineer",), client=client)

    jobs = {job.external_id: job for job in connector.fetch_jobs()}

    assert len(requests) == 2
    assert requests[0].url.params["country"] == "Spain" and requests[0].url.params["q"] == "backend engineer"
    worldwide = jobs["companies/acme/jobs/a"]
    assert worldwide.remote_eligibility is RemoteEligibility.WORLDWIDE
    assert (worldwide.salary_min, worldwide.salary_max) == (Decimal("60000"), Decimal("80000"))
    assert (worldwide.currency, worldwide.salary_period) == ("EUR", SalaryPeriod.YEAR)
    assert worldwide.employment_type is EmploymentType.FULL_TIME
    assert "Build Java services." in worldwide.description and "2+ years" in worldwide.description
    assert worldwide.published_at == datetime.fromtimestamp(1790927730, tz=UTC)
    assert jobs["companies/acme/jobs/b"].remote_eligibility is RemoteEligibility.SPAIN_ONLY
    restricted = jobs["companies/acme/jobs/c"]
    assert restricted.location == "Remote — Germany, Spain"
    assert restricted.salary_min is None and restricted.currency is None


def test_duplicate_jobs_across_queries_are_merged_and_errors_are_safe():
    client, _ = client_for({None: {"jobs": [raw_job("a", [])]}})
    connector = HimalayasConnector(queries=("backend", "java"), client=client)
    assert len(connector.fetch_jobs()) == 1

    failing = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(429)))
    with pytest.raises(HimalayasConnectorError, match="429"):
        HimalayasConnector(client=failing).fetch_jobs()


@pytest.mark.parametrize(
    ("countries", "expected"),
    [
        ([], SignalStatus.COMPATIBLE),
        (["Spain"], SignalStatus.COMPATIBLE),
        ([f"Country {index}" for index in range(120)] + ["Spain"], SignalStatus.COMPATIBLE),
        (["Germany", "France"], SignalStatus.INCOMPATIBLE),
        (["United States"], SignalStatus.INCOMPATIBLE),
    ],
)
def test_location_restrictions_drive_spain_eligibility(countries, expected):
    client, _ = client_for({None: {"jobs": [raw_job("a", countries)]}})
    (job,) = HimalayasConnector(queries=("q",), client=client).fetch_jobs()
    candidate = load_candidate_config(EXAMPLE_CANDIDATE)
    candidate = candidate.model_copy(update={"profile": candidate.profile.model_copy(update={"current_country": "Spain"})})

    assert len(job.location) <= 255
    assert evaluate_job(JobFacts.from_normalized_job(job), candidate).signals.geography.status is expected


def test_portals_are_throttled_and_names_validated(tmp_path, monkeypatch):
    state = tmp_path / "portal-state.json"
    calls = []

    class FakeConnector:
        def fetch_jobs(self):
            calls.append(1)
            return []

    monkeypatch.setitem(
        job_portals.PORTALS,
        "himalayas",
        job_portals.PortalSpec("himalayas", timedelta(hours=20), lambda client: FakeConnector(), (RuntimeError,)),
    )
    now = datetime(2026, 10, 3, 12, tzinfo=UTC)

    assert due_portals(["himalayas"], state_path=state, now=now) == ["himalayas"]
    fetch_portals(["himalayas"], state_path=state, record=False, now=now)
    assert due_portals(["himalayas"], state_path=state, now=now) == ["himalayas"]  # dry run kept no state
    fetch_portals(["himalayas"], state_path=state, now=now)
    assert due_portals(["himalayas"], state_path=state, now=now + timedelta(hours=19)) == []
    assert due_portals(["himalayas"], state_path=state, now=now + timedelta(hours=21)) == ["himalayas"]
    assert len(calls) == 2
    assert parse_portal_names(" Himalayas, ,himalayas") == ("himalayas",)
    assert parse_portal_names("") == ()
    with pytest.raises(ValueError, match="Unknown job portal"):
        parse_portal_names("linkedin")


def test_refresh_ingests_portal_jobs_without_company_boards(db_session, monkeypatch, tmp_path):
    client, _ = client_for({None: {"jobs": [raw_job("a", ["Spain"]), raw_job("b", ["United States"])]}})
    monkeypatch.setitem(
        job_portals.PORTALS,
        "himalayas",
        job_portals.PortalSpec(
            "himalayas", timedelta(hours=20), lambda _client: HimalayasConnector(queries=("q",), client=client), ()
        ),
    )
    monkeypatch.setattr(opportunities, "_fetch_targets", lambda *a, **k: pytest.fail("no boards are active"))

    summary = opportunities.refresh_opportunities(
        db_session,
        load_candidate_config(EXAMPLE_CANDIDATE),
        no_jev=True,
        engine=type("Engine", (), {"cache_identity": "offline"})(),
        cache=DecisionCache(tmp_path / "cache.json"),
        portals=("himalayas",),
        portal_state_path=tmp_path / "portal-state.json",
    )

    assert summary.portals_checked == 1
    assert summary.jobs_fetched == 2
    assert db_session.query(Job).count() == 2
    assert (tmp_path / "portal-state.json").exists()
