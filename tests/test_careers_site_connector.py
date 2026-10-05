from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from ai_job_hunter.candidates.prefilter import title_may_be_relevant
from ai_job_hunter.connectors import CareersSiteConnector, CareersSiteConnectorError, JobConnector, build_job_connectors
from ai_job_hunter.connectors._robots import RobotsRules
from ai_job_hunter.connectors.careers_site import (
    careers_site_board_url,
    careers_site_identifier_from_url,
    job_url_title,
    probe_careers_site,
    split_careers_identifier,
)
from ai_job_hunter.domain.normalized_job import EmploymentType, RemoteEligibility, RemotePolicy, SalaryPeriod
from ai_job_hunter.job_sources import JobSourceSpec, JobSourcesConfig

FIXTURES = Path(__file__).parent / "fixtures" / "careers_site"
HOST = "careers.example.com"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def default_routes() -> dict[str, tuple[int, str, str]]:
    html = "text/html; charset=utf-8"
    xml = "application/xml"
    return {
        "/robots.txt": (200, fixture("robots.txt"), "text/plain"),
        "/sitemap_index.xml": (200, fixture("sitemap_index.xml"), xml),
        "/sitemaps/jobs1.xml": (200, fixture("sitemap_jobs.xml"), xml),
        "/en/job/100/Senior-Platform-Engineer": (200, fixture("page_no_posting.html"), html),
        "/en/job/101/Junior-Software-Engineer": (200, fixture("job_onsite.html"), html),
        "/en/job/102/Data-Engineer-Microdata": (200, fixture("job_microdata.html"), html),
        "/en/job/103/Expired-Role": (200, fixture("job_expired.html"), html),
        "/en/job/104/Listing-With-Two-Postings": (200, fixture("job_two_postings.html"), html),
        "/en/job/105/Remote-Backend-Engineer": (200, fixture("job_remote.html"), html),
        "/en/job/106/Graph-Engineer": (200, fixture("job_graph.html"), html),
        "/en/job/107/Web-Page-Without-Posting": (200, fixture("page_no_posting.html"), html),
    }


def make_connector(identifier: str = HOST, *, routes=None, requests=None, sleeps=None, **kwargs):
    """Serve ``routes`` (path -> (status, body, content type)); anything else is a 404."""

    table = {**default_routes(), **(routes or {})}

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == HOST, f"request left the careers host: {request.url}"
        if requests is not None:
            requests.append(request)
        entry = table.get(request.url.path, (404, "", "text/plain"))
        if callable(entry):
            return entry(request)
        status, body, content_type = entry
        return httpx.Response(status, content=body.encode("utf-8"), headers={"content-type": content_type})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    kwargs.setdefault("sleep", (lambda seconds: sleeps.append(seconds)) if sleeps is not None else (lambda _s: None))
    return CareersSiteConnector(identifier, client=client, **kwargs), client


def by_title(jobs):
    return {job.title: job for job in jobs}


# -- identifiers ------------------------------------------------------------------------


def test_identifier_is_host_plus_path_and_validated():
    assert split_careers_identifier("Careers.Example.com/") == ("careers.example.com", "")
    assert split_careers_identifier("example.com/global/en/") == ("example.com", "/global/en")
    assert careers_site_board_url("example.com/global/en") == "https://example.com/global/en"
    for bad in ("localhost", "10.0.0.1", "example.com/../x", "https://example.com", "example.com/a b", "exa mple.com", ""):
        with pytest.raises(ValueError):
            split_careers_identifier(bad)


def test_identifier_from_url_cuts_job_pages_and_files():
    assert careers_site_identifier_from_url("https://careers.cisco.com/global/en") == "careers.cisco.com/global/en"
    assert careers_site_identifier_from_url("https://www.caixabanktech.com/es/job/junior-java/") == "www.caixabanktech.com/es"
    assert careers_site_identifier_from_url("https://x.example.com/careers/index.html") == "x.example.com/careers"
    assert careers_site_identifier_from_url("https://x.example.com/en/jobs/", host_only=True) == "x.example.com"
    assert careers_site_identifier_from_url("https://user:pw@x.example.com/") is None
    assert careers_site_identifier_from_url("https://x.example.com:8443/") is None
    assert careers_site_identifier_from_url("ftp://x.example.com/") is None


def test_job_url_title_uses_the_slug_only():
    assert job_url_title("https://c.example.com/job/Madrid-Senior-Engineer-MD/1370/") == "Madrid Senior Engineer MD"
    assert job_url_title("https://c.example.com/global/en/job/CISCIS2020960EXTERNAL/Consulting-Engineering-Leader") == (
        "Consulting Engineering Leader"
    )
    assert job_url_title("https://c.example.com/about") == ""


# -- robots.txt ---------------------------------------------------------------------------


def test_robots_rules_support_wildcards_longest_match_and_crawl_delay():
    rules = RobotsRules(fixture("robots.txt"), "AI-Job-Hunter")
    assert rules.crawl_delay == 2
    assert rules.sitemaps == ["http://careers.example.com/sitemap_index.xml", "https://other.example.net/foreign.xml"]
    assert rules.can_fetch("https://careers.example.com/en/job/1/Engineer")
    assert not rules.can_fetch("https://careers.example.com/en/job/110/apply")
    assert not rules.can_fetch("https://careers.example.com/private/x")
    assert rules.can_fetch("https://careers.example.com/private/public/x")  # longer Allow beats Disallow
    blocked = RobotsRules("User-agent: *\nDisallow: /\n", "AI-Job-Hunter")
    assert not blocked.can_fetch("https://careers.example.com/")
    named = RobotsRules("User-agent: ai-job-hunter\nDisallow: /\n\nUser-agent: *\nAllow: /\n", "AI-Job-Hunter")
    assert not named.can_fetch("https://careers.example.com/")
    assert RobotsRules(None, "AI-Job-Hunter").can_fetch("https://careers.example.com/anything")
    anchored = RobotsRules("User-agent: *\nDisallow: /*.pdf$\n", "AI-Job-Hunter")
    assert not anchored.can_fetch("https://c.example.com/a/b.pdf")
    assert anchored.can_fetch("https://c.example.com/a/b.pdf.html")


@pytest.mark.parametrize("status", [401, 403, 500, 503])
def test_robots_errors_other_than_404_fail_closed(status):
    requests: list[httpx.Request] = []
    connector, client = make_connector(routes={"/robots.txt": (status, "", "text/plain")}, requests=requests)
    with pytest.raises(CareersSiteConnectorError, match=f"HTTP {status}"):
        connector.fetch_jobs()
    client.close()
    assert [request.url.path for request in requests] == ["/robots.txt"]  # nothing else was read


def test_robots_served_as_html_is_treated_as_unknown_and_fails_closed():
    connector, client = make_connector(routes={"/robots.txt": (200, "<html><body>challenge</body></html>", "text/html")})
    with pytest.raises(CareersSiteConnectorError, match="not a text file"):
        connector.fetch_jobs()
    client.close()


def test_missing_robots_and_missing_sitemap_mean_allowed_but_empty():
    requests: list[httpx.Request] = []
    connector, client = make_connector(routes={"/robots.txt": (404, "", "text/plain")}, requests=requests)
    assert connector.fetch_jobs() == []
    client.close()
    assert [request.url.path for request in requests] == ["/robots.txt", "/sitemap.xml"]


def test_robots_disallowing_everything_for_us_means_no_job_page_is_fetched():
    requests: list[httpx.Request] = []
    robots = "User-agent: *\nDisallow: /en/\nSitemap: https://careers.example.com/sitemap_index.xml\n"
    connector, client = make_connector(routes={"/robots.txt": (200, robots, "text/plain")}, requests=requests)
    assert connector.fetch_jobs() == []
    client.close()
    assert all(not request.url.path.startswith("/en/") for request in requests)


# -- sitemaps and job selection -----------------------------------------------------------


def test_sitemap_index_is_followed_on_the_same_host_and_job_urls_are_filtered():
    requests: list[httpx.Request] = []
    connector, client = make_connector(requests=requests, max_details=0)
    assert isinstance(connector, JobConnector)
    assert connector.fetch_jobs() == []
    client.close()
    # robots.txt, the declared (http -> https upgraded) index and its same-host child only; the foreign
    # sitemap in robots.txt and the foreign child of the index are never requested.
    assert [request.url.path for request in requests] == ["/robots.txt", "/sitemap_index.xml", "/sitemaps/jobs1.xml"]
    assert all(request.url.scheme == "https" for request in requests)
    # 8 job pages plus /apply and /private, which robots.txt removes later; not the about page, the bare
    # listing, the pdf or the foreign host.
    assert connector.stats["job_urls"] == 10
    assert connector.stats["sitemap_urls"] == 14


def test_default_sitemap_is_used_when_robots_declares_none():
    routes = {
        "/robots.txt": (200, "User-agent: *\nAllow: /\n", "text/plain"),
        "/sitemap.xml": (200, fixture("sitemap_jobs.xml"), "application/xml"),
    }
    requests: list[httpx.Request] = []
    connector, client = make_connector(routes=routes, requests=requests, max_details=0)
    connector.fetch_jobs()
    client.close()
    assert [request.url.path for request in requests] == ["/robots.txt", "/sitemap.xml"]


def test_only_jobs_under_the_identifier_path_are_considered():
    routes = {"/robots.txt": (200, "", "text/plain"), "/sitemap.xml": (200, fixture("sitemap_jobs.xml"), "application/xml")}
    connector, client = make_connector("careers.example.com/en", routes=routes, max_details=0)
    connector.fetch_jobs()
    assert connector.stats["job_urls"] == 9  # /private/... is outside /en
    client.close()
    other, client = make_connector("careers.example.com/fr", routes=routes, max_details=0)
    other.fetch_jobs()
    assert other.stats["job_urls"] == 0
    client.close()


def test_known_urls_are_skipped_and_detail_requests_are_bounded_newest_first():
    requests: list[httpx.Request] = []
    connector, client = make_connector(
        requests=requests,
        known_urls={"https://careers.example.com/en/job/101/Junior-Software-Engineer"},
        max_details=2,
    )
    jobs = connector.fetch_jobs()
    client.close()
    pages = [request.url.path for request in requests if request.url.path.startswith("/en/")]
    # Newest lastmod first: 105 (10-03), 106 (10-02); 101 (10-04) is known and never fetched.
    assert pages == ["/en/job/105/Remote-Backend-Engineer", "/en/job/106/Graph-Engineer"]
    assert [job.title for job in jobs] == ["Remote Backend Engineer", "Graph Engineer"]
    assert connector.stats["known"] == 1


def test_requests_are_spaced_by_the_delay_and_by_a_longer_crawl_delay():
    sleeps: list[float] = []
    connector, client = make_connector(sleeps=sleeps, max_details=2, request_delay=1.0)
    connector.fetch_jobs()
    client.close()
    # robots.txt asks Crawl-delay: 2, which is longer than the 1 s default; no sleep before the first request.
    assert sleeps and set(sleeps) == {2.0}
    assert len(sleeps) == 4  # robots, index, child, 2 pages -> 4 gaps

    sleeps = []
    routes = {"/robots.txt": (200, "User-agent: *\nCrawl-delay: 99\nSitemap: https://careers.example.com/sitemap_index.xml\n", "text/plain")}
    connector, client = make_connector(routes=routes, sleeps=sleeps, max_details=1)
    connector.fetch_jobs()
    client.close()
    assert set(sleeps) == {10.0}  # capped


def test_url_filter_skips_clearly_irrelevant_urls_before_any_request():
    requests: list[httpx.Request] = []
    connector, client = make_connector(
        requests=requests, url_filter=lambda url: "Junior" in url, max_details=10
    )
    jobs = connector.fetch_jobs()
    client.close()
    assert [job.title for job in jobs] == ["Junior Software Engineer"]
    assert [r.url.path for r in requests if r.url.path.startswith("/en/")] == ["/en/job/101/Junior-Software-Engineer"]


def test_max_jobs_limits_results():
    connector, client = make_connector(max_jobs=1)
    assert len(connector.fetch_jobs()) == 1
    client.close()


# -- JobPosting parsing -------------------------------------------------------------------


def test_job_posting_fields_are_mapped_from_json_ld_only():
    connector, client = make_connector(company_name="Example Co")
    jobs = by_title(connector.fetch_jobs())
    client.close()

    remote = jobs["Remote Backend Engineer"]
    assert remote.provider == "careers_site" and remote.company_name == "Example Co"
    assert remote.source_url == remote.canonical_url == remote.apply_url == (
        "https://careers.example.com/en/job/105/Remote-Backend-Engineer"
    )
    assert remote.external_id == "careers.example.com/en/job/105/Remote-Backend-Engineer"
    assert remote.description == "Build & run services.\nPython\nSQL"  # escaped HTML decoded once, then as text
    assert "never be scraped" not in remote.description
    assert remote.published_at.isoformat() == "2026-10-03T00:00:00+00:00"
    assert remote.employment_type is EmploymentType.FULL_TIME
    assert remote.remote_policy is RemotePolicy.REMOTE
    # TELECOMMUTE is the work mode only: the applicant countries are kept as text, eligibility stays unknown.
    assert remote.remote_eligibility is RemoteEligibility.UNKNOWN
    assert remote.location == "Spain, Portugal"
    assert remote.salary_min == Decimal("45000") and remote.salary_max == Decimal("60000")
    assert remote.currency == "EUR" and remote.salary_period is SalaryPeriod.YEAR
    assert remote.raw_metadata["identifier"] == "R-105"
    assert remote.raw_metadata["validThrough"] == "2099-01-31T23:59:00+00:00"
    assert remote.raw_metadata["applicantLocationRequirements"] == ["Spain", "Portugal"]
    assert remote.raw_metadata["hiringOrganization"] == "Example Corp"
    assert remote.raw_metadata["sitemapLastmod"] == "2026-10-03"

    onsite = jobs["Junior Software Engineer"]
    assert onsite.location == "Madrid, MD, ES; Barcelona, Spain"
    assert onsite.remote_policy is None and onsite.remote_eligibility is RemoteEligibility.UNKNOWN
    assert onsite.employment_type is EmploymentType.INTERNSHIP
    assert onsite.published_at.isoformat() == "2026-10-04T08:30:00+00:00"  # naive timestamps are read as UTC
    # A bare number without a period is not an explicit salary.
    assert onsite.salary_min is None and onsite.currency is None and onsite.salary_period is None
    assert onsite.company_name == "Example Co"


def test_hiring_organization_names_the_company_when_none_is_configured():
    connector, client = make_connector(max_details=20)
    jobs = by_title(connector.fetch_jobs())
    client.close()
    assert jobs["Remote Backend Engineer"].company_name == "Example Corp"  # object form
    assert jobs["Junior Software Engineer"].company_name == "Example Corp"  # plain string form
    assert jobs["Graph Engineer"].company_name is None


def test_graph_postings_unknowns_stay_unknown():
    connector, client = make_connector()
    graph = by_title(connector.fetch_jobs())["Graph Engineer"]
    client.close()
    assert graph.remote_policy is RemotePolicy.REMOTE  # TELECOMMUTE as a list
    assert graph.employment_type is None  # two different types: ambiguous
    assert graph.published_at is None  # unparseable date
    assert graph.location is None and graph.description is None


def test_pages_without_exactly_one_job_posting_are_skipped_never_scraped():
    connector, client = make_connector(max_details=20)
    titles = {job.title for job in connector.fetch_jobs()}
    client.close()
    assert titles == {"Remote Backend Engineer", "Junior Software Engineer", "Graph Engineer"}
    # 100 and 107 (WebPage + broken JSON), 102 (microdata only), 104 (two postings) are skipped; 103 expired.
    assert connector.stats["no_jobposting"] == 4
    assert connector.stats["expired"] == 1
    assert connector.stats["parsed"] == 3


def test_withdrawn_page_and_non_html_are_skipped():
    routes = {"/en/job/105/Remote-Backend-Engineer": (404, "", "text/html")}
    connector, client = make_connector(routes=routes)
    assert "Remote Backend Engineer" not in {job.title for job in connector.fetch_jobs()}
    client.close()


def test_server_errors_on_a_job_page_raise_instead_of_silently_dropping():
    routes = {"/en/job/105/Remote-Backend-Engineer": (500, "", "text/html")}
    connector, client = make_connector(routes=routes, max_details=20)
    with pytest.raises(CareersSiteConnectorError, match="HTTP 500"):
        connector.fetch_jobs()
    client.close()


# -- HTTP safety ----------------------------------------------------------------------------


def test_redirects_are_followed_only_within_the_host():
    def to_other_host(_request):
        return httpx.Response(302, headers={"location": "https://evil.example.net/robots.txt"})

    connector, client = make_connector(routes={"/robots.txt": to_other_host})
    with pytest.raises(CareersSiteConnectorError, match="another host"):
        connector.fetch_jobs()
    client.close()

    def same_host(_request):
        return httpx.Response(301, headers={"location": "/en/job/105/Remote-Backend-Engineer"})

    connector, client = make_connector(routes={"/en/job/106/Graph-Engineer": same_host}, max_details=20)
    titles = [job.title for job in connector.fetch_jobs()]
    client.close()
    assert titles.count("Remote Backend Engineer") == 2  # followed within the host (stored under both URLs)


def test_redirect_loops_are_bounded():
    def loop(_request):
        return httpx.Response(302, headers={"location": "/robots.txt"})

    connector, client = make_connector(routes={"/robots.txt": loop})
    with pytest.raises(CareersSiteConnectorError, match="too many times"):
        connector.fetch_jobs()
    client.close()


def test_size_caps_and_dtd_sitemaps_are_rejected(monkeypatch):
    monkeypatch.setattr("ai_job_hunter.connectors.careers_site._MAX_PAGE_BYTES", 100)
    connector, client = make_connector(max_details=1)
    with pytest.raises(CareersSiteConnectorError, match="too large"):
        connector.fetch_jobs()
    client.close()

    bomb = '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><urlset><url><loc>&a;</loc></url></urlset>'
    connector, client = make_connector(routes={"/sitemaps/jobs1.xml": (200, bomb, "application/xml")})
    with pytest.raises(CareersSiteConnectorError, match="DTD"):
        connector.fetch_jobs()
    client.close()

    connector, client = make_connector(routes={"/sitemaps/jobs1.xml": (200, "<html>nope</html", "text/html")})
    with pytest.raises(CareersSiteConnectorError, match="not valid XML"):
        connector.fetch_jobs()
    client.close()


def test_sitemap_files_are_bounded(monkeypatch):
    monkeypatch.setattr("ai_job_hunter.connectors.careers_site._MAX_SITEMAP_FILES", 2)
    requests: list[httpx.Request] = []
    connector, client = make_connector(requests=requests, max_details=0)
    connector.fetch_jobs()
    client.close()
    assert [r.url.path for r in requests] == ["/robots.txt", "/sitemap_index.xml", "/sitemaps/jobs1.xml"]
    connector, client = make_connector(requests=(requests := []), max_details=0)
    monkeypatch.setattr("ai_job_hunter.connectors.careers_site._MAX_SITEMAP_FILES", 1)
    connector.fetch_jobs()
    client.close()
    assert [r.url.path for r in requests] == ["/robots.txt", "/sitemap_index.xml"]


# -- probe ------------------------------------------------------------------------------------


def test_probe_samples_three_spread_pages_and_reports_support():
    requests: list[httpx.Request] = []
    connector, client = make_connector(requests=requests)
    probe = connector.probe(3)
    client.close()
    assert probe.sampled == 3 and probe.job_urls == 10
    assert [r.url.path for r in requests if r.url.path.startswith("/en/")].__len__() == 3
    assert probe.supported == (probe.postings > 0)


def test_probe_careers_site_requires_a_job_posting_and_falls_back_to_the_host():
    routes = {"/robots.txt": (200, "", "text/plain"), "/sitemap.xml": (200, fixture("sitemap_jobs.xml"), "application/xml")}
    # Only job pages under /en carry postings; the URL path /fr finds no job URLs, so the bare host is tried.
    table = {**default_routes(), **routes}

    def handler(request: httpx.Request) -> httpx.Response:
        status, body, content_type = table.get(request.url.path, (404, "", "text/plain"))
        return httpx.Response(status, content=body.encode(), headers={"content-type": content_type})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    probe = probe_careers_site("https://careers.example.com/fr", client=client, sleep=lambda _s: None)
    assert probe is not None and probe.identifier == "careers.example.com" and probe.postings >= 1

    empty = {**table, **{path: (200, fixture("page_no_posting.html"), "text/html") for path in table if path.startswith("/en/")}}

    def handler_empty(request: httpx.Request) -> httpx.Response:
        status, body, content_type = empty.get(request.url.path, (404, "", "text/plain"))
        return httpx.Response(status, content=body.encode(), headers={"content-type": content_type})

    client = httpx.Client(transport=httpx.MockTransport(handler_empty))
    assert probe_careers_site("https://careers.example.com/", client=client, sleep=lambda _s: None) is None

    def blocked(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="blocked")

    client = httpx.Client(transport=httpx.MockTransport(blocked))
    assert probe_careers_site("https://careers.example.com/", client=client, sleep=lambda _s: None) is None


# -- configuration and factory ---------------------------------------------------------------


def test_job_source_spec_validates_careers_site_identifiers():
    spec = JobSourceSpec(provider="CAREERS_SITE", identifier="careers.cisco.com/global/en", company_name="Cisco")
    assert spec.provider == "careers_site"
    for bad in ("localhost", "https://careers.cisco.com", "10.1.2.3"):
        with pytest.raises(ValueError):
            JobSourceSpec(provider="careers_site", identifier=bad)
    with pytest.raises(ValueError, match="region"):
        JobSourceSpec(provider="careers_site", identifier="careers.cisco.com", region="eu")


def test_factory_builds_careers_site_connectors_with_known_urls_and_slug_filter():
    config = JobSourcesConfig(
        sources=[JobSourceSpec(provider="careers_site", identifier=f"{HOST}", company_name="Example Co", max_jobs=5)]
    )
    requests: list[httpx.Request] = []
    table = default_routes()

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        status, body, content_type = table.get(request.url.path, (404, "", "text/plain"))
        return httpx.Response(status, content=body.encode(), headers={"content-type": content_type})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    (connector,) = build_job_connectors(
        config, client=client, known_urls={HOST: frozenset({"https://careers.example.com/en/job/105/Remote-Backend-Engineer"})}
    )
    assert isinstance(connector, CareersSiteConnector) and connector.max_jobs == 5
    # The slug gate and the known URL keep these pages out: "Web-Page-Without-Posting" has no engineering title.
    assert title_may_be_relevant("Remote Backend Engineer")
    connector._sleep = lambda _s: None
    connector.fetch_jobs()
    client.close()
    fetched = {request.url.path for request in requests if request.url.path.startswith("/en/")}
    assert "/en/job/105/Remote-Backend-Engineer" not in fetched
    assert "/en/job/101/Junior-Software-Engineer" in fetched


# -- job pages without JSON-LD (small WordPress-style sites) ------------------------------

LABELLED_JOB = """<html><body><nav><a href="/ofertas/">Ofertas</a></nav><main>
<h1>Data Engineer</h1>
<p>Acerca del empleo</p>
<p>&#128205; Ubicación: Madrid (modelo híbrido)</p>
<p>&#128188; Tipo de contrato: Jornada completa</p>
<p>&#127919; Experiencia: 1 – 3 años</p>
<p>Diseñar pipelines de datos con Python y SQL.</p>
</main></body></html>"""

LISTING = """<html><body><main><h1>Ofertas</h1>
<a href="/ofertas/data-engineer/">Data Engineer</a><p>Ubicación: Madrid</p><p>Experiencia: 1 – 3 años</p>
<a href="https://careers.example.com/ofertas/mlops-engineer/">MLOps Engineer</a><p>Ubicación: Madrid</p><p>Experiencia: 1 – 4 años</p>
<a href="/ofertas/brochure.pdf">PDF</a><a href="/blog/post/">Blog</a><a href="https://other.example.org/ofertas/x/">Other</a>
<a href="/ofertas/?page=2">Next</a></main></body></html>"""

BLOG_POST = "<html><body><main><h1>Diez consejos</h1><p>Ubicación: Madrid</p></main></body></html>"


def listing_routes():
    html = "text/html; charset=utf-8"
    return {
        "/robots.txt": (200, "User-agent: *\nAllow: /\n", "text/plain"),
        "/sitemap.xml": (200, '<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"><url><loc>https://careers.example.com/ofertas/</loc></url></urlset>', "application/xml"),
        "/ofertas/": (200, LISTING, html),
        "/ofertas/data-engineer/": (200, LABELLED_JOB, html),
        "/ofertas/mlops-engineer/": (200, BLOG_POST, html),
    }


def test_offers_linked_only_from_the_listing_page_are_read_from_labelled_job_pages():
    requests: list[httpx.Request] = []
    connector, client = make_connector(f"{HOST}/ofertas", routes=listing_routes(), requests=requests, company_name="Quantia")
    jobs = connector.fetch_jobs()
    client.close()

    paths = [request.url.path for request in requests]
    assert "/ofertas/data-engineer/" in paths and "/ofertas/mlops-engineer/" in paths
    assert not any(path.endswith(".pdf") or path.startswith("/blog") for path in paths)
    (job,) = jobs  # the blog-like page has one label only and is skipped
    assert job.title == "Data Engineer" and job.company_name == "Quantia"
    assert job.location == "Madrid (modelo híbrido)"
    assert job.employment_type is EmploymentType.FULL_TIME
    assert job.published_at is None and job.remote_eligibility is RemoteEligibility.UNKNOWN
    assert job.raw_metadata["labels"]["experience"] == "1 – 3 años"
    assert "pipelines de datos" in job.description and "Ofertas" not in job.description.split("\n")[0]


def test_listing_pages_and_pages_with_repeated_labels_are_not_job_ads():
    routes = listing_routes()
    routes["/ofertas/data-engineer/"] = (200, LISTING, "text/html")  # labels repeated: a listing, not one ad
    connector, client = make_connector(f"{HOST}/ofertas", routes=routes)
    assert connector.fetch_jobs() == []
    client.close()


def test_probe_finds_a_listing_page_identifier():
    routes = {**default_routes(), **listing_routes()}

    def handler(request: httpx.Request) -> httpx.Response:
        status, body, content_type = routes.get(request.url.path, (404, "", "text/plain"))
        return httpx.Response(status, content=body.encode("utf-8"), headers={"content-type": content_type})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    probe = probe_careers_site(f"https://{HOST}/ofertas/", client=client, sleep=lambda _s: None)
    client.close()
    assert probe is not None and probe.identifier == f"{HOST}/ofertas" and probe.postings >= 1
