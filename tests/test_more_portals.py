from __future__ import annotations

import httpx
import pytest

from ai_job_hunter.connectors.arbeitnow import ArbeitnowConnector, ArbeitnowConnectorError
from ai_job_hunter.connectors.fourdayweek import FourDayWeekConnector, FourDayWeekConnectorError
from ai_job_hunter.connectors.weworkremotely import (
    DEFAULT_CATEGORIES,
    WeWorkRemotelyConnector,
    WeWorkRemotelyConnectorError,
)
from ai_job_hunter.domain.normalized_job import EmploymentType, RemoteEligibility, RemotePolicy
from ai_job_hunter.services.job_portals import PORTALS, fetch_portals
from ai_job_hunter.services.notifications import portal_credit


def client_for(handler):
    requests = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    return httpx.Client(transport=httpx.MockTransport(wrapped)), requests


# Shape observed live on 2026-10-04 (trimmed).
def arbeitnow_job(slug="backend-dev-1", **changes):
    job = {
        "slug": slug,
        "company_name": "Acme GmbH",
        "title": "Backend Developer (m/w/d)",
        "description": "&lt;div&gt;&lt;p&gt;Java &amp;amp; Spring&lt;/p&gt;&lt;ul&gt;&lt;li&gt;Kafka&lt;/li&gt;&lt;/ul&gt;&lt;/div&gt;",
        "remote": True,
        "url": f"https://www.arbeitnow.com/jobs/companies/acme/{slug}",
        "tags": ["Software Development"],
        "job_types": ["Experienced", "Permanent", "Full time"],
        "location": "Berlin",
        "created_at": 1791147316,
    }
    job.update(changes)
    return job


def test_arbeitnow_maps_fields_and_does_not_guess_eligibility():
    payload = {
        "data": [
            arbeitnow_job("a"),
            arbeitnow_job("b", remote=False, location="", job_types=[], company_name=" "),
            arbeitnow_job("c", url="https://www.arbeitnow.co.uk/jobs/companies/acme/c", job_types=["Part time"]),
            arbeitnow_job("a"),
            arbeitnow_job("evil", url="https://evil.example/jobs/x"),
            arbeitnow_job("http", url="http://www.arbeitnow.com/jobs/x"),
            arbeitnow_job("notitle", title=" "),
            "junk",
        ],
        "links": {"next": "https://www.arbeitnow.com/api/job-board-api?page=2"},
    }
    client, requests = client_for(lambda request: httpx.Response(200, json=payload))
    jobs = {job.external_id: job for job in ArbeitnowConnector(client=client).fetch_jobs()}

    assert len(requests) == 1  # first page only
    assert set(jobs) == {"a", "b", "c"}
    a = jobs["a"]
    assert a.title == "Backend Developer (m/w/d)"
    assert a.company_name == "Acme GmbH"
    assert a.description == "Java & Spring\nKafka"
    assert a.location == "Berlin"
    assert a.remote_policy is RemotePolicy.REMOTE
    assert a.remote_eligibility is RemoteEligibility.UNKNOWN
    assert a.employment_type is EmploymentType.FULL_TIME
    assert a.apply_url == a.source_url == "https://www.arbeitnow.com/jobs/companies/acme/a"
    assert a.published_at.isoformat() == "2026-10-04T20:55:16+00:00"
    b = jobs["b"]
    assert b.remote_policy is None and b.location is None and b.company_name is None
    assert jobs["c"].employment_type is EmploymentType.PART_TIME


@pytest.mark.parametrize(
    "response",
    [httpx.Response(503), httpx.Response(200, text="not json"), httpx.Response(200, json={"data": "x"}), httpx.Response(200, json=[])],
)
def test_arbeitnow_errors_are_safe(response):
    client, _ = client_for(lambda request: response)
    with pytest.raises(ArbeitnowConnectorError) as error:
        ArbeitnowConnector(client=client).fetch_jobs()
    assert "arbeitnow.com" not in str(error.value)


def wwr_item(slug="acme-senior-java-developer", title="Acme: Senior Java Developer", region="Anywhere in the World", country=None, **extra):
    country_tag = f"<country>{country}</country>" if country is not None else ""
    return f"""<item>
      <media:content url="https://example.test/logo.gif" type="image/png"/>
      <title>{title}</title>
      <region>{region}</region>
      {country_tag}
      <skills>Java, Spring</skills>
      <category>Back-End Programming</category>
      <type>{extra.get("type", "Full-Time")}</type>
      <description>&lt;p&gt;&lt;strong&gt;Headquarters:&lt;/strong&gt; Ghent&lt;/p&gt;&lt;p&gt;Build &amp;amp; run APIs&lt;/p&gt;</description>
      <pubDate>Thu, 17 Sep 2026 10:51:23 +0000</pubDate>
      <expires_at>Sat, 17 Oct 2026 10:51:23 +0000</expires_at>
      <guid>https://weworkremotely.com/remote-jobs/{slug}</guid>
      <link>https://weworkremotely.com/remote-jobs/{slug}</link>
    </item>"""


def wwr_feed(*items: str) -> bytes:
    body = "\n".join(items)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss">'
        f"<channel><title>WWR</title>{body}</channel></rss>"
    ).encode()


def test_wwr_maps_region_and_country_lists_without_guessing(monkeypatch):
    sleeps = []
    monkeypatch.setattr("ai_job_hunter.connectors.weworkremotely.time.sleep", sleeps.append)
    feeds = {
        DEFAULT_CATEGORIES[0]: wwr_feed(
            wwr_item(),
            wwr_item("na-dev", "NA Co: Backend", region="North America Only"),
            wwr_item("spain-ok", "Euro: Dev", country="🇪🇸 Spain, 🇫🇷 France, and 🇩🇪 Germany", type="Contract"),
            wwr_item("no-company", "Just A Title"),
        ),
        DEFAULT_CATEGORIES[1]: wwr_feed(wwr_item(), wwr_item("bad", "X: Y").replace("weworkremotely.com", "evil.example")),
        DEFAULT_CATEGORIES[2]: wwr_feed(wwr_item("devops", "Ops Co: SRE")),
    }
    client, requests = client_for(lambda request: httpx.Response(200, content=feeds[request.url.path.split("/")[-1][:-4]]))
    jobs = {job.external_id: job for job in WeWorkRemotelyConnector(client=client).fetch_jobs()}

    assert [r.url.path for r in requests] == [f"/categories/{c}.rss" for c in DEFAULT_CATEGORIES]
    assert sleeps == [2.0, 2.0]
    assert set(jobs) == {"acme-senior-java-developer", "na-dev", "spain-ok", "no-company", "devops"}
    java = jobs["acme-senior-java-developer"]
    assert (java.title, java.company_name) == ("Senior Java Developer", "Acme")
    assert java.location == "Remote — Worldwide" and java.remote_eligibility is RemoteEligibility.WORLDWIDE
    assert java.description == "Headquarters: Ghent\nBuild & run APIs"
    assert java.employment_type is EmploymentType.FULL_TIME
    assert java.remote_policy is RemotePolicy.REMOTE
    assert java.apply_url == "https://weworkremotely.com/remote-jobs/acme-senior-java-developer"
    assert java.published_at.isoformat() == "2026-09-17T10:51:23+00:00"
    na = jobs["na-dev"]
    assert na.location == "Remote — North America Only"
    assert na.remote_eligibility is RemoteEligibility.COUNTRY_RESTRICTED
    spain = jobs["spain-ok"]
    assert spain.location == "Remote — Spain, France, Germany"
    assert spain.remote_eligibility is RemoteEligibility.COUNTRY_RESTRICTED
    assert spain.employment_type is EmploymentType.CONTRACT
    assert jobs["no-company"].company_name is None and jobs["no-company"].title == "Just A Title"


def test_wwr_long_country_list_keeps_spain_visible(monkeypatch):
    monkeypatch.setattr("ai_job_hunter.connectors.weworkremotely.time.sleep", lambda _s: None)
    countries = ", ".join(f"Country number {n} of the very long list" for n in range(20)) + ", and Spain"
    client, _ = client_for(lambda request: httpx.Response(200, content=wwr_feed(wwr_item(country=countries))))
    job = WeWorkRemotelyConnector(client=client, categories=("c",)).fetch_jobs()[0]
    assert job.location == "Remote — Spain (+20 more countries)"


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(403),
        httpx.Response(200, content=b"<html></html>"),
        httpx.Response(200, content=b"<rss"),
        httpx.Response(200, content=b'<?xml version="1.0"?><!DOCTYPE rss [<!ENTITY a "b">]><rss></rss>'),
        httpx.Response(200, content=b"x" * 4_000_001),
    ],
)
def test_wwr_errors_are_safe(response):
    client, _ = client_for(lambda request: response)
    with pytest.raises(WeWorkRemotelyConnectorError) as error:
        WeWorkRemotelyConnector(client=client, categories=("c",)).fetch_jobs()
    assert "weworkremotely.com" not in str(error.value)


def test_new_portals_are_registered_throttled_and_credited(tmp_path):
    assert {"arbeitnow", "weworkremotely", "fourdayweek"} <= set(PORTALS)
    assert portal_credit("https://4dayweek.io/job/x") == ("4dayweek.io", "https://4dayweek.io")
    client, _ = client_for(lambda request: httpx.Response(200, json={"data": [arbeitnow_job("a")]}))
    state = tmp_path / "state.json"
    offers, failures = fetch_portals(["arbeitnow"], client=client, state_path=state)
    assert [o.external_id for o in offers] == ["a"] and failures == []
    assert state.exists()

    assert portal_credit("https://www.arbeitnow.co.uk/jobs/x") == ("Arbeitnow", "https://www.arbeitnow.com")
    assert portal_credit("https://weworkremotely.com/remote-jobs/x") == ("We Work Remotely", "https://weworkremotely.com")
    assert portal_credit("https://evilarbeitnow.com/x") is None


# Shape observed live on 2026-10-04 (trimmed).
def fdw_job(slug="backend-at-acme-1", **changes):
    job = {
        "id": "01a108a0",
        "slug": slug,
        "title": "Senior Backend Engineer",
        "description": "&lt;p&gt;Build &amp;amp; run APIs&lt;/p&gt;",
        "url": f"https://4dayweek.io/job/{slug}",
        "category": "engineering",
        "contract_type": "permanent",
        "work_arrangement": "remote",
        "locations": [
            {"country": "Portugal", "continent": "Europe", "work_arrangement": "remote", "is_primary": True},
            {"country": "Spain", "continent": "Europe", "work_arrangement": "remote"},
            {"country": "Spain", "city": "Madrid", "work_arrangement": "remote"},
            {"country": "France", "work_arrangement": "onsite"},
            {"continent": "Europe", "work_arrangement": "remote"},
        ],
        "salary_min": 10000000,
        "salary_max": 15000000,
        "salary_currency": "USD",
        "salary_period": "year",
        "posted_at": "2026-10-04T20:35:25Z",
        "company": {"name": "Acme", "website": "https://www.acme.test", "hires_worldwide": True},
    }
    job.update(changes)
    return job


def test_fourdayweek_maps_countries_without_widening_and_skips_ambiguous_salary(monkeypatch):
    monkeypatch.setattr("ai_job_hunter.connectors.fourdayweek.time.sleep", lambda _s: None)
    pages = {
        "1": {"data": [fdw_job("a"), fdw_job("spain", locations=[{"country": "Spain", "work_arrangement": "remote"}]),
                       fdw_job("none", locations=[]), fdw_job("evil", url="https://evil.example/job/x"), "junk"],
              "has_more": True},
        "2": {"data": [fdw_job("a"), fdw_job("b", contract_type="contract", company=None)], "has_more": False},
    }
    client, requests = client_for(lambda request: httpx.Response(200, json=pages[request.url.params["page"]]))
    jobs = {job.external_id: job for job in FourDayWeekConnector(client=client).fetch_jobs()}

    assert [r.url.params["page"] for r in requests] == ["1", "2"]
    params = requests[0].url.params
    assert (params["work_arrangement"], params["category"], params["posted_after"], params["limit"]) == (
        "remote", "engineering", "7", "100")
    assert set(jobs) == {"a", "spain", "none", "b"}
    a = jobs["a"]
    assert a.location == "Remote — Portugal, Spain"  # on-site France and country-less entries are not eligibility
    assert a.remote_eligibility is RemoteEligibility.COUNTRY_RESTRICTED
    assert a.remote_policy is RemotePolicy.REMOTE
    assert a.employment_type is EmploymentType.FULL_TIME
    assert a.description == "Build & run APIs"
    assert a.company_name == "Acme" and a.company_website == "https://www.acme.test"
    assert a.salary_min is None and a.currency is None
    assert a.raw_metadata["salary_min"] == 10000000
    assert a.apply_url == "https://4dayweek.io/job/a"
    assert jobs["spain"].remote_eligibility is RemoteEligibility.SPAIN_ONLY
    assert jobs["none"].location is None and jobs["none"].remote_eligibility is RemoteEligibility.UNKNOWN
    assert jobs["b"].employment_type is EmploymentType.CONTRACT and jobs["b"].company_name is None


@pytest.mark.parametrize(
    "response",
    [httpx.Response(429), httpx.Response(200, text="x"), httpx.Response(200, json={"data": {}})],
)
def test_fourdayweek_errors_are_safe(response):
    client, _ = client_for(lambda request: response)
    with pytest.raises(FourDayWeekConnectorError) as error:
        FourDayWeekConnector(client=client).fetch_jobs()
    assert "4dayweek.io/api" not in str(error.value)
