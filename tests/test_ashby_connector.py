from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from ai_job_hunter.connectors import AshbyConnector, AshbyConnectorError, JobConnector
from ai_job_hunter.domain.normalized_job import (
    EmploymentType,
    RemoteEligibility,
    RemotePolicy,
    SalaryPeriod,
)

FIXTURE = Path(__file__).parent / "fixtures" / "ashby_jobs.json"


def payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def make_connector(*, handler=None, body=None, status=200, **kwargs):
    if handler is None:
        handler = lambda _request: httpx.Response(status, json=body if body is not None else payload())
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return AshbyConnector("example-product", client=client, **kwargs), client


def test_ashby_connector_uses_public_api_and_maps_current_listed_jobs():
    requests = []
    connector, client = make_connector(
        handler=lambda req: (requests.append(req), httpx.Response(200, json=payload()))[1],
        company_name="Example Product Co",
    )
    try:
        assert isinstance(connector, JobConnector)
        first, second = connector.fetch_jobs()
    finally:
        client.close()

    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert requests[0].url.host == "api.ashbyhq.com"
    assert requests[0].url.path == "/posting-api/job-board/example-product"
    assert requests[0].url.params["includeCompensation"] == "true"
    assert first.provider == "ashby"
    assert first.external_id == "ashby-role-1"
    assert first.title == "Backend Engineer"
    assert first.company_name == "Example Product Co"
    assert first.source_url == "https://jobs.ashbyhq.com/example-product/ashby-role-1"
    assert first.canonical_url == first.source_url
    assert first.apply_url.endswith("/application")
    assert first.location == "Remote — Spain; Madrid, Spain; Lisbon, Portugal"
    assert first.remote_policy is RemotePolicy.REMOTE
    assert first.remote_eligibility is RemoteEligibility.UNKNOWN
    assert first.salary_min == Decimal("65000")
    assert first.salary_max == Decimal("80000")
    assert first.currency == "EUR"
    assert first.salary_period is SalaryPeriod.YEAR
    assert first.employment_type is EmploymentType.FULL_TIME
    assert first.published_at == datetime(2026, 9, 21, 9, 15, tzinfo=UTC)
    assert "backend APIs" in first.description
    assert first.raw_metadata["team"] == "Platform"
    assert first.raw_metadata["compensation"]["summaryComponents"][0]["minValue"] == 65000

    assert second.external_id == "ashby-role-2"
    assert second.title == "Product Engineer"
    assert second.location == "London, UK"
    assert second.remote_policy is RemotePolicy.HYBRID
    assert second.employment_type is EmploymentType.CONTRACT
    assert second.salary_min is None and second.salary_max is None
    assert second.currency is None and second.salary_period is None
    assert second.description == "Own product integrations."
    assert len([job for job in (first, second) if job.provider == "ashby"]) == 2


def test_ashby_connector_caps_only_listed_jobs():
    connector, client = make_connector(max_jobs=1)
    try:
        (offer,) = connector.fetch_jobs()
    finally:
        client.close()
    assert offer.external_id == "ashby-role-1"


def test_ashby_malformed_response_and_job_are_reported():
    connector, client = make_connector(body={"jobs": {}})
    try:
        with pytest.raises(AshbyConnectorError, match="jobs list"):
            connector.fetch_jobs()
    finally:
        client.close()

    connector, client = make_connector(body={"jobs": [{"id": "no-title"}]})
    try:
        with pytest.raises(AshbyConnectorError, match="index 0"):
            connector.fetch_jobs()
    finally:
        client.close()


def test_ashby_http_error_and_invalid_json_are_reported():
    connector, client = make_connector(status=503, body={"error": "unavailable"})
    try:
        with pytest.raises(AshbyConnectorError, match="HTTP 503"):
            connector.fetch_jobs()
    finally:
        client.close()

    connector, client = make_connector(handler=lambda _request: httpx.Response(200, content=b"not json"))
    try:
        with pytest.raises(AshbyConnectorError, match="invalid JSON"):
            connector.fetch_jobs()
    finally:
        client.close()


def test_ashby_salary_requires_one_structured_salary_component():
    data = payload()
    salary = data["jobs"][0]["compensation"]["summaryComponents"][0]
    salary["interval"] = "NONE"
    connector, client = make_connector(body=data)
    try:
        offers = connector.fetch_jobs()
    finally:
        client.close()
    assert offers[0].salary_min is None
    assert offers[0].currency is None
