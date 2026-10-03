from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest

from ai_job_hunter.connectors import (
    JobConnector,
    SmartRecruitersConnector,
    SmartRecruitersConnectorError,
)
from ai_job_hunter.domain.normalized_job import EmploymentType, RemoteEligibility, RemotePolicy


def posting(posting_id: str, name: str, **extra) -> dict:
    return {
        "id": posting_id,
        "name": name,
        "company": {"identifier": "example", "name": "Example Inc"},
        "releasedDate": "2026-09-09T09:43:26.403Z",
        "location": {"city": "Madrid", "country": "es", "remote": False, "fullLocation": "Madrid, Spain"},
        "typeOfEmployment": {"id": "permanent", "label": "Full-time"},
        **extra,
    }


DETAIL = {
    "jobAd": {
        "sections": {
            "additionalInformation": {"title": "Extra", "text": "<p>Benefits</p>"},
            "companyDescription": {"title": "Company", "text": "<p>About us</p>"},
            "jobDescription": {"title": "Job", "text": "<p>Build <b>things</b></p>"},
            "qualifications": {"title": "Qual", "text": "<ul><li>Python</li></ul>"},
        }
    }
}


class Fake:
    """Serves list pages and details from in-memory postings."""

    def __init__(self, postings: list[dict]) -> None:
        self.postings = postings
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path.endswith("/postings"):
            limit = int(request.url.params["limit"])
            offset = int(request.url.params["offset"])
            return httpx.Response(
                200,
                json={
                    "offset": offset,
                    "limit": limit,
                    "totalFound": len(self.postings),
                    "content": self.postings[offset : offset + limit],
                },
            )
        posting_id = path.rsplit("/", 1)[1]
        if any(item["id"] == posting_id for item in self.postings):
            return httpx.Response(200, json=DETAIL)
        return httpx.Response(404, json={})


def make(handler, **kwargs):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    sleeps: list[float] = []
    kwargs.setdefault("sleep", sleeps.append)
    return SmartRecruitersConnector("Example", client=client, **kwargs), client, sleeps


def test_normalizes_posting_with_detail_sections():
    fake = Fake(
        [
            posting("1", "Backend Engineer", location={"city": "X", "country": "pl", "remote": True, "fullLocation": "Poland, Remote"}),
            posting("2", "Hybrid Dev", location={"city": "Lisbon", "country": "pt", "hybrid": True}),
        ]
    )
    connector, client, sleeps = make(fake, company_name="Example Co")
    try:
        assert isinstance(connector, JobConnector)
        first, second = connector.fetch_jobs()
    finally:
        client.close()

    assert first.provider == "smartrecruiters"
    assert first.external_id == "1"
    assert first.company_name == "Example Co"
    assert first.source_url == "https://jobs.smartrecruiters.com/Example/1"
    assert first.location == "Poland, Remote"
    assert first.remote_policy is RemotePolicy.REMOTE
    assert first.remote_eligibility is RemoteEligibility.UNKNOWN
    assert first.employment_type is EmploymentType.FULL_TIME
    assert first.published_at == datetime(2026, 9, 9, 9, 43, 26, 403000, tzinfo=UTC)
    assert first.description == "About us\n\nBuild things\n\nPython\n\nBenefits"
    assert first.raw_metadata["detail"]["jobAd"]["sections"]["jobDescription"]["title"] == "Job"
    # No fullLocation: city + upper-cased ISO country; hybrid is only set when stated.
    assert second.location == "Lisbon, PT"
    assert second.remote_policy is RemotePolicy.HYBRID
    assert second.company_name == "Example Co"
    # Sequential calls: list + 2 details, delay between each pair of requests.
    assert len(fake.requests) == 3
    assert sleeps == [0.2, 0.2]
    assert all(r.method == "GET" and r.url.host == "api.smartrecruiters.com" for r in fake.requests)


def test_remote_false_stays_unknown():
    connector, client, _ = make(Fake([posting("1", "Dev")]))
    try:
        assert connector.fetch_jobs()[0].remote_policy is None
    finally:
        client.close()


def test_paginates_until_total_found():
    fake = Fake([posting(str(i), f"Role {i}") for i in range(5)])
    connector, client, _ = make(fake, page_size=2, detail_filter=lambda _title: False)
    try:
        jobs = connector.fetch_jobs()
    finally:
        client.close()

    assert [job.external_id for job in jobs] == ["0", "1", "2", "3", "4"]
    offsets = [int(r.url.params["offset"]) for r in fake.requests]
    assert offsets == [0, 2, 4]


def test_max_jobs_bounds_pages_and_details():
    fake = Fake([posting(str(i), f"Role {i}") for i in range(10)])
    connector, client, _ = make(fake, page_size=3, max_jobs=4)
    try:
        jobs = connector.fetch_jobs()
    finally:
        client.close()

    assert len(jobs) == 4
    list_requests = [r for r in fake.requests if r.url.path.endswith("/postings")]
    assert [r.url.params["limit"] for r in list_requests] == ["3", "1"]
    assert len(fake.requests) - len(list_requests) == 4


def test_detail_filter_limits_detail_requests():
    fake = Fake([posting("1", "Backend Engineer"), posting("2", "Sales Manager")])
    seen: list[str] = []

    def accept(title: str) -> bool:
        seen.append(title)
        return "Engineer" in title

    connector, client, _ = make(fake, detail_filter=accept)
    try:
        engineer, sales = connector.fetch_jobs()
    finally:
        client.close()

    assert seen == ["Backend Engineer", "Sales Manager"]
    detail_paths = [r.url.path for r in fake.requests if not r.url.path.endswith("/postings")]
    assert detail_paths == ["/v1/companies/Example/postings/1"]
    assert engineer.description and "Build things" in engineer.description
    assert sales.description is None
    assert "detail" not in sales.raw_metadata


def test_withdrawn_posting_keeps_list_data_without_description():
    class Gone(Fake):
        def __call__(self, request):
            if not request.url.path.endswith("/postings"):
                return httpx.Response(404)
            return super().__call__(request)

    connector, client, _ = make(Gone([posting("1", "Dev")]))
    try:
        (job,) = connector.fetch_jobs()
    finally:
        client.close()
    assert job.description is None


def test_empty_company_returns_no_jobs():
    connector, client, _ = make(Fake([]))
    try:
        assert connector.fetch_jobs() == []
    finally:
        client.close()


def test_errors_do_not_leak_urls():
    connector, client, _ = make(lambda _req: httpx.Response(500))
    try:
        with pytest.raises(SmartRecruitersConnectorError, match="HTTP 500") as error:
            connector.fetch_jobs()
    finally:
        client.close()
    assert "smartrecruiters.com" not in str(error.value)

    def boom(request):
        raise httpx.ConnectError("cannot reach https://api.smartrecruiters.com/v1/x", request=request)

    connector, client, _ = make(boom)
    try:
        with pytest.raises(SmartRecruitersConnectorError) as network_error:
            connector.fetch_jobs()
    finally:
        client.close()
    assert "smartrecruiters.com" not in str(network_error.value)


@pytest.mark.parametrize(
    "body",
    [
        [],
        {"content": "nope", "totalFound": 1},
        {"content": [], "totalFound": "1"},
        {"content": [5], "totalFound": 1},
        {"content": [{"id": "1"}], "totalFound": 1},
    ],
)
def test_malformed_payloads_raise(body):
    connector, client, _ = make(lambda _req: httpx.Response(200, json=body))
    try:
        with pytest.raises(SmartRecruitersConnectorError):
            connector.fetch_jobs()
    finally:
        client.close()


def test_invalid_json_raises():
    connector, client, _ = make(lambda _req: httpx.Response(200, content=b"<html>"))
    try:
        with pytest.raises(SmartRecruitersConnectorError, match="invalid JSON"):
            connector.fetch_jobs()
    finally:
        client.close()


@pytest.mark.parametrize("kwargs", [{"page_size": 0}, {"page_size": 101}, {"max_jobs": 0}, {"request_delay": -1}])
def test_constructor_validation(kwargs):
    with pytest.raises(ValueError):
        SmartRecruitersConnector("example", **kwargs)
    with pytest.raises(ValueError):
        SmartRecruitersConnector("  ")
