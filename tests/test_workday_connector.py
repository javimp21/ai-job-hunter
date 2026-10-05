from __future__ import annotations

import json

import httpx
import pytest

from ai_job_hunter.connectors import JobConnector, WorkdayConnector, WorkdayConnectorError, build_job_connectors
from ai_job_hunter.domain.normalized_job import EmploymentType, RemoteEligibility, RemotePolicy
from ai_job_hunter.job_sources import JobSourcesConfig

HOST = "https://acme.wd3.myworkdayjobs.com"


def posting(n: int, title: str | None = None) -> dict:
    return {
        "title": title or f"Engineer {n}",
        "externalPath": f"/job/Madrid/Engineer-{n}_JR{n}",
        "locationsText": "Madrid",
        "postedOn": "Posted 3 Days Ago",
        "bulletFields": [f"JR{n}"],
    }


DETAIL = {
    "jobPostingInfo": {
        "jobReqId": "JR1",
        "title": "Engineer 1",
        "jobDescription": "<p>Build <b>APIs</b></p><ul><li>Python</li></ul>",
        "location": "Madrid, Spain",
        "timeType": "Full time",
        "remoteType": "Hybrid",
        "startDate": "2026-12-01",
        "country": {"descriptor": "Spain"},
    }
}


def make(handler, **kwargs):
    client = httpx.Client(transport=httpx.MockTransport(handler))
    kwargs.setdefault("request_delay", 0)
    kwargs.setdefault("target_countries_only", False)  # pagination tests; the country filter has its own tests
    return WorkdayConnector("acme/Careers", region="wd3", client=client, **kwargs), client


def paged_handler(total: int, requests: list):
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            body = json.loads(request.content)
            assert body["limit"] == 20 and body["searchText"] == "" and body["appliedFacets"] == {}
            offset = body["offset"]
            page = [posting(n) for n in range(offset + 1, min(offset + 20, total) + 1)]
            # Workday only reports the total on the first page.
            return httpx.Response(200, json={"total": total if offset == 0 else 0, "jobPostings": page})
        return httpx.Response(200, json=DETAIL)

    return handler


def test_fetch_normalizes_posting_with_detail():
    requests: list = []
    connector, client = make(paged_handler(1, requests), company_name="Acme Bank")
    try:
        assert isinstance(connector, JobConnector)
        (job,) = connector.fetch_jobs()
    finally:
        client.close()

    assert [(r.method, str(r.url)) for r in requests] == [
        ("POST", f"{HOST}/wday/cxs/acme/Careers/jobs"),
        ("GET", f"{HOST}/wday/cxs/acme/Careers/job/Madrid/Engineer-1_JR1"),
    ]
    assert job.provider == "workday"
    assert job.external_id == "JR1"
    assert job.company_name == "Acme Bank"
    assert job.source_url == job.apply_url == f"{HOST}/Careers/job/Madrid/Engineer-1_JR1"
    assert job.description == "Build APIs\nPython"
    assert job.location == "Madrid, Spain"
    assert job.employment_type is EmploymentType.FULL_TIME
    assert job.remote_policy is RemotePolicy.HYBRID
    assert job.remote_eligibility is RemoteEligibility.UNKNOWN
    # "Posted 3 Days Ago" becomes an approximate publication date (day precision).
    assert job.published_at is not None and (job.discovered_at - job.published_at).days in (3, 4)
    assert job.raw_metadata["posted_on"] == "Posted 3 Days Ago"


def test_pagination_uses_first_page_total_and_caps_with_max_jobs():
    requests: list = []
    connector, client = make(paged_handler(45, requests), detail_filter=lambda _t: False)
    try:
        jobs = connector.fetch_jobs()
    finally:
        client.close()
    assert len(jobs) == 45
    assert [json.loads(r.content)["offset"] for r in requests] == [0, 20, 40]
    assert jobs[0].description is None and jobs[0].external_id == "JR1"  # list-only fallback

    requests.clear()
    connector, client = make(paged_handler(45, requests), max_jobs=25, detail_filter=lambda _t: False)
    try:
        assert len(connector.fetch_jobs()) == 25
    finally:
        client.close()
    assert len(requests) == 2


def test_detail_filter_skips_detail_requests_and_withdrawn_postings_degrade():
    requests: list = []

    def handler(request):
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(200, json={"total": 2, "jobPostings": [posting(1, "Backend Engineer"), posting(2, "Teller")]})
        return httpx.Response(404)

    connector, client = make(handler, detail_filter=lambda title: "Engineer" in title)
    try:
        jobs = connector.fetch_jobs()
    finally:
        client.close()
    assert [j.title for j in jobs] == ["Backend Engineer", "Teller"]
    assert sum(r.method == "GET" for r in requests) == 1
    assert jobs[0].description is None and jobs[0].remote_policy is None


def test_unknown_work_mode_and_time_type_stay_none():
    detail = {"jobPostingInfo": {"remoteType": "Flexible", "timeType": "Weird", "jobDescription": 5}}

    def handler(request):
        if request.method == "POST":
            return httpx.Response(200, json={"total": 1, "jobPostings": [posting(1)]})
        return httpx.Response(200, json=detail)

    connector, client = make(handler)
    try:
        (job,) = connector.fetch_jobs()
    finally:
        client.close()
    assert job.remote_policy is None and job.employment_type is None and job.description is None
    assert job.external_id == "JR1"


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(500),
        httpx.Response(200, content=b"not json"),
        httpx.Response(200, json=[]),
        httpx.Response(200, json={"total": 1, "jobPostings": "x"}),
        httpx.Response(200, json={"total": "1", "jobPostings": []}),
        httpx.Response(200, json={"total": 1, "jobPostings": [1]}),
        httpx.Response(200, json={"total": 1, "jobPostings": [{"title": "T", "externalPath": "https://evil.example/job/x"}]}),
        httpx.Response(200, json={"total": 1, "jobPostings": [{"title": "T", "externalPath": "/job/../../admin"}]}),
        httpx.Response(200, content=b"{" + b" " * (5 * 1024 * 1024 + 1)),
    ],
)
def test_bad_responses_raise_connector_error(response):
    connector, client = make(lambda _r: response)
    try:
        with pytest.raises(WorkdayConnectorError):
            connector.fetch_jobs()
    finally:
        client.close()


def test_network_error_and_detail_server_error_are_connector_errors():
    def boom(_request):
        raise httpx.ConnectError("down")

    connector, client = make(boom)
    with pytest.raises(WorkdayConnectorError, match="Could not reach"):
        connector.fetch_jobs()
    client.close()

    def handler(request):
        if request.method == "POST":
            return httpx.Response(200, json={"total": 1, "jobPostings": [posting(1)]})
        return httpx.Response(503)

    connector, client = make(handler)
    with pytest.raises(WorkdayConnectorError, match="HTTP 503"):
        connector.fetch_jobs()
    client.close()


def test_page_cap_stops_runaway_pagination():
    requests: list = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"total": 10**9, "jobPostings": [posting(1)]})

    connector, client = make(handler, detail_filter=lambda _t: False)
    try:
        connector.fetch_jobs()
    finally:
        client.close()
    assert len(requests) == 500


@pytest.mark.parametrize(
    ("identifier", "region"),
    [("acme", "wd3"), ("acme/", "wd3"), ("a.b/Site", "wd3"), ("acme/Site/x", "wd3"), ("acme/Site", "eu"), ("acme/Site", "wd3.evil.com"), ("acme/Site", "")],
)
def test_invalid_identifier_or_region_is_rejected(identifier, region):
    with pytest.raises(ValueError):
        WorkdayConnector(identifier, region=region)


def test_factory_builds_workday_and_spec_requires_region():
    config = JobSourcesConfig.model_validate(
        {"sources": [{"provider": "workday", "identifier": "Acme/Careers", "region": "WD3", "max_jobs": 50}]}
    )
    (connector,) = build_job_connectors(config)
    try:
        assert isinstance(connector, WorkdayConnector)
        assert (connector.tenant, connector.site, connector.region, connector.max_jobs) == ("acme", "Careers", "wd3", 50)
    finally:
        connector.close()
    for source in (
        {"provider": "workday", "identifier": "acme/Careers"},
        {"provider": "workday", "identifier": "acme", "region": "wd3"},
        {"provider": "workday", "identifier": "acme/Careers", "region": "de"},
    ):
        with pytest.raises(ValueError):
            JobSourcesConfig.model_validate({"sources": [source]})


SPAIN_FACETS = [
    {
        "facetParameter": "locationMainGroup",
        "values": [
            {"facetParameter": "locationCountry", "values": [
                {"descriptor": "Spain", "id": "es-id", "count": 3},
                {"descriptor": "Mexico", "id": "mx-id", "count": 9},
            ]},
            {"facetParameter": "locationRegionStateProvince", "values": [
                {"descriptor": "Madrid", "id": "mad-id", "count": 2},
            ]},
        ],
    },
    {"facetParameter": "jobFamily", "values": [{"descriptor": "Spain Ops", "id": "x", "count": 1}]},
]


def facet_handler(facets, requests, total=3):
    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            body = json.loads(request.content)
            page = [posting(n) for n in range(body["offset"] + 1, min(body["offset"] + 20, total) + 1)]
            return httpx.Response(200, json={"total": total if body["offset"] == 0 else 0, "jobPostings": page, "facets": facets})
        return httpx.Response(200, json=DETAIL)

    return handler


def test_target_countries_apply_the_country_facet():
    requests = []
    connector, _ = make(facet_handler(SPAIN_FACETS, requests), target_countries_only=True, detail_filter=lambda title: False)

    jobs = connector.fetch_jobs()

    assert len(jobs) == 3
    bodies = [json.loads(r.content) for r in requests if r.method == "POST"]
    assert bodies[0]["appliedFacets"] == {}
    assert bodies[1]["appliedFacets"] == {"locationCountry": ["es-id"]}


def test_target_countries_fall_back_to_locations_and_skip_sites_without_them():
    places = [{"facetParameter": "locations", "values": [
        {"descriptor": "Madrid (Hubs Spain)", "id": "hub", "count": 1},
        {"descriptor": "London", "id": "ldn", "count": 5},
    ]}]
    requests = []
    make(facet_handler(places, requests), target_countries_only=True, detail_filter=lambda title: False)[0].fetch_jobs()
    assert json.loads(requests[1].content)["appliedFacets"] == {"locations": ["hub"]}

    abroad = [{"facetParameter": "locations", "values": [{"descriptor": "London", "id": "ldn", "count": 5}]}]
    requests = []
    assert make(facet_handler(abroad, requests), target_countries_only=True)[0].fetch_jobs() == []
    assert len(requests) == 1


def test_target_countries_include_the_preferred_relocation_countries():
    facets = [{"facetParameter": "locationCountry", "values": [
        {"descriptor": "Spain", "id": "es", "count": 1},
        {"descriptor": "Netherlands, The", "id": "nl", "count": 1},
        {"descriptor": "Switzerland", "id": "ch", "count": 1},
        {"descriptor": "Ireland", "id": "ie", "count": 1},
        {"descriptor": "Luxembourg", "id": "lu", "count": 1},
        {"descriptor": "Northern Ireland Office", "id": "x", "count": 1},
        {"descriptor": "Germany", "id": "de", "count": 9},
    ]}]
    requests = []
    make(facet_handler(facets, requests), target_countries_only=True, detail_filter=lambda title: False)[0].fetch_jobs()
    assert json.loads(requests[1].content)["appliedFacets"] == {"locationCountry": ["es", "nl", "ch", "ie", "lu"]}

    places = [{"facetParameter": "locations", "values": [
        {"descriptor": "Zurich, Switzerland", "id": "zrh", "count": 1},
        {"descriptor": "Dublin 2", "id": "dub", "count": 1},
        {"descriptor": "Berlin", "id": "ber", "count": 4},
    ]}]
    requests = []
    make(facet_handler(places, requests), target_countries_only=True, detail_filter=lambda title: False)[0].fetch_jobs()
    assert json.loads(requests[1].content)["appliedFacets"] == {"locations": ["zrh", "dub"]}


@pytest.mark.parametrize(
    ("text", "days"),
    [("Posted Today", 0), ("Posted Yesterday", 1), ("Posted 3 Days Ago", 3), ("Posted 30+ Days Ago", 31), ("soon", None)],
)
def test_posted_on_text_becomes_an_approximate_publication_date(text, days):
    from datetime import UTC, datetime, timedelta

    from ai_job_hunter.connectors.workday import _posted_on

    now = datetime(2026, 10, 4, 15, 30, tzinfo=UTC)
    expected = None if days is None else datetime(2026, 10, 4, tzinfo=UTC) - timedelta(days=days)
    assert _posted_on(text, now) == expected
