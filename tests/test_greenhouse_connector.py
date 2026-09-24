import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from ai_job_hunter.connectors import GreenhouseConnector, GreenhouseConnectorError, JobConnector
from ai_job_hunter.domain.normalized_job import (
    EmploymentType,
    RemoteEligibility,
    RemotePolicy,
)

FIXTURE = Path(__file__).parent / "fixtures" / "greenhouse_jobs.json"


def payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def make_connector(*, handler=None, body=None, status=200, **kwargs):
    if handler is None:
        handler = lambda _request: httpx.Response(status, json=body if body is not None else payload())
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return GreenhouseConnector("exampleco", client=client, **kwargs), client


def test_greenhouse_connector_normalizes_offers_and_preserves_fields():
    requests = []
    connector, client = make_connector(handler=lambda req: (requests.append(req), httpx.Response(200, json=payload()))[1], company_name="Example Co")
    try:
        assert isinstance(connector, JobConnector)
        first, second = connector.fetch_jobs()
    finally:
        client.close()

    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert str(requests[0].url) == (
        "https://boards-api.greenhouse.io/v1/boards/exampleco/jobs?content=true"
    )
    assert requests[0].headers["accept"] == "application/json"
    assert first.provider == "greenhouse"
    assert first.external_id == "48123"
    assert first.title == "Backend Software Engineer"
    assert first.company_name == "Example Co"
    assert first.source_url == "https://job-boards.greenhouse.io/exampleco/jobs/48123"
    assert first.canonical_url == first.source_url
    assert first.apply_url is None
    assert first.location == "Barcelona, Spain"
    assert first.published_at == datetime(2026, 9, 18, 9, 30, tzinfo=UTC)
    assert first.description == "<p>Build APIs with Python.</p>\nWork with the platform team."
    assert first.salary_min is None
    assert first.employment_type is None
    assert first.remote_policy is None
    assert first.remote_eligibility is RemoteEligibility.UNKNOWN
    assert first.raw_metadata["metadata"][0]["value"] == "Platform"
    assert first.raw_metadata["updated_at"] == "2026-09-20T11:00:00+00:00"

    assert second.external_id == "48124"
    assert second.company_name == "Example Co"
    assert second.location is None
    assert second.description is None
    assert second.published_at is None
    assert second.raw_metadata == {
        "id": "48124",
        "title": "Platform Engineer",
        "absolute_url": "https://job-boards.greenhouse.io/exampleco/jobs/48124",
    }


def test_greenhouse_connector_caps_normalized_results_and_accepts_api_company_name():
    data = payload()
    data["jobs"][0]["company_name"] = "API Company"
    connector, client = make_connector(body=data, max_jobs=1)
    try:
        (offer,) = connector.fetch_jobs()
    finally:
        client.close()
    assert offer.company_name == "API Company"


def test_greenhouse_http_error_is_reported():
    connector, client = make_connector(status=429, body={"error": "rate limited"})
    try:
        with pytest.raises(GreenhouseConnectorError, match="HTTP 429"):
            connector.fetch_jobs()
    finally:
        client.close()


def test_greenhouse_invalid_json_is_reported():
    connector, client = make_connector(
        handler=lambda _request: httpx.Response(200, content=b"not json")
    )
    try:
        with pytest.raises(GreenhouseConnectorError, match="invalid JSON"):
            connector.fetch_jobs()
    finally:
        client.close()


def test_greenhouse_malformed_payload_and_required_title_are_reported():
    connector, client = make_connector(body={"jobs": {}})
    try:
        with pytest.raises(GreenhouseConnectorError, match="jobs list"):
            connector.fetch_jobs()
    finally:
        client.close()

    connector, client = make_connector(body={"jobs": [{"id": 1}]})
    try:
        with pytest.raises(GreenhouseConnectorError, match="index 0"):
            connector.fetch_jobs()
    finally:
        client.close()


def test_greenhouse_constructor_rejects_invalid_limits():
    with pytest.raises(ValueError, match="max_jobs"):
        GreenhouseConnector("exampleco", max_jobs=0)


def test_greenhouse_omits_overlong_location_from_normalized_field_but_keeps_raw_value():
    data = payload()
    location = "; ".join(f"Office {index}, Some City, Some Country" for index in range(20))
    data["jobs"][0]["location"]["name"] = location
    connector, client = make_connector(body=data)
    try:
        (offer,) = connector.fetch_jobs()[:1]
    finally:
        client.close()
    assert offer.location is None
    assert offer.raw_metadata["location"]["name"] == location
