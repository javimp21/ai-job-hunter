from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from ai_job_hunter.candidates import load_candidate_config
from ai_job_hunter.connectors.manfred import ManfredConnector, ManfredConnectorError
from ai_job_hunter.decision_engine import DecisionCache, FinalDecision
from ai_job_hunter.domain.normalized_job import EmploymentType, RemoteEligibility, RemotePolicy, SalaryPeriod
from ai_job_hunter.models import Job
from ai_job_hunter.services import job_portals, opportunities
from ai_job_hunter.services.notifications import format_notification_message
from tests.test_notifications import _opportunity

EXAMPLE_CANDIDATE = Path(__file__).parents[1] / "config" / "examples" / "candidate.example.json"


def raw_offer(offer_id: int, **changes):
    offer = {
        "id": offer_id,
        "position": "Backend Engineer",
        "slug": f"acme-backend-{offer_id}",
        "status": "ACTIVE",
        "salaryFrom": 45000,
        "salaryTo": 55000,
        "remotePercentage": 100,
        "currency": "€",
        "locations": ["Madrid, España"],
        "offerLanguages": ["ES"],
        "updatedAt": "2026-10-02T11:01:17.887Z",
        "isFreelance": False,
        "company": {"name": "Acme", "web": "https://acme.example"},
    }
    offer.update(changes)
    return offer


def detail(offer_id: int):
    return {
        **raw_offer(offer_id),
        "introduction": "**Intro** con [enlace](https://x.example)",
        "responsibilities": ["Diseñar APIs", "Mejorar tests"],
        "whatOffering": "Remoto 100%",
        "workingDayInfo": {"isFullTime": True},
        "lastStatusChange": "2026-10-01T09:30:00.000Z",
        "techs": [{"name": "Java", "icon": {"id": 1}}, {"name": "Spring Boot"}, {"name": "Java"}, {"icon": {}}],
        "scout": {"email": "scout@getmanfred.example"},
    }


def client_for(listing, details=None, requests=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(request)
        assert request.url.params["lang"] == "ES"
        if request.url.path.endswith("/offers"):
            return httpx.Response(200, json=listing)
        offer_id = int(request.url.path.rsplit("/", 1)[1])
        if details is None or offer_id not in details:
            return httpx.Response(404)
        return httpx.Response(200, json=details[offer_id])

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_only_active_offers_are_kept_and_mapped_conservatively():
    requests = []
    listing = [
        raw_offer(1),
        raw_offer(2, status="CLOSED"),
        raw_offer(3, remotePercentage=0, salaryFrom=0, locations=[]),
        raw_offer(4, remotePercentage=40, isFreelance=True, currency="CHF"),
        raw_offer(5, remotePercentage="n/a", salaryFrom=60000, salaryTo=50000),
        "junk",
    ]
    bare = {offer_id: raw_offer(offer_id) for offer_id in (3, 4, 5)}
    for offer_id, changes in ((3, {"remotePercentage": 0, "salaryFrom": 0, "locations": []}),
                              (4, {"remotePercentage": 40, "isFreelance": True, "currency": "CHF"}),
                              (5, {"remotePercentage": "n/a", "salaryFrom": 60000, "salaryTo": 50000})):
        bare[offer_id].update(changes)
    client = client_for(listing, {1: detail(1), **bare}, requests)

    jobs = {job.external_id: job for job in ManfredConnector(client=client, detail_pause=0).fetch_jobs()}

    assert set(jobs) == {"1", "3", "4", "5"}
    assert len(requests) == 5  # one list + four details
    full = jobs["1"]
    assert full.source_url == "https://www.getmanfred.com/ofertas-empleo/1/acme-backend-1"
    assert full.remote_policy is RemotePolicy.REMOTE and full.remote_eligibility is RemoteEligibility.UNKNOWN
    assert (full.salary_min, full.salary_max) == (Decimal("45000"), Decimal("55000"))
    assert (full.currency, full.salary_period) == ("EUR", SalaryPeriod.YEAR)
    assert full.employment_type is EmploymentType.FULL_TIME
    # The detail's lastStatusChange (when the offer became ACTIVE) is the publication date.
    assert full.published_at is not None and full.published_at.isoformat() == "2026-10-01T09:30:00+00:00"
    assert "Tecnologías\nJava, Spring Boot" in full.description
    assert full.location == "Madrid, España" and full.company_name == "Acme"
    assert "Intro con enlace" in full.description and "- Diseñar APIs" in full.description
    assert "scout" not in str(full.raw_metadata)
    onsite = jobs["3"]
    assert onsite.remote_policy is RemotePolicy.ONSITE and onsite.location is None
    assert onsite.salary_min is None and onsite.salary_max == Decimal("55000")
    assert onsite.description is None and onsite.published_at is None  # empty detail: no text, no date
    hybrid = jobs["4"]
    assert hybrid.remote_policy is RemotePolicy.HYBRID and hybrid.employment_type is EmploymentType.CONTRACT
    assert hybrid.currency is None and hybrid.salary_period is None  # unknown currency: no invented salary
    unknown = jobs["5"]
    assert unknown.remote_policy is None and unknown.salary_min is None and unknown.salary_max is None


def test_offers_whose_detail_fails_are_skipped_until_a_later_run():
    listing = [raw_offer(1), raw_offer(2)]
    jobs = ManfredConnector(client=client_for(listing, {1: detail(1)}), detail_pause=0).fetch_jobs()
    assert [job.external_id for job in jobs] == ["1"]  # offer 2 had no detail (404)

    with pytest.raises(ManfredConnectorError, match="details are unavailable"):
        ManfredConnector(client=client_for(listing, {}), detail_pause=0).fetch_jobs()


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(503),
        httpx.Response(200, text="<html>"),
        httpx.Response(200, json={"offers": []}),
        httpx.Response(200, json=[{"title": "x"}]),
        httpx.Response(200, json=[{"id": 1, "status": "ACTIVE", "position": "No slug"}]),
    ],
)
def test_shape_changes_fail_with_a_safe_error(response):
    client = httpx.Client(transport=httpx.MockTransport(lambda request: response))
    with pytest.raises(ManfredConnectorError):
        ManfredConnector(client=client, detail_pause=0).fetch_jobs()


def test_empty_listing_is_not_an_error():
    assert ManfredConnector(client=client_for([]), detail_pause=0).fetch_jobs() == []


def test_manfred_is_throttled_hourly_and_enabled_by_name():
    spec = job_portals.PORTALS["manfred"]
    assert spec.min_interval == timedelta(hours=1)
    assert spec.errors == (ManfredConnectorError,)
    assert job_portals.parse_portal_names("himalayas, Manfred") == ("himalayas", "manfred")


def test_failing_portal_does_not_stop_refresh(tmp_path):
    failing = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(500)))
    offers, failures = job_portals.fetch_portals(["manfred"], client=failing, state_path=tmp_path / "state.json")
    assert offers == [] and [(f.portal, f.error_type) for f in failures] == [("manfred", "ManfredConnectorError")]
    assert job_portals.due_portals(["manfred"], state_path=tmp_path / "state.json") == ["manfred"]


def test_refresh_ingests_manfred_jobs(db_session, monkeypatch, tmp_path):
    client = client_for([raw_offer(1), raw_offer(2, locations=[])], {1: detail(1), 2: detail(2)})
    monkeypatch.setitem(
        job_portals.PORTALS,
        "manfred",
        job_portals.PortalSpec(
            "manfred", timedelta(hours=1), lambda _c: ManfredConnector(client=client, detail_pause=0), ()
        ),
    )
    monkeypatch.setattr(opportunities, "_fetch_targets", lambda *a, **k: pytest.fail("no boards are active"))

    summary = opportunities.refresh_opportunities(
        db_session,
        load_candidate_config(EXAMPLE_CANDIDATE),
        no_jev=True,
        engine=type("Engine", (), {"cache_identity": "offline"})(),
        cache=DecisionCache(tmp_path / "cache.json"),
        portals=("manfred",),
        portal_state_path=tmp_path / "portal-state.json",
    )

    assert summary.portals_checked == 1 and summary.jobs_fetched == 2
    assert db_session.query(Job).count() == 2


def test_alert_shows_a_manfred_credit_link():
    item = replace(
        _opportunity(uuid4(), FinalDecision.REVIEW, 79),
        url="https://www.getmanfred.com/ofertas-empleo/1/acme-backend-1",
    )
    message = format_notification_message(item)
    assert '📡 Fuente: <a href="https://www.getmanfred.com">Manfred</a>' in message
