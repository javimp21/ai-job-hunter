import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from ai_job_hunter.connectors import JobConnector, LeverConnector, LeverConnectorError
from ai_job_hunter.domain.normalized_job import (
    EmploymentType,
    RemoteEligibility,
    RemotePolicy,
    SalaryPeriod,
)

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def make_client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_lever_connector_normalizes_structured_posting_fields():
    requests = []
    page = fixture("lever_jobs_page_one.json")
    client = make_client(lambda req: (requests.append(req), httpx.Response(200, json=page))[1])
    connector = LeverConnector("exampleco", company_name="Example Co", region="eu", client=client)
    try:
        assert isinstance(connector, JobConnector)
        first, second = connector.fetch_jobs()
    finally:
        client.close()

    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert requests[0].url.host == "api.eu.lever.co"
    assert requests[0].url.path == "/v0/postings/exampleco"
    assert dict(requests[0].url.params) == {"mode": "json", "skip": "0", "limit": "100"}
    assert first.provider == "lever"
    assert first.external_id == "lever-role-1"
    assert first.title == "Backend Engineer"
    assert first.company_name == "Example Co"
    assert first.source_url == "https://jobs.eu.lever.co/exampleco/lever-role-1"
    assert first.canonical_url == first.source_url
    assert first.apply_url == "https://jobs.eu.lever.co/exampleco/lever-role-1/apply"
    assert first.location == "Remote, ES"
    assert first.description == "Build services with Go and PostgreSQL."
    assert first.remote_policy is RemotePolicy.REMOTE
    assert first.remote_eligibility is RemoteEligibility.UNKNOWN
    assert first.salary_min == Decimal("45000")
    assert first.salary_max == Decimal("65000")
    assert first.currency == "EUR"
    assert first.salary_period is SalaryPeriod.YEAR
    assert first.employment_type is EmploymentType.FULL_TIME
    assert first.published_at == datetime.fromtimestamp(1790000000, tz=UTC)
    assert first.raw_metadata["updatedAt"] == 1790100000000

    assert second.external_id == "lever-role-2"
    assert second.title == "Graduate Platform Developer"
    assert second.company_name == "Example Co"
    assert second.location == "Dublin, IE"
    assert second.description == "Learn with the platform group."
    assert second.remote_policy is None
    assert second.remote_eligibility is RemoteEligibility.UNKNOWN
    assert second.salary_min is None and second.salary_period is None
    assert second.employment_type is EmploymentType.INTERNSHIP


def test_lever_connector_follows_skip_pagination_until_short_page():
    requests = []
    page_one = fixture("lever_jobs_page_one.json")
    page_two = fixture("lever_jobs_page_two.json")

    def handler(request):
        requests.append(request)
        skip = int(request.url.params["skip"])
        return httpx.Response(200, json=page_one if skip == 0 else page_two)

    client = make_client(handler)
    connector = LeverConnector("exampleco", page_size=2, client=client)
    try:
        offers = connector.fetch_jobs()
    finally:
        client.close()

    assert [offer.external_id for offer in offers] == [
        "lever-role-1", "lever-role-2", "lever-role-3"
    ]
    assert [request.url.params["skip"] for request in requests] == ["0", "2"]
    assert all(request.url.params["limit"] == "2" for request in requests)
    assert offers[2].employment_type is EmploymentType.CONTRACT
    assert offers[2].remote_policy is RemotePolicy.HYBRID


def test_lever_max_jobs_stops_fetching_at_requested_limit():
    requests = []
    page = fixture("lever_jobs_page_one.json")
    client = make_client(lambda req: (requests.append(req), httpx.Response(200, json=page))[1])
    connector = LeverConnector("exampleco", max_jobs=1, client=client)
    try:
        offers = connector.fetch_jobs()
    finally:
        client.close()
    assert len(offers) == 1
    assert len(requests) == 1
    assert requests[0].url.params["limit"] == "1"


def test_lever_uses_global_api_by_default_and_falls_back_to_html_description():
    item = fixture("lever_jobs_page_two.json")[0]
    item.pop("descriptionPlain")
    item["description"] = "<p>Build and maintain internal tools.</p>"
    requests = []
    client = make_client(lambda req: (requests.append(req), httpx.Response(200, json=[item]))[1])
    connector = LeverConnector("sample-site", client=client)
    try:
        (offer,) = connector.fetch_jobs()
    finally:
        client.close()
    assert requests[0].url.host == "api.lever.co"
    assert offer.description == "Build and maintain internal tools."
    assert offer.company_name is None


def test_lever_http_error_invalid_json_and_malformed_payload_are_reported():
    client = make_client(lambda _request: httpx.Response(404, json={"error": "missing"}))
    connector = LeverConnector("missing", client=client)
    try:
        with pytest.raises(LeverConnectorError, match="HTTP 404"):
            connector.fetch_jobs()
    finally:
        client.close()

    client = make_client(lambda _request: httpx.Response(200, content=b"not json"))
    connector = LeverConnector("exampleco", client=client)
    try:
        with pytest.raises(LeverConnectorError, match="invalid JSON"):
            connector.fetch_jobs()
    finally:
        client.close()

    client = make_client(lambda _request: httpx.Response(200, json={"data": []}))
    connector = LeverConnector("exampleco", client=client)
    try:
        with pytest.raises(LeverConnectorError, match="JSON list"):
            connector.fetch_jobs()
    finally:
        client.close()


def test_lever_constructor_rejects_invalid_region_page_size_and_limit():
    with pytest.raises(ValueError, match="region"):
        LeverConnector("exampleco", region="private")
    with pytest.raises(ValueError, match="page_size"):
        LeverConnector("exampleco", page_size=101)
    with pytest.raises(ValueError, match="max_jobs"):
        LeverConnector("exampleco", max_jobs=0)


def test_lever_description_includes_lists_and_closing_sections():
    item = fixture("lever_jobs_page_two.json")[0]
    item["descriptionPlain"] = "We build insurance products."
    item["lists"] = [
        {"text": "What you'll do", "content": "<li>Design REST APIs</li><li>Own services end to end</li>"},
        {"text": "Requirements", "content": "<li>3+ years of experience with Java</li>"},
        "not-a-section",
    ]
    item["additionalPlain"] = "Hybrid in Madrid, 2 days per week."
    client = make_client(lambda req: httpx.Response(200, json=[item]))
    connector = LeverConnector("sample-site", client=client)
    try:
        (offer,) = connector.fetch_jobs()
    finally:
        client.close()

    description = offer.description
    assert description.startswith("We build insurance products.")
    assert "What you'll do" in description and "Design REST APIs" in description
    assert "Requirements" in description and "3+ years of experience with Java" in description
    assert description.endswith("Hybrid in Madrid, 2 days per week.")
    assert description.index("Design REST APIs") < description.index("Requirements")


def test_lever_description_without_lists_is_unchanged():
    item = fixture("lever_jobs_page_two.json")[0]
    item.pop("lists", None)
    item.pop("additional", None)
    item.pop("additionalPlain", None)
    client = make_client(lambda req: httpx.Response(200, json=[item]))
    connector = LeverConnector("sample-site", client=client)
    try:
        (offer,) = connector.fetch_jobs()
    finally:
        client.close()

    assert offer.description == item["descriptionPlain"]
