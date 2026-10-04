import json

import httpx
import pytest
from company_hunter_support import add_company

from ai_job_hunter.company_hunter.contacts import discover_contacts
from ai_job_hunter.company_hunter.fetching import FetchRefused, PoliteFetcher
from ai_job_hunter.company_hunter.people import classify_role, looks_like_name, parse_page
from ai_job_hunter.models import Contact, ContactType

HOME = """<html lang="en"><body>
<nav><a href="/team">Team</a> <a href="/careers">Careers</a> <a href="/blog">Blog</a>
<a href="https://github.com/acmepay">GitHub</a> <a href="https://www.linkedin.com/company/acme">LinkedIn</a></nav>
<h1>Acme Pay</h1></body></html>"""

TEAM = """<html lang="es"><body><h1>Nuestro equipo</h1>
<div class="card"><h3>Jane Doe</h3><p>Engineering Manager</p>
  <a href="https://www.linkedin.com/in/jane-doe-123/">LinkedIn</a>
  <a href="mailto:jane@acme.example.test">Email</a></div>
<div class="card"><h3>John Smith</h3><p>Senior Backend Engineer</p>
  <a href="mailto:john@gmail.example">Email</a></div>
<div class="card"><h3>Ana López</h3><p>Marketing Manager</p></div>
<div class="card"><h3>Pedro Ruiz — CTO</h3></div>
</body></html>"""

POST_INDEX = '<html><body><a href="/blog/kafka-at-acme">Kafka at Acme</a></body></html>'
POST = """<html><head><title>Kafka at Acme</title>
<script type="application/ld+json">{"@type":"BlogPosting","headline":"Kafka at Acme",
"author":{"@type":"Person","name":"John Smith"}}</script></head><body>text</body></html>"""

GLOBAL = lambda host, port: ("93.184.216.34",)  # noqa: E731 - public address for the SSRF guard


def make_fetcher(routes, *, robots="", slept=None, **kwargs):
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        if request.url.path == "/robots.txt":
            if isinstance(robots, int):
                return httpx.Response(robots)
            return httpx.Response(200, text=robots)
        route = routes.get((request.url.host, request.url.path))
        if route is None:
            return httpx.Response(404)
        if isinstance(route, tuple):
            return httpx.Response(200, json=route[0]) if route[1] == "json" else httpx.Response(route[0])
        return httpx.Response(200, text=route, headers={"content-type": "text/html; charset=utf-8"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    fetcher = PoliteFetcher(
        client=client, host_resolver=GLOBAL, sleep=(slept.append if slept is not None else lambda s: None),
        clock=lambda: 0.0, **kwargs,
    )
    return fetcher, seen


# ---- fetcher -------------------------------------------------------------------------


def test_robots_disallow_blocks_the_page_and_never_fetches_it():
    fetcher, seen = make_fetcher({("acme.example.test", "/team"): TEAM}, robots="User-agent: *\nDisallow: /team\n")

    with pytest.raises(FetchRefused, match="robots"):
        fetcher.get_html("https://acme.example.test/team")
    assert seen == ["https://acme.example.test/robots.txt"]


def test_missing_robots_allows_but_unreachable_robots_blocks():
    fetcher, _ = make_fetcher({("acme.example.test", "/team"): TEAM}, robots=404)
    assert "Jane Doe" in fetcher.get_html("https://acme.example.test/team")[1]

    blocked, seen = make_fetcher({("acme.example.test", "/team"): TEAM}, robots=503)
    with pytest.raises(FetchRefused):
        blocked.get_html("https://acme.example.test/team")
    assert seen == ["https://acme.example.test/robots.txt"]


def test_requests_to_one_host_are_spaced_and_crawl_delay_is_honoured():
    slept: list[float] = []
    ticks = iter(range(100))
    fetcher, _ = make_fetcher(
        {("acme.example.test", "/a"): "<html></html>", ("acme.example.test", "/b"): "<html></html>"},
        robots="User-agent: *\nCrawl-delay: 4\n",
        slept=slept,
    )
    fetcher.clock = lambda: 0.0

    fetcher.get_html("https://acme.example.test/a")
    fetcher.get_html("https://acme.example.test/b")

    assert slept and max(slept) == 4.0


def test_linkedin_private_hosts_and_budget_are_refused():
    fetcher, seen = make_fetcher({}, max_pages=1)
    for url in ("https://www.linkedin.com/in/jane", "https://es.linkedin.com/company/acme"):
        with pytest.raises(FetchRefused, match="linkedin"):
            fetcher.get_html(url)
    with pytest.raises(FetchRefused):
        PoliteFetcher(client=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200)))).get_html(
            "http://127.0.0.1/team"
        )
    assert seen == []

    ok, _ = make_fetcher({("acme.example.test", "/x"): "<html></html>"}, max_pages=1)
    ok.get_html("https://acme.example.test/x")
    with pytest.raises(FetchRefused, match="budget"):
        ok.get_html("https://acme.example.test/x")


def test_api_hosts_are_allow_listed():
    fetcher, _ = make_fetcher({})
    with pytest.raises(FetchRefused):
        fetcher.get_public_json("https://evil.example.test/x", allowed_hosts=frozenset({"api.github.com"}))


# ---- parsing -------------------------------------------------------------------------


def test_role_and_name_heuristics():
    assert classify_role("Engineering Manager") is ContactType.ENGINEERING_MANAGER
    assert classify_role("CTO") is ContactType.ENGINEERING_MANAGER
    assert classify_role("Senior Backend Engineer") is ContactType.ENGINEER
    assert classify_role("Co-Founder") is ContactType.FOUNDER
    assert classify_role("Technical Recruiter") is ContactType.RECRUITER
    assert classify_role("Our mission is simple") is None
    assert looks_like_name("Ana López") and looks_like_name("Juan de la Cruz")
    assert not looks_like_name("Our Team") and not looks_like_name("Software Engineer")
    assert not looks_like_name("Meet The Team") and not looks_like_name("jane doe")


def test_team_page_pairs_names_with_roles_and_links_only_what_is_published():
    page = parse_page("https://acme.example.test/team", TEAM, company_domain="acme.example.test")
    people = {person.name: person for person in page.people}

    assert set(people) == {"Jane Doe", "John Smith", "Ana López", "Pedro Ruiz"}
    jane = people["Jane Doe"]
    assert jane.linkedin_url == "https://linkedin.com/in/jane-doe-123"
    assert jane.email == "jane@acme.example.test"
    assert people["John Smith"].email is None  # mailto on a foreign domain is not the company's
    assert people["John Smith"].linkedin_url is None
    assert people["Pedro Ruiz"].contact_type is ContactType.ENGINEERING_MANAGER
    assert people["Ana López"].contact_type is ContactType.OTHER
    assert page.language == "es"


def test_image_only_neighbour_links_are_not_attributed():
    html = """<html><body>
    <div><h3>Jane Doe</h3><p>Engineering Manager</p></div>
    <div><a href="https://www.linkedin.com/in/someone-else"><img src="x.png"></a><h3>John Smith</h3><p>Backend Engineer</p></div>
    </body></html>"""

    people = {p.name: p for p in parse_page("https://acme.example.test/team", html).people}

    assert people["Jane Doe"].linkedin_url is None
    assert people["John Smith"].linkedin_url is None


def test_bare_linkedin_label_before_the_next_name_is_not_given_to_the_previous_person():
    html = """<html><body>
    <div><h3>Jane Doe</h3><p>Engineering Manager</p></div>
    <div><a href="https://www.linkedin.com/in/john-smith-99">LinkedIn</a><h3>John Smith</h3><p>Backend Engineer</p></div>
    </body></html>"""

    people = {p.name: p for p in parse_page("https://acme.example.test/team", html).people}

    assert people["Jane Doe"].linkedin_url is None  # slug names someone else
    assert people["John Smith"].linkedin_url is None  # conservative: the link precedes his card


def test_json_ld_person_and_article_author():
    html = """<html><head><script type="application/ld+json">
    [{"@type":"Person","name":"Maria Garcia","jobTitle":"Head of Engineering",
      "sameAs":["https://www.linkedin.com/in/maria-garcia"]},
     {"@type":"Article","headline":"Our Kafka migration","author":{"@type":"Person","name":"Maria Garcia"}}]
    </script></head><body></body></html>"""

    page = parse_page("https://acme.example.test/blog/x", html)

    assert [(p.name, p.role, p.linkedin_url) for p in page.people] == [
        ("Maria Garcia", "Head of Engineering", "https://linkedin.com/in/maria-garcia")
    ]
    assert page.article_title == "Our Kafka migration" and page.article_authors == ["Maria Garcia"]


# ---- discovery -----------------------------------------------------------------------

SITE = {
    ("acme.example.test", "/"): HOME,
    ("acme.example.test", "/team"): TEAM,
    ("acme.example.test", "/blog"): POST_INDEX,
    ("acme.example.test", "/blog/kafka-at-acme"): POST,
}


def test_discovery_stores_verified_contacts_with_evidence_and_topic(db_session):
    company = add_company(db_session, website="https://acme.example.test")
    fetcher, seen = make_fetcher(SITE, robots="User-agent: *\nDisallow: /private\n")

    result = discover_contacts(db_session, company.id, fetcher=fetcher)
    db_session.commit()

    contacts = {c.name: c for c in db_session.query(Contact).all()}
    assert set(contacts) == {"Jane Doe", "John Smith", "Pedro Ruiz"}  # Ana (marketing) is not kept
    jane = contacts["Jane Doe"]
    assert (jane.title, jane.contact_type) == ("Engineering Manager", "ENGINEERING_MANAGER")
    assert jane.email == "jane@acme.example.test"
    assert jane.linkedin_url == "https://linkedin.com/in/jane-doe-123"
    assert jane.source_url == "https://acme.example.test/team"
    assert jane.evidence["quote"] == "Jane Doe — Engineering Manager"
    assert jane.evidence["language"] == "es"
    john = contacts["John Smith"]
    assert john.email is None and john.linkedin_url is None
    assert john.evidence["topic"] == "Kafka at Acme"
    assert john.evidence["topic_url"].endswith("/blog/kafka-at-acme")
    assert (result.created, result.found) == (3, 3)
    assert not any("linkedin.com" in url and "robots" not in url for url in seen)

    again = discover_contacts(db_session, company.id, fetcher=make_fetcher(SITE)[0])
    assert (again.created, again.existing) == (0, 3)
    assert db_session.query(Contact).count() == 3


def test_nothing_verifiable_means_nothing_stored(db_session):
    company = add_company(db_session, website="https://acme.example.test")
    fetcher, _ = make_fetcher({("acme.example.test", "/"): "<html><body><h1>Hello</h1><p>We build things.</p></body></html>"})

    result = discover_contacts(db_session, company.id, fetcher=fetcher)

    assert result.stored_nothing and result.found == 0
    assert db_session.query(Contact).count() == 0
    assert any("nothing stored" in note for note in result.notes)


def test_no_website_means_no_fetch(db_session):
    company = add_company(db_session, website=None, lead=False)
    fetcher, seen = make_fetcher({})

    result = discover_contacts(db_session, company.id, fetcher=fetcher)

    assert seen == [] and result.stored_nothing


def test_robots_blocked_site_yields_nothing(db_session):
    company = add_company(db_session, website="https://acme.example.test")
    fetcher, seen = make_fetcher(SITE, robots="User-agent: *\nDisallow: /\n")

    result = discover_contacts(db_session, company.id, fetcher=fetcher)

    assert result.stored_nothing and result.refused
    assert seen == ["https://acme.example.test/robots.txt"]


def test_github_org_members_need_a_stated_role_and_may_publish_linkedin(db_session):
    company = add_company(db_session, website="https://acme.example.test")
    members = [{"login": "jdoe"}, {"login": "norole"}, {"login": "noname"}]
    users = {
        "jdoe": {
            "name": "Jess Doe", "bio": "Staff Software Engineer at Acme", "html_url": "https://github.com/jdoe",
            "blog": "https://www.linkedin.com/in/jess-doe",
        },
        "norole": {"name": "Nora Role", "bio": "I like cats", "html_url": "https://github.com/norole"},
        "noname": {"name": None, "bio": "Software Engineer", "html_url": "https://github.com/noname"},
    }
    routes = {
        ("acme.example.test", "/"): HOME,
        ("api.github.com", "/orgs/acmepay/public_members"): (members, "json"),
        **{("api.github.com", f"/users/{login}"): (data, "json") for login, data in users.items()},
    }
    fetcher, seen = make_fetcher(routes)

    discover_contacts(db_session, company.id, fetcher=fetcher)

    contacts = db_session.query(Contact).all()
    assert [c.name for c in contacts] == ["Jess Doe"]
    assert contacts[0].source_provider == "github_org"
    assert contacts[0].linkedin_url == "https://linkedin.com/in/jess-doe"
    assert contacts[0].source_url == "https://github.com/jdoe"
    assert not any(url.startswith("https://github.com") or "linkedin.com" in url for url in seen)
    assert json.dumps(contacts[0].evidence).count("@") == 0
