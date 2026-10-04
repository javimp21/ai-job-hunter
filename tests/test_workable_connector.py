from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from ai_job_hunter.connectors import JobConnector, WorkableConnector, WorkableConnectorError
from ai_job_hunter.domain.normalized_job import EmploymentType, RemoteEligibility, RemotePolicy

PAYLOAD = {
    "name": "Example Health",
    "description": "<p>About us</p>",
    "jobs": [
        {
            "title": "Backend Engineer",
            "shortcode": "ABC123",
            "employment_type": "Full-time",
            "telecommuting": True,
            "department": "Technology",
            "url": "https://apply.workable.com/j/ABC123",
            "shortlink": "https://apply.workable.com/j/ABC123",
            "application_url": "https://apply.workable.com/j/ABC123/apply",
            "published_on": "2026-09-22",
            "country": "Spain",
            "city": "Madrid",
            "experience": "Mid-Senior level",
            "locations": [
                {"country": "Spain", "countryCode": "ES", "city": "Madrid", "region": None, "hidden": False},
                {"country": "Portugal", "countryCode": "PT", "city": "Lisbon", "hidden": False},
                {"country": "France", "city": "Paris", "hidden": True},
            ],
            "description": "<p>Build <strong>APIs</strong>.</p><ul><li>Python</li></ul>",
        },
        {
            "title": "Designer",
            "shortcode": "DEF456",
            "employment_type": "Something else",
            "telecommuting": False,
            "url": "https://apply.workable.com/j/DEF456",
            "published_on": "not a date",
            "locations": [],
            "description": "",
        },
    ],
}


def make_connector(*, payload=PAYLOAD, status=200, handler=None, **kwargs):
    if handler is None:
        handler = lambda _request: httpx.Response(status, json=payload)
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return WorkableConnector("example", client=client, **kwargs), client


def test_connector_reads_widget_api_and_normalizes_jobs():
    requests = []
    connector, client = make_connector(
        handler=lambda req: (requests.append(req), httpx.Response(200, json=PAYLOAD))[1]
    )
    try:
        assert isinstance(connector, JobConnector)
        first, second = connector.fetch_jobs()
    finally:
        client.close()

    assert len(requests) == 1
    assert str(requests[0].url) == "https://apply.workable.com/api/v1/widget/accounts/example?details=true"
    assert "authorization" not in requests[0].headers
    assert first.provider == "workable"
    assert first.external_id == "ABC123"
    assert first.title == "Backend Engineer"
    assert first.company_name == "Example Health"
    assert first.source_url == first.canonical_url == "https://apply.workable.com/j/ABC123"
    assert first.apply_url == "https://apply.workable.com/j/ABC123/apply"
    assert first.description == "Build APIs.\nPython"
    assert first.location == "Madrid, Spain; Lisbon, Portugal"
    assert first.remote_policy is RemotePolicy.REMOTE
    assert first.remote_eligibility is RemoteEligibility.UNKNOWN
    assert first.employment_type is EmploymentType.FULL_TIME
    assert first.published_at == datetime(2026, 9, 22, tzinfo=UTC)
    assert first.raw_metadata["department"] == "Technology"

    assert second.title == "Designer"
    assert second.location is None
    assert second.remote_policy is None  # telecommuting=false is not evidence of on-site
    assert second.employment_type is None
    assert second.published_at is None
    assert second.description is None
    assert second.apply_url == "https://apply.workable.com/j/DEF456"


def test_configured_company_name_wins_and_max_jobs_limits():
    connector, client = make_connector(company_name="Configured", max_jobs=1)
    try:
        jobs = connector.fetch_jobs()
    finally:
        client.close()
    assert len(jobs) == 1
    assert jobs[0].company_name == "Configured"


@pytest.mark.parametrize("status", [404, 429, 500, 302])
def test_http_errors_are_wrapped(status):
    connector, client = make_connector(status=status)
    try:
        with pytest.raises(WorkableConnectorError, match=str(status)):
            connector.fetch_jobs()
    finally:
        client.close()


def test_invalid_payloads_are_rejected():
    for body in ([], {"jobs": "x"}, {"jobs": ["x"]}, {"jobs": [{"title": ""}]}):
        connector, client = make_connector(payload=body)
        try:
            with pytest.raises(WorkableConnectorError):
                connector.fetch_jobs()
        finally:
            client.close()
    connector, client = make_connector(handler=lambda _r: httpx.Response(200, content=b"not json"))
    try:
        with pytest.raises(WorkableConnectorError, match="invalid JSON"):
            connector.fetch_jobs()
    finally:
        client.close()


def test_network_errors_are_wrapped():
    def boom(request):
        raise httpx.ConnectError("down", request=request)

    connector, client = make_connector(handler=boom)
    try:
        with pytest.raises(WorkableConnectorError, match="Could not reach"):
            connector.fetch_jobs()
    finally:
        client.close()


@pytest.mark.parametrize("account", ["", " ", "a/b", "a.b", "../x", "-x"])
def test_account_slug_is_validated(account):
    with pytest.raises(ValueError):
        WorkableConnector(account)
