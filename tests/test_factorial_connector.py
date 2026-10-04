from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from ai_job_hunter.candidates.prefilter import title_may_be_relevant
from ai_job_hunter.connectors import FactorialConnector, FactorialConnectorError, JobConnector
from ai_job_hunter.domain.normalized_job import EmploymentType, RemoteEligibility, RemotePolicy

FIXTURES = Path(__file__).parent / "fixtures"
LISTING = (FIXTURES / "factorial_listing.html").read_text(encoding="utf-8")
DETAIL = (FIXTURES / "factorial_detail.html").read_text(encoding="utf-8")
ROBOTS_ALLOW = "User-agent: *\nAllow: /\n"


def make_connector(*, routes=None, requests=None, sleeps=None, **kwargs):
    """Serve ``routes`` (path -> (status, body)); anything else is a 404. Records request paths."""

    routes = {"/robots.txt": (200, ROBOTS_ALLOW), "/": (200, LISTING), **(routes or {})}

    def handler(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(request)
        status, body = routes.get(request.url.path, (404, ""))
        return httpx.Response(status, content=body.encode("utf-8"), headers={"content-type": "text/html; charset=utf-8"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    kwargs.setdefault("sleep", (lambda seconds: sleeps.append(seconds)) if sleeps is not None else (lambda _s: None))
    return FactorialConnector("example", client=client, **kwargs), client


def test_listing_cards_are_parsed_from_explicit_fields_only():
    requests: list[httpx.Request] = []
    connector, client = make_connector(
        requests=requests, detail_filter=lambda _title: False, company_name="Example Co"
    )
    assert isinstance(connector, JobConnector)
    jobs = connector.fetch_jobs()
    client.close()

    assert [job.title for job in jobs] == ["AI Engineer", "Senior Backend Engineer & Platform", "Sales Representative"]
    # robots.txt plus one listing request; no detail request when the filter rejects every title.
    assert [request.url.path for request in requests] == ["/robots.txt", "/"]
    first, second, third = jobs
    assert first.provider == "factorial" and first.company_name == "Example Co"
    assert first.external_id == "100200"
    assert first.source_url == first.canonical_url == first.apply_url == (
        "https://example.factorialhr.com/job_posting/ai-engineer-100200"
    )
    assert first.location == "Madrid"
    assert first.remote_policy is RemotePolicy.HYBRID
    assert second.remote_policy is RemotePolicy.REMOTE
    # A remote work mode never states from which countries remote work is allowed.
    assert second.remote_eligibility is RemoteEligibility.UNKNOWN
    assert third.remote_policy is None  # no work-mode cell and data-is-remote=false: unknown stays unknown
    assert third.employment_type is None and third.description is None and third.published_at is None
    assert first.raw_metadata["team"] == "Technology"
    assert first.raw_metadata["workMode"] == "Hybrid"
    assert first.raw_metadata["contractType"] == "indefinite"
    assert first.raw_metadata["detailFetched"] is False
    assert third.raw_metadata["contractType"] is None and third.raw_metadata["workMode"] is None


@pytest.mark.parametrize(("label", "policy"), [("Híbrido", RemotePolicy.HYBRID), ("Presencial", RemotePolicy.ONSITE)])
def test_spanish_work_mode_labels_are_mapped(label, policy):
    listing = LISTING.replace(">Hybrid", f">{label}", 1)
    connector, client = make_connector(routes={"/": (200, listing)}, detail_filter=lambda _title: False)
    first = connector.fetch_jobs()[0]
    client.close()

    assert first.remote_policy is policy
    assert first.raw_metadata["workMode"] == label


def test_duplicate_cards_and_open_application_are_skipped():
    connector, client = make_connector(detail_filter=lambda _title: False)
    jobs = connector.fetch_jobs()
    client.close()
    assert [job.external_id for job in jobs] == ["100200", "100201", "100202"]
    assert all("apply" not in (job.source_url or "").rsplit("/", 1)[-1] for job in jobs)


def test_details_are_fetched_only_for_relevant_titles_with_a_delay():
    requests: list[httpx.Request] = []
    sleeps: list[float] = []
    connector, client = make_connector(
        routes={"/job_posting/ai-engineer-100200": (200, DETAIL), "/job_posting/senior-backend-engineer-100201": (404, "")},
        requests=requests,
        sleeps=sleeps,
        detail_filter=title_may_be_relevant,
        request_delay=0.5,
    )
    jobs = connector.fetch_jobs()
    client.close()

    paths = [request.url.path for request in requests]
    assert paths[:2] == ["/robots.txt", "/"]
    assert "/job_posting/ai-engineer-100200" in paths
    assert "/job_posting/sales-representative-100202" not in paths  # non-target title: no detail request
    assert len(sleeps) == len(requests) - 1 and set(sleeps) == {0.5}

    ai = jobs[0]
    assert ai.description == "About us\nWe build reliable AI systems.\nPython\nLLMs\nApply with your CV."
    assert "Cookie" not in ai.description and "tracking" not in ai.description
    assert ai.location == "Madrid, Madrid, Spain"  # the detail page states the full location
    assert ai.employment_type is EmploymentType.FULL_TIME  # first explicit schedule wins
    assert ai.raw_metadata["detailFetched"] is True
    # A posting withdrawn between list and detail keeps its listing fields.
    assert jobs[1].description is None and jobs[1].raw_metadata["detailFetched"] is False


def test_detail_requests_are_capped_per_run():
    requests: list[httpx.Request] = []
    connector, client = make_connector(
        routes={
            "/job_posting/ai-engineer-100200": (200, DETAIL),
            "/job_posting/senior-backend-engineer-100201": (200, DETAIL),
            "/job_posting/sales-representative-100202": (200, DETAIL),
        },
        requests=requests,
        max_details=1,
    )
    jobs = connector.fetch_jobs()
    client.close()
    assert sum(1 for request in requests if request.url.path.startswith("/job_posting/")) == 1
    assert [job.raw_metadata["detailFetched"] for job in jobs] == [True, False, False]


def test_max_jobs_limits_the_cards_returned():
    connector, client = make_connector(max_jobs=1, detail_filter=lambda _title: False)
    jobs = connector.fetch_jobs()
    client.close()
    assert len(jobs) == 1


def test_robots_disallow_stops_before_the_listing_request():
    requests: list[httpx.Request] = []
    connector, client = make_connector(
        routes={"/robots.txt": (200, "User-agent: *\nDisallow: /\n")}, requests=requests
    )
    with pytest.raises(FactorialConnectorError, match="robots.txt disallows"):
        connector.fetch_jobs()
    client.close()
    assert [request.url.path for request in requests] == ["/robots.txt"]


def test_robots_disallowing_detail_pages_keeps_listing_fields_only():
    requests: list[httpx.Request] = []
    connector, client = make_connector(
        routes={"/robots.txt": (200, "User-agent: *\nDisallow: /job_posting/\n"), "/job_posting/ai-engineer-100200": (200, DETAIL)},
        requests=requests,
    )
    jobs = connector.fetch_jobs()
    client.close()
    assert len(jobs) == 3 and all(job.description is None for job in jobs)
    assert [request.url.path for request in requests] == ["/robots.txt", "/"]


def test_missing_robots_is_allowed_but_other_robots_errors_fail_closed():
    connector, client = make_connector(routes={"/robots.txt": (404, "")}, detail_filter=lambda _title: False)
    assert len(connector.fetch_jobs()) == 3
    client.close()
    connector, client = make_connector(routes={"/robots.txt": (403, "")})
    with pytest.raises(FactorialConnectorError, match="HTTP 403"):
        connector.fetch_jobs()
    client.close()


def test_region_selects_the_host():
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.host)
        return httpx.Response(200, content=(ROBOTS_ALLOW if request.url.path == "/robots.txt" else "<html></html>").encode())

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with FactorialConnector("Example", region="es", client=client, sleep=lambda _s: None) as connector:
        assert connector.base_url == "https://example.factorial.es"
        assert connector.fetch_jobs() == []
    assert set(seen) == {"example.factorial.es"}
    client.close()


def test_cards_pointing_to_another_host_are_rejected():
    foreign = LISTING.replace("https://example.factorialhr.com/job_posting/ai-engineer-100200", "https://evil.example/job_posting/ai-engineer-100200", 1)
    connector, client = make_connector(routes={"/": (200, foreign)})
    with pytest.raises(FactorialConnectorError, match="does not match"):
        connector.fetch_jobs()
    client.close()


@pytest.mark.parametrize(
    ("status", "message"),
    [(500, "HTTP 500"), (302, "redirected"), (200, "too large")],
)
def test_http_and_size_errors_are_safe(status, message):
    body = "x" * (3 * 1024 * 1024) if message == "too large" else ""
    connector, client = make_connector(routes={"/": (status, body)})
    with pytest.raises(FactorialConnectorError, match=message) as excinfo:
        connector.fetch_jobs()
    client.close()
    assert "example.factorialhr.com" not in str(excinfo.value)


def test_transport_errors_do_not_leak_the_url():
    def handler(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom https://example.factorialhr.com/")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(FactorialConnectorError, match="ConnectError") as excinfo:
        FactorialConnector("example", client=client, sleep=lambda _s: None).fetch_jobs()
    client.close()
    assert "factorialhr" not in str(excinfo.value)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"company": " "},
        {"company": "a.b"},
        {"company": "ok", "region": "de"},
        {"company": "ok", "max_jobs": 0},
        {"company": "ok", "max_details": -1},
        {"company": "ok", "request_delay": -1},
        {"company": "ok", "timeout": 0},
    ],
)
def test_constructor_validates_arguments(kwargs):
    with pytest.raises(ValueError):
        FactorialConnector(**kwargs)
