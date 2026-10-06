from __future__ import annotations

from decimal import Decimal

import httpx
import pytest

from ai_job_hunter.ats_discovery import discover_ats_url
from ai_job_hunter.connectors import JobConnector, RecruiteeConnector, RecruiteeConnectorError
from ai_job_hunter.domain.company_intelligence import ATSProvider
from ai_job_hunter.domain.normalized_job import EmploymentType, RemoteEligibility, RemotePolicy, SalaryPeriod

PAYLOAD = {
    "offers": [
        {
            "id": 2772077,
            "status": "published",
            "title": "Backend Engineer (m/f/d) - Kotlin / Java",
            "careers_url": "https://acme.recruitee.com/o/backend-engineer",
            "careers_apply_url": "https://acme.recruitee.com/o/backend-engineer/c/new",
            "description": "<p>Build <strong>payment</strong> services.</p>",
            "requirements": "<ul><li>Kotlin</li><li>Java</li></ul>",
            "location": "Berlin, Berlin, Germany",
            "country_code": "DE",
            "department": "Technology",
            "employment_type_code": "fulltime_permanent",
            "experience_code": "experienced",
            "remote": False,
            "hybrid": True,
            "on_site": True,
            "published_at": "2026-10-06 14:25:18 UTC",
            "salary": {"min": "60000", "max": "70000", "period": "year", "currency": "EUR"},
            "company_name": "acme",
        },
        {
            "id": 5,
            "status": "published",
            "title": "Junior Developer",
            "careers_url": "https://acme.recruitee.com/o/junior-developer",
            "location": "Remote",
            "remote": False,
            "hybrid": False,
            "on_site": False,
            "salary": {"min": None, "max": None, "period": None, "currency": None},
        },
        {"id": 6, "status": "draft", "title": "Hidden", "careers_url": "https://acme.recruitee.com/o/hidden"},
    ]
}


def connector(handler, **kwargs):
    return RecruiteeConnector("acme", client=httpx.Client(transport=httpx.MockTransport(handler)), **kwargs)


def test_offers_are_normalized_and_only_stated_facts_are_kept():
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json=PAYLOAD)

    source = connector(handler, company_name="Acme GmbH")
    assert isinstance(source, JobConnector)
    first, second = source.fetch_jobs()

    assert str(seen[0].url) == "https://acme.recruitee.com/api/offers/"
    assert first.provider == "recruitee" and first.external_id == "2772077" and first.company_name == "Acme GmbH"
    assert first.apply_url == "https://acme.recruitee.com/o/backend-engineer/c/new"
    assert first.location == "Berlin, Berlin, Germany" and first.employment_type is EmploymentType.FULL_TIME
    assert first.remote_policy is RemotePolicy.HYBRID and first.published_at.year == 2026
    assert (first.salary_min, first.salary_max, first.currency) == (Decimal("60000"), Decimal("70000"), "EUR")
    assert first.salary_period is SalaryPeriod.YEAR
    assert "payment" in first.description and "Kotlin" in first.description and "<p>" not in first.description
    # False flags and empty salaries are "not stated", never on-site, remote or zero.
    assert second.remote_policy is None and second.remote_eligibility is RemoteEligibility.UNKNOWN
    assert second.salary_min is None and second.currency is None


def test_errors_are_safe_and_bounded():
    with pytest.raises(RecruiteeConnectorError, match="HTTP 404"):
        connector(lambda r: httpx.Response(404)).fetch_jobs()
    with pytest.raises(RecruiteeConnectorError, match="offers list"):
        connector(lambda r: httpx.Response(200, json={"jobs": []})).fetch_jobs()
    with pytest.raises(RecruiteeConnectorError, match="invalid JSON"):
        connector(lambda r: httpx.Response(200, text="<html>")).fetch_jobs()

    def boom(request):
        raise httpx.ConnectError("secret detail")

    with pytest.raises(RecruiteeConnectorError, match="Could not reach") as caught:
        connector(boom).fetch_jobs()
    assert "secret" not in str(caught.value)
    assert len(connector(lambda r: httpx.Response(200, json=PAYLOAD), max_jobs=1).fetch_jobs()) == 1
    with pytest.raises(ValueError):
        RecruiteeConnector("bad/slug")


def test_recruitee_boards_are_recognised_from_their_subdomain():
    result = discover_ats_url("https://rebuy.recruitee.com/o/backend-engineer")
    assert (result.provider, result.identifier) == (ATSProvider.RECRUITEE, "rebuy")
    assert discover_ats_url("https://www.recruitee.com/").provider is not ATSProvider.RECRUITEE
