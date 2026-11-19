from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from ai_job_hunter.candidates import load_candidate_config
from ai_job_hunter.candidates.profile import RemotePreference
from ai_job_hunter.config import Settings
from ai_job_hunter.connectors.jobr import FEED_URL as JOBR_FEED
from ai_job_hunter.connectors.jobr import JobrConnector, JobrConnectorError
from ai_job_hunter.connectors.remote_backend_jobs import FEED_URL as BACKEND_FEED
from ai_job_hunter.connectors.remote_backend_jobs import RemoteBackendJobsConnector
from ai_job_hunter.decision_engine import DecisionCache
from ai_job_hunter.domain.normalized_job import RemoteEligibility, RemotePolicy
from ai_job_hunter.models import JobEvaluation, JobSource
from ai_job_hunter.services.job_portals import due_portals, fetch_portals, parse_portal_names
from ai_job_hunter.services.liveness import needs_check
from ai_job_hunter.services.notifications import portal_credit
from ai_job_hunter.services.opportunities import refresh_opportunities

EXAMPLE_CANDIDATE = Path(__file__).parents[1] / "config" / "examples" / "candidate.example.json"
JOBR_JOB = """
<job>
  <id>123456</id>
  <title>Backend Engineer</title>
  <jobUrl>https://jobr.pro/job/123456/backend-engineer</jobUrl>
  <applyUrl>https://jobr.pro/r/123456</applyUrl>
  <location>Madrid, Spain</location>
  <remote type="hybrid">true</remote>
  <company><name>Example Madrid Systems</name></company>
  <description><![CDATA[<p>Build Python APIs &amp; PostgreSQL\x02 services.</p><p>Fluent German required.</p>]]></description>
  <salary currency="EUR"><min>50000</min><max>70000</max></salary>
  <datePosted>2026-11-18T18:30:15.000Z</datePosted>
</job>
"""
BACKEND_JOB = """
<item>
  <title>Platform Engineer at Example Remote Systems</title>
  <link>https://www.remotebackendjobs.com/cmwla77ar010w3q0ustgk5i8h-platform-engineer?utm_source=rss&amp;utm_medium=feed</link>
  <pubDate>Wed, 18 Nov 2026 19:00:00 GMT</pubDate>
  <description><![CDATA[<p>Location: Europe only · Salary: EUR 60k-80k</p><p>&lt;p&gt;Build Python APIs.&lt;/p&gt;</p>]]></description>
</item>
"""


def test_jobr_queries_bounded_country_feeds_and_keeps_the_listings_own_facts():
    requests = []
    bad_link = JOBR_JOB.replace("123456", "123457").replace("jobr.pro/job", "jobr.pro.example.test/job")
    wrong_id = JOBR_JOB.replace("<id>123456", "<id>123458")
    missing = (JOBR_JOB.replace("123456", "123459").replace("Madrid, Spain", "")
               .replace('type="hybrid">true', 'type="">false').replace("50000", "80000")
               .replace("2026-11-18T18:30:15.000Z", "2026-11-18T18:30:15"))

    def handler(request):
        requests.append(request)
        return httpx.Response(200, text=f"<jobs>{JOBR_JOB}{bad_link}{wrong_id}{missing}</jobs>")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        job, unspecified = JobrConnector(client=client).fetch_jobs()

    assert [request.url.params["location"] for request in requests] == ["ES", "IE", "NL", "CH", "GB"]
    for request in requests:
        assert request.method == "GET" and str(request.url.copy_with(query=None)) == JOBR_FEED
        assert dict(request.url.params) == {
            "location": request.url.params["location"], "role": "Software Engineer", "limit": "50",
        }
        assert "authorization" not in request.headers
    assert job.external_id == "123456" and job.company_name == "Example Madrid Systems"
    assert job.source_url == job.apply_url == job.canonical_url == "https://jobr.pro/job/123456/backend-engineer"
    assert job.location == "Madrid, Spain" and job.remote_policy is RemotePolicy.HYBRID
    assert job.description == "Build Python APIs & PostgreSQL services.\nFluent German required."
    assert (job.salary_min, job.salary_max, job.currency, job.salary_period) == (50000, 70000, "EUR", None)
    assert job.published_at == datetime(2026, 11, 18, 18, 30, 15, tzinfo=UTC)
    assert unspecified.remote_eligibility is RemoteEligibility.UNKNOWN
    assert unspecified.location is unspecified.remote_policy is unspecified.published_at is unspecified.salary_min is None
    assert portal_credit(job.apply_url) == ("Jobs via Jobr", "https://jobr.pro/")
    assert not needs_check(job.apply_url)


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"<!DOC\x02TYPE jobs><jobs/>", "forbidden DTD"),
        (b"<rss/>", "unexpected feed"),
        (b"<jobs", "not valid XML"),
        (b"<jobs>\xff</jobs>", "not valid UTF-8"),
    ],
)
def test_jobr_rejects_unsafe_or_unexpected_xml(content, message):
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, content=content))) as client:
        with pytest.raises(JobrConnectorError, match=message):
            JobrConnector(client=client).fetch_jobs()


def test_remote_backend_jobs_preserves_links_and_does_not_guarantee_global_eligibility():
    duplicate = BACKEND_JOB.replace("-platform-engineer", "-renamed")
    worldwide = BACKEND_JOB.replace("cmwla77ar010w3q0ustgk5i8h", "cmwla77ar010w3q0ustgk5i8i").replace(
        "Europe only", "Worldwide"
    )
    unknown = BACKEND_JOB.replace("cmwla77ar010w3q0ustgk5i8h", "cmwla77ar010w3q0ustgk5i8j").replace(
        "<p>Location: Europe only · Salary: EUR 60k-80k</p>", ""
    )
    bad_link = BACKEND_JOB.replace("www.remotebackendjobs.com", "www.remotebackendjobs.com@example.test")

    def handler(request):
        assert request.method == "GET" and str(request.url) == BACKEND_FEED
        assert "authorization" not in request.headers
        return httpx.Response(200, text=f"<rss><channel>{BACKEND_JOB}{duplicate}{worldwide}{unknown}{bad_link}</channel></rss>")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        job, global_job, unspecified = RemoteBackendJobsConnector(client=client).fetch_jobs()

    assert job.external_id == "cmwla77ar010w3q0ustgk5i8h"
    assert (job.title, job.company_name, job.description) == ("Platform Engineer", "Example Remote Systems", "Build Python APIs.")
    assert job.apply_url == job.source_url == f"{job.canonical_url}?utm_source=rss&utm_medium=feed"
    assert job.location == "Remote, Europe only" and job.remote_policy is RemotePolicy.REMOTE
    assert job.published_at == datetime(2026, 11, 18, 19, tzinfo=UTC)
    assert job.remote_eligibility is RemoteEligibility.UNKNOWN and job.salary_min is None
    assert global_job.remote_eligibility is RemoteEligibility.WORLDWIDE
    assert unspecified.location is None and unspecified.remote_eligibility is RemoteEligibility.UNKNOWN
    assert portal_credit(job.apply_url) == ("Remote Backend Jobs", "https://www.remotebackendjobs.com/")
    assert needs_check(job.apply_url)


def test_new_portals_are_opt_in_and_failed_portals_do_not_advance_the_poll_time(tmp_path, monkeypatch):
    monkeypatch.delenv("JOB_PORTALS", raising=False)
    names = parse_portal_names("Jobr,Remote_Backend_Jobs")
    assert set(names).isdisjoint(parse_portal_names(Settings(_env_file=None).job_portals))
    now = datetime(2026, 11, 18, 19, tzinfo=UTC)
    state = tmp_path / "portal-state.json"

    def handler(request):
        if request.url.host == "jobr.pro":
            return httpx.Response(429)
        return httpx.Response(200, text="<rss><channel/></rss>")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        jobs, failures = fetch_portals(names, client=client, state_path=state, now=now)
    assert not jobs
    assert [(failure.portal, failure.error_type) for failure in failures] == [("jobr", "JobrConnectorError")]
    assert due_portals(names, state_path=state, now=now + timedelta(hours=3)) == ["jobr"]
    assert due_portals(names, state_path=state, now=now + timedelta(hours=4)) == list(names)


def test_refresh_applies_candidate_geography_to_madrid_and_international_jobs(db_session, tmp_path):
    swiss = JOBR_JOB.replace("123456", "123457").replace("Madrid, Spain", "Zurich, Switzerland")
    us = BACKEND_JOB.replace("cmwla77ar010w3q0ustgk5i8h", "cmwla77ar010w3q0ustgk5i8i").replace(
        "Europe only", "United States only"
    )

    def handler(request):
        if request.url.host == "jobr.pro":
            items = {"ES": JOBR_JOB, "CH": swiss}.get(request.url.params["location"], "")
            return httpx.Response(200, text=f"<jobs>{items}</jobs>")
        return httpx.Response(200, text=f"<rss><channel>{BACKEND_JOB}{us}</channel></rss>")

    candidate = load_candidate_config(EXAMPLE_CANDIDATE)
    candidate.preferences.remote_preference = RemotePreference.HYBRID_OR_REMOTE
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        summary = refresh_opportunities(
            db_session,
            candidate,
            no_jev=True,
            engine=type("OfflineEngine", (), {"cache_identity": "offline"})(),
            cache=DecisionCache(tmp_path / "cache.json"),
            client=client,
            portals=parse_portal_names("jobr,remote_backend_jobs"),
            portal_state_path=tmp_path / "portal-state.json",
        )

    assert not summary.failures
    assert summary.portals_checked == 2 and summary.jobs_fetched == summary.new_jobs == 4
    assert summary.pending == summary.hard_skips == 2
    sources = db_session.query(JobSource).all()
    evaluations = {item.job_id: item for item in db_session.query(JobEvaluation).all()}
    evaluated = {source.source_location: evaluations[source.job_id] for source in sources}
    assert evaluated["Madrid, Spain"].status == evaluated["Remote, Europe only"].status == "PENDING"
    assert evaluated["Zurich, Switzerland"].decision == evaluated["Remote, United States only"].decision == "SKIP"
