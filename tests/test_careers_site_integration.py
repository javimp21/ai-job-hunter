"""Careers-site and Amazon connectors wired into discovery, leads, monitored sources and refresh."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from ai_job_hunter.ats_discovery import discover_ats_url
from ai_job_hunter.company_leads import CompanyLeadInput, CompanyLeadsConfig, import_company_leads, resolve_company_leads
from ai_job_hunter.connectors import AmazonJobsConnector, AmazonJobsConnectorError, build_job_connectors
from ai_job_hunter.connectors.careers_site import CareersSiteProbe
from ai_job_hunter.domain.company_intelligence import ATSDiscoveryConfidence, ATSProvider, CompanyMonitorTarget
from ai_job_hunter.domain.normalized_job import EmploymentType, NormalizedJob, RemotePolicy
from ai_job_hunter.job_sources import JobSourceSpec, JobSourcesConfig
from ai_job_hunter.models import (
    Company,
    CompanyLead,
    CompanyLeadStatus,
    Job,
    JobSource,
    MonitoredSource,
    MonitoredSourceState,
)
from ai_job_hunter.services import opportunities
from ai_job_hunter.services.monitored_sources import (
    active_monitor_targets,
    mark_closed_postings,
    sync_monitored_sources,
)

FIXTURES = Path(__file__).parent / "fixtures" / "careers_site"
PUBLIC_DNS = lambda _host, _port: ("93.184.216.34",)  # noqa: E731


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda _seconds: None)


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# -- Amazon -------------------------------------------------------------------------------------


def amazon_client(requests: list[httpx.Request], *, robots=(200, "User-agent: *\nDisallow: /internal\n"), search=None):
    payload = search or fixture("amazon_search.json")

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/robots.txt":
            return httpx.Response(robots[0], text=robots[1])
        if request.url.path == "/en/search.json":
            return httpx.Response(200, text=payload, headers={"content-type": "application/json"})
        return httpx.Response(404)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_amazon_reads_the_public_search_limited_to_target_countries_and_software_roles():
    requests: list[httpx.Request] = []
    client = amazon_client(requests)
    sleeps: list[float] = []
    connector = AmazonJobsConnector(client=client, sleep=sleeps.append)
    jobs = connector.fetch_jobs()
    client.close()

    assert [request.url.path for request in requests] == ["/robots.txt", "/en/search.json"]
    query = requests[1].url.params
    assert query.get_list("normalized_country_code[]") == ["ESP", "IRL", "LUX", "NLD", "CHE"]
    assert query.get_list("category[]") == ["software-development"]
    assert query["result_limit"] == "100" and query["offset"] == "0"
    assert sleeps == [1.0]
    # The USA job in the payload is outside the allowed countries and is dropped even though Amazon returned it.
    assert [job.title for job in jobs] == ["Software Dev Engineer I", "Software Dev Engineer Intern"]
    first, second = jobs
    assert first.provider == "amazon_jobs" and first.company_name == "Amazon" and first.external_id == "3141336"
    assert first.source_url == "https://www.amazon.jobs/en/jobs/3141336/software-dev-engineer-i"
    assert first.location == "Madrid, Community of Madrid, ESP"
    assert first.employment_type is EmploymentType.FULL_TIME
    assert first.published_at.isoformat() == "2026-09-22T00:00:00+00:00"
    assert first.description.splitlines()[:2] == ["Build services.", "Own them."]
    assert "Basic qualifications\n- Bachelor's degree" in first.description
    assert first.remote_policy is None  # the payload has no work-mode field
    assert first.raw_metadata["legalEntity"] == "Amazon Spain Services SL"
    assert second.employment_type is EmploymentType.INTERNSHIP and second.location == "IE, D, Dublin"


def test_amazon_pages_until_all_hits_and_honours_max_jobs():
    requests: list[httpx.Request] = []
    pages = {
        "0": {"hits": 150, "jobs": [json.loads(fixture("amazon_search.json"))["jobs"][0]]},
        "100": {"hits": 150, "jobs": [json.loads(fixture("amazon_search.json"))["jobs"][1]]},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, json=pages[request.url.params["offset"]])

    client = httpx.Client(transport=httpx.MockTransport(handler))
    connector = AmazonJobsConnector(client=client, sleep=lambda _s: None)
    assert len(connector.fetch_jobs()) == 2
    assert [r.url.params.get("offset") for r in requests] == [None, "0", "100"]
    limited = AmazonJobsConnector(client=client, max_jobs=1, sleep=lambda _s: None)
    assert len(limited.fetch_jobs()) == 1
    client.close()


@pytest.mark.parametrize("status", [403, 500])
def test_amazon_robots_errors_fail_closed(status):
    requests: list[httpx.Request] = []
    client = amazon_client(requests, robots=(status, ""))
    with pytest.raises(AmazonJobsConnectorError, match=f"HTTP {status}"):
        AmazonJobsConnector(client=client, sleep=lambda _s: None).fetch_jobs()
    client.close()
    assert [r.url.path for r in requests] == ["/robots.txt"]


def test_amazon_robots_disallowing_the_search_is_respected_and_bad_payloads_fail():
    requests: list[httpx.Request] = []
    client = amazon_client(requests, robots=(200, "User-agent: *\nDisallow: /en/search\n"))
    with pytest.raises(AmazonJobsConnectorError, match="disallows"):
        AmazonJobsConnector(client=client, sleep=lambda _s: None).fetch_jobs()
    client.close()

    client = amazon_client([], search="[1, 2]")
    with pytest.raises(AmazonJobsConnectorError, match="unexpected"):
        AmazonJobsConnector(client=client, sleep=lambda _s: None).fetch_jobs()
    client.close()

    with pytest.raises(ValueError):
        AmazonJobsConnector("example.com")
    with pytest.raises(ValueError):
        AmazonJobsConnector(countries=("USA",))


def test_amazon_wiring_in_sources_factory_and_discovery():
    spec = JobSourceSpec(provider="AMAZON_JOBS", identifier="amazon.jobs", company_name="Amazon")
    assert spec.provider == "amazon_jobs"
    with pytest.raises(ValueError):
        JobSourceSpec(provider="amazon_jobs", identifier="other.jobs")
    (connector,) = build_job_connectors(JobSourcesConfig(sources=[spec]))
    assert isinstance(connector, AmazonJobsConnector)
    connector.close()

    found = discover_ats_url("https://www.amazon.jobs/en/")
    assert found.provider is ATSProvider.AMAZON_JOBS and found.identifier == "amazon.jobs" and found.is_supported
    assert discover_ats_url("https://www.amazon.com/jobs").provider is ATSProvider.UNKNOWN


# -- lead discovery -----------------------------------------------------------------------------


def import_lead(session, careers_url: str) -> CompanyLead:
    item = CompanyLeadInput(
        company_name="Acme Robotics",
        website_url="https://acme.test",
        careers_url=careers_url,
        source_type="curated_list",
        source_label="careers_site_2026_10",
    )
    import_company_leads(session, CompanyLeadsConfig(leads=[item]))
    session.flush()
    return session.scalar(select(CompanyLead))


def careers_host_client(*, with_postings: bool) -> tuple[httpx.Client, list[str]]:
    requests: list[str] = []
    page = fixture("job_remote.html") if with_postings else fixture("page_no_posting.html")
    sitemap = (
        "<urlset>"
        "<url><loc>https://careers.acme.test/job/1/Backend-Engineer</loc></url>"
        "<url><loc>https://careers.acme.test/job/2/Platform-Engineer</loc></url>"
        "<url><loc>https://careers.acme.test/job/3/Data-Engineer</loc></url>"
        "</urlset>"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        path = request.url.path
        if path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /\nSitemap: https://careers.acme.test/sitemap.xml\n")
        if path == "/sitemap.xml":
            return httpx.Response(200, text=sitemap, headers={"content-type": "application/xml"})
        if path.startswith("/job/"):
            return httpx.Response(200, text=page, headers={"content-type": "text/html"})
        return httpx.Response(200, text="<html><body>Careers at Acme</body></html>", headers={"content-type": "text/html"})

    return httpx.Client(transport=httpx.MockTransport(handler)), requests


def test_careers_url_with_job_posting_pages_becomes_a_review_source(db_session):
    lead = import_lead(db_session, "https://careers.acme.test/")
    client, requests = careers_host_client(with_postings=True)
    summary = resolve_company_leads(db_session, client=client, host_resolver=PUBLIC_DNS)
    client.close()

    assert summary.count(CompanyLeadStatus.SUPPORTED_ATS) == 1
    assert lead.ats_provider == "CAREERS_SITE" and lead.ats_identifier == "careers.acme.test"
    assert "JobPosting" in lead.resolution_note
    # robots.txt, sitemap and three sampled job pages were read from the careers host only.
    assert [url.split("/", 3)[2] for url in requests].count("careers.acme.test") == len(requests)
    assert sum("/job/" in url for url in requests) == 3

    created = sync_monitored_sources(db_session).created
    assert created == 1
    (source,) = db_session.scalars(select(MonitoredSource)).all()
    assert source.provider == "CAREERS_SITE" and source.identifier == "careers.acme.test"
    assert source.state == MonitoredSourceState.REVIEW_SOURCE.value  # waits for the daily auto-activation
    assert source.careers_url == "https://careers.acme.test/"
    assert active_monitor_targets(db_session) == []  # not fetched until active


def test_careers_url_without_job_postings_stays_unsupported(db_session):
    lead = import_lead(db_session, "https://careers.acme.test/")
    client, _requests = careers_host_client(with_postings=False)
    resolve_company_leads(db_session, client=client, host_resolver=PUBLIC_DNS)
    client.close()
    assert lead.status == CompanyLeadStatus.RESOLVED.value and lead.ats_provider is None
    assert sync_monitored_sources(db_session).created == 0


def test_known_ats_hosts_are_never_probed(db_session):
    import_lead(db_session, "https://boards.greenhouse.io/acme")

    def never(_url, _client):
        pytest.fail("a known ATS URL must not trigger a careers-site probe")

    resolve_company_leads(db_session, host_resolver=PUBLIC_DNS, careers_probe=never)
    assert db_session.scalar(select(CompanyLead)).ats_provider == "GREENHOUSE"


def test_probe_is_not_run_on_private_hosts_and_errors_do_not_fail_the_lead(db_session):
    import_lead(db_session, "https://careers.acme.test/")
    client, _requests = careers_host_client(with_postings=True)

    def exploding(_url, _client):
        raise ValueError("boom")

    resolve_company_leads(
        db_session, client=client, host_resolver=PUBLIC_DNS, careers_probe=exploding
    )
    client.close()
    assert db_session.scalar(select(CompanyLead)).status == CompanyLeadStatus.RESOLVED.value

    lead = db_session.scalar(select(CompanyLead))
    lead.status = CompanyLeadStatus.NEW.value
    db_session.flush()
    client, _requests = careers_host_client(with_postings=True)
    resolve_company_leads(
        db_session,
        client=client,
        host_resolver=lambda _h, _p: ("10.0.0.5",),
        careers_probe=lambda *_: pytest.fail("private hosts are blocked before any probe"),
    )
    client.close()
    assert db_session.scalar(select(CompanyLead)).status == CompanyLeadStatus.FAILED.value


def test_injected_probe_result_is_persisted_with_its_verification(db_session):
    import_lead(db_session, "https://careers.acme.test/")
    client, _requests = careers_host_client(with_postings=True)
    probe = CareersSiteProbe("careers.acme.test", job_urls=40, sampled=3, postings=2)
    resolve_company_leads(
        db_session, client=client, host_resolver=PUBLIC_DNS, careers_probe=lambda _url, _client: probe
    )
    client.close()
    company = db_session.scalar(select(Company))
    from ai_job_hunter.domain.company_intelligence import company_facts

    (discovery,) = company_facts(company).ats_discoveries
    assert discovery.provider is ATSProvider.CAREERS_SITE and discovery.identifier == "careers.acme.test"
    assert discovery.confidence is ATSDiscoveryConfidence.DIRECT_URL_PATTERN
    assert "2 of 3 sampled" in discovery.evidence and discovery.is_supported


# -- monitoring ---------------------------------------------------------------------------------


def add_careers_source(session) -> tuple[Company, MonitoredSource]:
    company = Company(name="Acme Robotics", website_url="https://acme.test")
    session.add(company)
    session.flush()
    source = MonitoredSource(
        company_id=company.id,
        provider="CAREERS_SITE",
        identifier="careers.example.com",
        identifier_key="careers.example.com",
        careers_url="https://careers.example.com/",
        state=MonitoredSourceState.ACTIVE.value,
        origin="career_url",
    )
    session.add(source)
    session.commit()
    return company, source


def add_job(session, company: Company, url: str) -> JobSource:
    job = Job(title="Stored Engineer", company_id=company.id)
    session.add(job)
    session.flush()
    row = JobSource(job_id=job.id, provider="careers_site", external_id=url.removeprefix("https://"), canonical_url=url)
    session.add(row)
    session.commit()
    return row


def test_active_careers_site_targets_carry_the_urls_already_stored(db_session):
    company, _source = add_careers_source(db_session)
    add_job(db_session, company, "https://careers.example.com/en/job/101/Junior-Software-Engineer")
    (target,) = active_monitor_targets(db_session)
    assert target.provider is ATSProvider.CAREERS_SITE
    assert target.known_urls == frozenset({"https://careers.example.com/en/job/101/Junior-Software-Engineer"})


def test_refresh_fetches_only_unseen_pages_and_never_closes_known_postings(db_session):
    company, _source = add_careers_source(db_session)
    stored = add_job(db_session, company, "https://careers.example.com/en/job/101/Junior-Software-Engineer")
    (target,) = active_monitor_targets(db_session)
    requests: list[httpx.Request] = []

    table = {
        "/robots.txt": (200, fixture("robots.txt")),
        "/sitemap_index.xml": (200, fixture("sitemap_index.xml")),
        "/sitemaps/jobs1.xml": (200, fixture("sitemap_jobs.xml")),
        "/en/job/105/Remote-Backend-Engineer": (200, fixture("job_remote.html")),
        "/en/job/106/Graph-Engineer": (200, fixture("job_graph.html")),
    }

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        status, body = table.get(request.url.path, (200, fixture("page_no_posting.html")))
        return httpx.Response(status, text=body)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        offers, failures = opportunities._fetch_targets([target], max_jobs_per_company=50, client=client)
    finally:
        client.close()

    assert failures == []
    assert "/en/job/101/Junior-Software-Engineer" not in {request.url.path for request in requests}
    assert {offer.title for offer, _target in offers} >= {"Remote Backend Engineer", "Graph Engineer"}

    # The run returned only unseen pages, so the stored posting must not look "gone from the board".
    closed = mark_closed_postings(
        db_session, [target], offers, [], seen_source_ids=set(), max_jobs_per_company=50
    )
    assert closed == 0
    db_session.refresh(stored)
    assert stored.closed_at is None


def test_job_sources_json_accepts_careers_site_and_amazon(tmp_path):
    from ai_job_hunter.job_sources import load_job_sources

    path = tmp_path / "sources.json"
    path.write_text(
        json.dumps(
            {
                "sources": [
                    {"provider": "careers_site", "identifier": "careers.cisco.com/global/en", "company_name": "Cisco"},
                    {"provider": "amazon_jobs", "identifier": "amazon.jobs", "company_name": "Amazon"},
                ]
            }
        ),
        encoding="utf-8",
    )
    assert [source.provider for source in load_job_sources(path).sources] == ["careers_site", "amazon_jobs"]


def test_normalized_job_contract_for_careers_site_jobs_is_valid():
    job = NormalizedJob(provider="careers_site", title="Engineer", remote_policy=RemotePolicy.REMOTE)
    assert job.remote_eligibility.value == "UNKNOWN"
    assert CompanyMonitorTarget.model_fields["known_urls"].default == frozenset()


def test_boards_after_the_fetch_deadline_are_skipped_as_failed_not_closed(db_session, monkeypatch):
    add_careers_source(db_session)
    (target,) = active_monitor_targets(db_session)
    monkeypatch.setattr(opportunities, "FETCH_DEADLINE_SECONDS", -1)
    client = httpx.Client(transport=httpx.MockTransport(lambda request: pytest.fail("no request after the deadline")))
    try:
        offers, failures = opportunities._fetch_targets([target], max_jobs_per_company=50, client=client)
    finally:
        client.close()

    assert offers == []
    assert [(f.company, f.error_type) for f in failures] == [(target.company_name, "FetchDeadlineReached")]
