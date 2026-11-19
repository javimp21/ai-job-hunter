from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from ai_job_hunter.candidates import load_candidate_config
from ai_job_hunter.config import Settings
from ai_job_hunter.connectors.jobtech import API_URL, JobTechConnector
from ai_job_hunter.connectors.pythonjobs import FEED_URL, PythonJobsConnector, PythonJobsConnectorError
from ai_job_hunter.decision_engine import DecisionCache
from ai_job_hunter.domain.normalized_job import RemoteEligibility
from ai_job_hunter.models import JobEvaluation, JobSource
from ai_job_hunter.services.job_portals import due_portals, fetch_portals, parse_portal_names
from ai_job_hunter.services.notifications import portal_credit
from ai_job_hunter.services.opportunities import refresh_opportunities

EXAMPLE_CANDIDATE = Path(__file__).parents[1] / "config" / "examples" / "candidate.example.json"
PYTHON_JOB = """
<item>
  <title>Backend Engineer, Example Python Systems</title>
  <link>https://www.python.org/jobs/1001/</link>
  <guid>https://www.python.org/jobs/1001/</guid>
  <description><![CDATA[Remote, Spain
<p>Build Python APIs &amp; PostgreSQL services.</p>
<script>window.untrusted()</script>]]></description>
</item>
"""


def rss(items: str) -> str:
    return f"<rss version='2.0'><channel>{items}</channel></rss>"


def swedish_job(job_id: str = "2001", **changes) -> dict:
    return {
        "id": job_id,
        "webpage_url": f"https://arbetsformedlingen.se/platsbanken/annonser/{job_id}",
        "headline": "Backend Engineer",
        "description": {"text": "Build Python APIs for fictional customers."},
        "employer": {"name": "Example Stockholm Engineering", "email": "ignored@example.test"},
        "workplace_address": {"municipality": "Stockholm", "country": "Sverige"},
        "publication_date": "2026-10-02T08:15:00",
        "removed": False,
        **changes,
    }


def test_python_jobs_rss_normalizes_locations_links_and_duplicates():
    duplicate = PYTHON_JOB.replace("www.python.org/jobs/1001/", "python.org/jobs/1001/?ref=rss")
    bad_link = PYTHON_JOB.replace("www.python.org", "www.python.org.example.test")
    ambiguous = """
    <item><title>Engineer (Python, Rust), Example, Inc.</title>
    <guid>https://www.python.org/jobs/1002/</guid>
    <description>This plain text isn't a location.</description></item>
    """

    def handler(request):
        assert request.method == "GET" and str(request.url) == FEED_URL
        return httpx.Response(200, text=rss(PYTHON_JOB + duplicate + bad_link + ambiguous))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        job, ambiguous_job = PythonJobsConnector(client=client).fetch_jobs()

    assert (job.provider, job.external_id, job.company_name) == ("pythonjobs", "1001", "Example Python Systems")
    assert job.apply_url == job.canonical_url == job.source_url == "https://www.python.org/jobs/1001/"
    assert job.title == "Backend Engineer"
    assert job.location == "Remote, Spain"
    assert job.description == "Build Python APIs & PostgreSQL services."
    assert job.remote_eligibility is RemoteEligibility.UNKNOWN
    assert job.remote_policy is None and job.published_at is None
    assert ambiguous_job.title == "Engineer (Python, Rust), Example, Inc."
    assert ambiguous_job.company_name is None and ambiguous_job.location is None
    assert ambiguous_job.description == "This plain text isn't a location."
    assert portal_credit(job.source_url) == ("Python.org Jobs", "https://www.python.org/jobs/")


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"<rss>", "not valid XML"),
        (b"<rss/>", "not an RSS document"),
        ("<?xml version='1.0'?><!DOCTYPE rss><rss><channel/></rss>".encode("utf-16"), "forbidden DTD"),
        (b"x" * 4_000_001, "too large"),
    ],
)
def test_python_jobs_rejects_unsafe_or_invalid_feed(content, message):
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=content))) as client:
        with pytest.raises(PythonJobsConnectorError, match=message):
            PythonJobsConnector(client=client).fetch_jobs()


def test_jobtech_bounds_queries_and_preserves_only_listed_facts():
    requests = []

    def handler(request):
        requests.append(request)
        hits = [
            swedish_job(),
            swedish_job("2002", removed=True),
            swedish_job("2003", webpage_url="https://example.test/ads/2003"),
            swedish_job("2004", webpage_url="https://arbetsformedlingen.se/platsbanken/annonser/123"),
            swedish_job("2005", workplace_address=None, publication_date="invalid"),
            "bad row",
        ]
        return httpx.Response(200, json={"hits": hits})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        job, missing = JobTechConnector(client=client).fetch_jobs()

    assert [request.url.params["q"] for request in requests] == ["backend", "systemutvecklare", "mjukvaruutvecklare"]
    for request in requests:
        assert request.method == "GET" and str(request.url.copy_with(query=None)) == API_URL
        assert request.url.params["limit"] == "50"
        assert request.url.params["sort"] == "pubdate-desc" and request.url.params["published-after"] == "10080"
        assert "authorization" not in request.headers

    assert (job.provider, job.external_id, job.company_name) == ("jobtech", "2001", "Example Stockholm Engineering")
    assert job.apply_url == job.canonical_url == job.source_url == "https://arbetsformedlingen.se/platsbanken/annonser/2001"
    assert job.location == "Stockholm, Sweden"
    assert job.description == "Build Python APIs for fictional customers."
    assert job.published_at == datetime(2026, 10, 2, 6, 15, tzinfo=UTC)
    assert job.remote_eligibility is RemoteEligibility.UNKNOWN
    assert job.remote_policy is None and job.salary_min is None and job.raw_metadata is None
    assert missing.location is None and missing.published_at is None
    assert portal_credit(job.source_url) == ("Arbetsförmedlingen (Platsbanken)", "https://arbetsformedlingen.se/platsbanken/")


def test_public_portals_are_opt_in_and_only_success_is_throttled(tmp_path, monkeypatch):
    monkeypatch.delenv("JOB_PORTALS", raising=False)
    names = parse_portal_names("JobTech, PythonJobs")
    assert names == ("jobtech", "pythonjobs")
    assert set(names).isdisjoint(parse_portal_names(Settings(_env_file=None).job_portals))
    state = tmp_path / "portal-state.json"
    now = datetime(2026, 10, 2, tzinfo=UTC)

    def handler(request):
        if request.url.host == "jobsearch.api.jobtechdev.se":
            return httpx.Response(200, json={"unexpected": "shape"})
        assert str(request.url) == FEED_URL
        return httpx.Response(200, text=rss(PYTHON_JOB))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        jobs, failures = fetch_portals(names, client=client, state_path=state, now=now)

    assert [job.provider for job in jobs] == ["pythonjobs"]
    assert [(failure.portal, failure.error_type) for failure in failures] == [("jobtech", "JobTechConnectorError")]
    assert due_portals(names, state_path=state, now=now + timedelta(hours=11)) == ["jobtech"]
    assert due_portals(names, state_path=state, now=now + timedelta(hours=12)) == list(names)


def test_refresh_ingests_both_portals_and_applies_the_same_geography_filter(db_session, tmp_path):
    def handler(request):
        if str(request.url) == FEED_URL:
            return httpx.Response(200, text=rss(PYTHON_JOB))
        assert str(request.url.copy_with(query=None)) == API_URL
        return httpx.Response(200, json={"hits": [swedish_job()]})

    candidate = load_candidate_config(EXAMPLE_CANDIDATE)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        summary = refresh_opportunities(
            db_session,
            candidate,
            no_jev=True,
            engine=type("OfflineEngine", (), {"cache_identity": "offline"})(),
            cache=DecisionCache(tmp_path / "cache.json"),
            client=client,
            portals=parse_portal_names("pythonjobs,jobtech"),
            portal_state_path=tmp_path / "portal-state.json",
        )

    assert not summary.failures
    assert summary.portals_checked == summary.jobs_fetched == summary.new_jobs == 2
    assert summary.hard_skips == summary.pending == 1
    sources = {source.provider: source for source in db_session.query(JobSource).all()}
    assert sources["pythonjobs"].source_location == "Remote, Spain"
    assert sources["jobtech"].source_location == "Stockholm, Sweden"
    evaluations = {item.job_id: item for item in db_session.query(JobEvaluation).all()}
    assert evaluations[sources["pythonjobs"].job_id].status == "PENDING"
    assert evaluations[sources["jobtech"].job_id].decision == "SKIP"
