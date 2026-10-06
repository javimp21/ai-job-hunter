from pathlib import Path
from uuid import uuid4

import pytest
from company_hunter_support import add_company, add_contact, make_fetcher, scripted_client, write_private
from sqlalchemy import select

from test_company_hunter_cli import keep_logging_state  # noqa: F401 - autouse: alembic reconfigures logging

from ai_job_hunter.cli import main
from ai_job_hunter.company_hunter.contacts import discover_contacts, prune_contacts
from ai_job_hunter.company_hunter.people import looks_like_name, parse_page
from ai_job_hunter.company_hunter.queue import suggest_connections
from ai_job_hunter.company_hunter.ranking import (
    CompanyInputs,
    PostingEvidence,
    SizeBasis,
    SizeClass,
    CompanyStage,
    company_stage,
    estimate_size,
    rank_companies,
    score_company,
)
from ai_job_hunter.company_hunter.relevance import RoleKind, assess_role, relevance, role_belongs_to
from ai_job_hunter.models import CompanyEvidence, Contact, MonitoredSource, MonitoredSourceState, Outreach

FIXTURES = Path(__file__).parent / "fixtures" / "company_hunter"
MONDAY = __import__("datetime").datetime(2026, 10, 5, 8, 0, tzinfo=__import__("datetime").UTC)


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# ---- real-HTML regression fixtures ---------------------------------------------------------


def test_databricks_navigation_and_footer_items_are_never_people():
    html = fixture("databricks_home_menu.html")
    for url in ("https://www.databricks.com/", "https://www.databricks.com/company/about-us"):
        # Even when cards are forced on, product menu entries are not people.
        for allow in (None, True):
            page = parse_page(url, html, company_domain="databricks.com", allow_cards=allow)
            assert page.people == [], [p.name for p in page.people]
    for text in ("Business Intelligence", "Customer Data Platform", "AI Assistant", "Platform Overview",
                 "Databricks Academy", "Artificial Intelligence", "Cloud Providers", "Cost Calculator"):
        assert not looks_like_name(text), text


def test_raisin_team_cards_are_read_with_roles_and_linkedin_from_the_card():
    page = parse_page(
        "https://www.raisin.com/es-es/acerca-raisin/", fixture("raisin_acerca_raisin.html"), company_domain="raisin.com"
    )

    people = {p.name: p for p in page.people}
    assert set(people) == {
        "Dr. Tamaz Georgadze", "Dr. Frank Freund", "Michael Stephan", "Katharina Lüth",
        "Benedikt Voller", "Marta Pinedo Engelmann",
    }
    assert people["Dr. Frank Freund"].role == "Chief Financial Officer (CFO) y fundador"
    assert people["Dr. Frank Freund"].linkedin_url == "https://linkedin.com/in/ffreund"
    assert people["Marta Pinedo Engelmann"].role == "Directora general de Raisin España"
    assert all(p.evidence_type == "team_card" and p.email is None for p in page.people)
    assert page.language == "es"
    legal = {"Política de Privacidad", "Aviso legal", "Cookies"}
    assert not legal & set(people)


def test_cards_are_not_read_on_a_home_page_or_inside_navigation_and_footers():
    card = "<div><h3>Jane Doe</h3><p>Engineering Manager</p></div>"
    on_home = parse_page("https://acme.example.test/", f"<html><body><main>{card}</main></body></html>")
    assert on_home.people == []
    for wrapper in ("<nav>{}</nav>", "<footer>{}</footer>", '<div class="mega-menu">{}</div>', '<div role="navigation">{}</div>',
                    "<header>{}</header>", "<aside>{}</aside>"):
        html = "<html><body>" + wrapper.format(card) + "</body></html>"
        assert parse_page("https://acme.example.test/team", html).people == [], wrapper
    ok = parse_page("https://acme.example.test/team", f"<html><body><main><section>{card}</section></main></body></html>")
    assert [p.name for p in ok.people] == ["Jane Doe"]
    in_article_header = (
        "<html><body><main><article><header><h3>Jane Doe</h3><p>Engineering Manager</p></header></article></main></body></html>"
    )
    assert [p.name for p in parse_page("https://acme.example.test/team", in_article_header).people] == ["Jane Doe"]


def test_a_name_must_share_a_card_with_its_role_and_menu_texts_are_not_names():
    split = """<html><body><main>
      <h3>Jane Doe</h3><div><p>Some text</p><p>and more</p><p>and more</p></div>
      <p>Engineering Manager</p>
      <div><h3>Product Overview</h3><p>Staff Engineer</p></div>
      <div><h3>Cloud Providers</h3><p>Senior Engineer</p></div>
    </main></body></html>"""
    assert parse_page("https://acme.example.test/team", split).people == []

    in_menu = """<html><body><nav><a href="/x">Maria Garcia</a></nav><main>
      <div><h3>Maria Garcia</h3><p>Senior Engineer</p></div></main></body></html>"""
    assert parse_page("https://acme.example.test/team", in_menu).people == []  # identical to a menu link text


def test_a_wrapper_holding_several_people_is_not_one_card():
    html = """<html><body><main><div>
      <h3>Jane Doe</h3><p>Engineering Manager</p><h3>John Smith</h3><p>Backend Engineer</p>
    </div></main></body></html>"""
    names = [p.name for p in parse_page("https://acme.example.test/team", html).people]
    assert names == []  # ambiguous pairing in one flat wrapper is skipped, not guessed


def test_structured_data_person_organization_members_and_microdata():
    html = """<html><head><script type="application/ld+json">
    {"@type":"Organization","name":"Acme","employee":[{"@type":"Person","name":"Rosa Vidal","jobTitle":"VP Engineering"},
      {"@type":"Person","name":"Leo Marin","jobTitle":"Marketing Manager"}]}
    </script></head><body><div itemscope itemtype="https://schema.org/Person">
      <span itemprop="name">Pablo Rey</span><span itemprop="jobTitle">Tech Lead</span></div></body></html>"""

    page = parse_page("https://acme.example.test/", html)

    assert {(p.name, p.evidence_type) for p in page.people} == {("Rosa Vidal", "json_ld"), ("Pablo Rey", "microdata")}


# ---- role relevance ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "role,kind",
    [
        ("CTO", RoleKind.ENGINEERING_C), ("VP Engineering", RoleKind.ENGINEERING_C),
        ("Chief Technology Officer", RoleKind.ENGINEERING_C), ("Head of Engineering", RoleKind.ENGINEERING_HEAD),
        ("Director of Engineering", RoleKind.ENGINEERING_HEAD), ("Engineering Manager", RoleKind.ENGINEERING_MANAGER),
        ("Tech Lead", RoleKind.TECH_LEAD), ("Staff Software Engineer", RoleKind.SENIOR_ENGINEER),
        ("Senior Backend Engineer", RoleKind.SENIOR_ENGINEER), ("Software Engineer", RoleKind.ENGINEER),
        ("Technical Recruiter", RoleKind.RECRUITER), ("Talent Acquisition Partner", RoleKind.RECRUITER),
        ("Chief Executive Officer (CEO) y fundador", RoleKind.NON_ENGINEERING_C),
        ("Chief Financial Officer (CFO)", RoleKind.NON_ENGINEERING_C), ("Chief Operation Officer (COO)", RoleKind.NON_ENGINEERING_C),
        ("Chief Revenue Officer (CRO)", RoleKind.NON_ENGINEERING_C), ("Co-Founder", RoleKind.NON_ENGINEERING_C),
        ("Chief Product Officer", RoleKind.NON_ENGINEERING_C), ("Directora general de Raisin España", RoleKind.NON_ENGINEERING_C),
    ],
)
def test_role_kinds(role, kind):
    assert assess_role(role).kind is kind


@pytest.mark.parametrize(
    "text",
    ["Marketing Manager", "Product Manager", "Explore benefits, tiers and how to become a partner", "Platform Overview",
     "Sales Director", "", None, "x " * 50, "We are hiring engineers to build the platform of the future today."],
)
def test_non_targets_and_sentences_are_not_roles(text):
    assert assess_role(text) is None


def test_relevance_order_and_company_size_rules():
    order = ["Technical Recruiter", "Engineering Manager", "Tech Lead", "Head of Engineering", "Software Engineer"]
    scores = [relevance(role, small_known=False) for role in order]
    assert scores == sorted(scores, reverse=True) and None not in scores
    # A recruiter is the best cold contact for a junior; a director of a big org the worst of the leaders.
    assert relevance("Technical Recruiter", small_known=False) > relevance("Engineering Manager", small_known=False)
    assert relevance("CTO", small_known=True) > relevance("Technical Recruiter", small_known=True)
    assert relevance("CTO", small_known=False) is None  # a CTO answers only where the company is known to be small
    assert relevance("Senior Backend Engineer", small_known=True) is None  # senior engineers do not hire juniors
    assert relevance("Staff Engineer", small_known=False) is None
    for ceo in ("CEO", "Chief Financial Officer", "COO", "Founder", "Chief Revenue Officer"):
        assert relevance(ceo, small_known=False) is None
        assert relevance(ceo, small_known=True) == 20


# ---- size evidence and ranking ------------------------------------------------------------------


def _inputs(**kwargs):
    return CompanyInputs(company_id=uuid4(), name="Co", **kwargs)


def _posting(i=0):
    return PostingEvidence(f"Java Engineer {i}", "Java", "Madrid", None, None)


def test_size_from_evidence_hints_and_job_counts_keeps_provenance_and_known_small():
    small = estimate_size(_inputs(employee_count=40, size_provenance="manual"))
    assert (small.size_class, small.basis, small.known_small) == (SizeClass.SMALL, SizeBasis.EVIDENCE, True)
    assert estimate_size(_inputs(employee_count=800)).size_class is SizeClass.MID
    assert estimate_size(_inputs(employee_count=9000)).size_class is SizeClass.LARGE
    assert estimate_size(_inputs(size_bucket="seed")).known_small

    hint = estimate_size(_inputs(lead_notes=("A fast-growing startup in Madrid",)))
    assert (hint.size_class, hint.basis, hint.known_small) == (SizeClass.SMALL, SizeBasis.HINT, False)
    assert estimate_size(_inputs(lead_notes=("Team of 11-50 employees",))).size_class is SizeClass.SMALL
    assert estimate_size(_inputs(lead_notes=("Scale-up, Series C",))).size_class is SizeClass.MID

    huge_board = estimate_size(_inputs(board_job_count=350))
    assert (huge_board.size_class, huge_board.basis, huge_board.known_small) == (SizeClass.LARGE, SizeBasis.JOB_COUNT, False)
    # 300+ postings contradict a startup hint
    assert estimate_size(_inputs(board_job_count=350, lead_notes=("startup",))).size_class is SizeClass.LARGE
    assert estimate_size(_inputs(board_job_count=150)).size_class is SizeClass.MID
    lone = estimate_size(_inputs(board_job_count=12))
    assert lone.size_class is SizeClass.UNKNOWN and not lone.known_small
    assert estimate_size(_inputs()).basis is SizeBasis.NONE
    # evidence beats the proxy
    assert estimate_size(_inputs(employee_count=40, board_job_count=400)).size_class is SizeClass.SMALL
    # hints never change the draft stage
    assert company_stage(None, None) is CompanyStage.UNKNOWN


def _factor(fit, name):
    return next(factor for factor in fit.factors if factor.name == name)


def test_startups_and_scaleups_outrank_large_companies_and_each_factor_stays_explained():
    base = {"description": "A fintech payments company.", "postings": (_posting(),)}
    startup = score_company(_inputs(employee_count=60, **base))
    scaleup = score_company(_inputs(employee_count=400, **base))
    large_evidence = score_company(_inputs(employee_count=9000, **base))
    large_board = score_company(_inputs(board_job_count=500, **base))
    unknown = score_company(_inputs(**base))

    assert startup.score > scaleup.score > unknown.score > large_evidence.score
    assert large_board.score < unknown.score
    size = _factor(large_board, "size/stage")
    assert size.points < 0 and "300+" in size.reason and size.provenance
    assert _factor(large_evidence, "size/stage").points == -10
    assert _factor(startup, "size/stage").reason == "about 60 employees"
    hint = _factor(score_company(_inputs(lead_notes=("startup",), **base)), "size/stage")
    assert 0 < hint.points < _factor(startup, "size/stage").points and "hint" in hint.reason
    assert "size/stage" not in large_board.unknowns


def test_ranking_uses_the_board_job_count_of_monitored_sources(db_session):
    big = add_company(db_session, "Big Board Co", lead=True)
    small = add_company(db_session, "Small Board Co", lead=True)
    for company, count in ((big, 450), (small, 12)):
        db_session.add(MonitoredSource(
            company_id=company.id, provider="GREENHOUSE", identifier=company.name, identifier_key=company.name.casefold(),
            origin="career_url", state=MonitoredSourceState.ACTIVE.value, last_job_count=count,
        ))
    db_session.commit()

    result = rank_companies(db_session)

    assert [fit.name for fit in result.ranked] == ["Small Board Co", "Big Board Co"]
    assert result.ranked[1].size.size_class is SizeClass.LARGE and result.ranked[0].size.size_class is SizeClass.UNKNOWN


# ---- discovery gating -----------------------------------------------------------------------------

HOME = '<html><body><a href="/es-es/acerca-raisin/">Acerca de</a></body></html>'
ENG_TEAM = """<html lang="en"><body><main>
<div><h3>Ana Torres</h3><p>CTO</p></div>
<div><h3>Bob Marley</h3><p>Head of Engineering</p></div>
<div><h3>Cleo Vega</h3><p>Engineering Manager</p></div>
<div><h3>Dan Ortiz</h3><p>Tech Lead</p></div>
<div><h3>Eva Ruiz</h3><p>Senior Backend Engineer</p></div>
<div><h3>Fer Gil</h3><p>Technical Recruiter</p></div>
<div><h3>Gus Kane</h3><p>Chief Executive Officer</p></div>
<div><h3>Hal Moon</h3><p>Marketing Manager</p></div>
</main></body></html>"""


def raisin_site(team_html):
    return {("acme.example.test", "/"): '<html><body><a href="/team">Team</a></body></html>',
            ("acme.example.test", "/team"): team_html}


def test_discovery_stores_engineering_people_and_skips_executives_when_size_is_unknown(db_session):
    company = add_company(db_session, website="https://acme.example.test")
    result = discover_contacts(db_session, company.id, fetcher=make_fetcher(raisin_site(ENG_TEAM))[0])

    stored = {c.name: c.title for c in db_session.scalars(select(Contact))}
    assert stored == {
        "Bob Marley": "Head of Engineering", "Cleo Vega": "Engineering Manager",
        "Dan Ortiz": "Tech Lead", "Fer Gil": "Technical Recruiter",
    }
    assert {(n, r) for n, r, _ in result.skipped} == {
        ("Ana Torres", "CTO"), ("Eva Ruiz", "Senior Backend Engineer"), ("Gus Kane", "Chief Executive Officer"),
    }
    assert all("<= 50 employees" in reason for n, _r, reason in result.skipped if n in {"Ana Torres", "Gus Kane"})
    assert {n for n, _r, _s in result.stored} == set(stored)


def test_discovery_on_the_raisin_fixture_stores_no_executives_unless_the_company_is_known_small(db_session):
    raisin = fixture("raisin_acerca_raisin.html")
    routes = {("www.raisin.com", "/"): HOME, ("www.raisin.com", "/es-es/acerca-raisin/"): raisin}
    company = add_company(db_session, "Raisin", website="https://www.raisin.com")

    result = discover_contacts(db_session, company.id, fetcher=make_fetcher(routes)[0])
    assert result.stored_nothing and len(result.skipped) == 6 and db_session.query(Contact).count() == 0

    db_session.add(CompanyEvidence(
        company_id=company.id, provider="manual", source_key="size", evidence_type="other",
        structured_data={"employee_count": 45},
    ))
    db_session.flush()
    again = discover_contacts(db_session, company.id, fetcher=make_fetcher(routes)[0])
    assert again.created == 6 and again.size.known_small


def test_a_startup_hint_or_a_small_board_does_not_unlock_executives(db_session):
    company = add_company(db_session, website="https://acme.example.test")
    from ai_job_hunter.models import CompanyLead

    db_session.query(CompanyLead).first().notes = "Early-stage startup"
    db_session.commit()

    result = discover_contacts(db_session, company.id, fetcher=make_fetcher(raisin_site(ENG_TEAM))[0])

    assert "Gus Kane" not in {c.name for c in db_session.scalars(select(Contact))}
    assert result.size.basis is SizeBasis.HINT


# ---- LinkedIn queue ---------------------------------------------------------------------------------

NOTE = "Hola, vi lo que hacéis en Acme Pay con Java; yo trabajo con Java y Spring Boot en banca. Encantado de conectar."


def suggest(session, tmp_path, count=5):
    cv_dir, style = write_private(tmp_path)
    client, _ = scripted_client(NOTE)
    result = suggest_connections(
        session, rank_companies(session).ranked, client=client, now=MONDAY, target=count, cv_dir=cv_dir, style_guide_path=style
    )
    session.commit()
    return result


def test_queue_never_suggests_executives_of_large_or_unknown_size_companies(db_session, tmp_path):
    company = add_company(db_session, "Execs Co")
    add_contact(db_session, company, "Cee Eo", "Chief Executive Officer", "FOUNDER")
    add_contact(db_session, company, "Cee Foo", "Chief Financial Officer", "OTHER")
    db_session.commit()

    assert suggest(db_session, tmp_path).new == []


def test_queue_suggests_executives_only_when_size_is_known_to_be_at_most_50(db_session, tmp_path):
    small = add_company(db_session, "Tiny Co")
    add_contact(db_session, small, "Cee Eo", "Chief Executive Officer", "FOUNDER")
    add_contact(db_session, small, "Cto Person", "CTO", "ENGINEERING_MANAGER")
    add_contact(db_session, small, "Eng Ineer", "Backend Engineer", "ENGINEER")
    db_session.add(CompanyEvidence(
        company_id=small.id, provider="manual", source_key="s", evidence_type="other", structured_data={"employee_count": 20},
    ))
    db_session.commit()

    result = suggest(db_session, tmp_path)

    # one person per company per day: the CTO (top at small companies) outranks the engineer and the CEO (20)
    assert [r.contact.name for r in result.new] == ["Cto Person"]


def test_queue_orders_by_relevance_within_a_company(db_session, tmp_path):
    company = add_company(db_session, "Order Co")
    for name, title in (("Rec Ruiter", "Technical Recruiter"), ("Eng Ineer", "Software Engineer"),
                        ("Tech Lead", "Tech Lead"), ("Em Manager", "Engineering Manager")):
        add_contact(db_session, company, name, title, "ENGINEER")
    db_session.commit()

    assert [r.contact.name for r in suggest(db_session, tmp_path).new] == ["Rec Ruiter"]


# ---- clean-up of already stored bad contacts ---------------------------------------------------------


def test_prune_contacts_flags_and_deletes_only_invalid_unreferenced_generated_contacts(db_session):
    company = add_company(db_session, "Databricks")
    junk = add_contact(db_session, company, "Business Intelligence", "Customer Data Platform", "ENGINEER")
    ceo = add_contact(db_session, company, "Chief Exec", "Chief Executive Officer (CEO) y fundador", "FOUNDER")
    good = add_contact(db_session, company, "Gina Torres", "Backend Engineer", "ENGINEER")
    referenced = add_contact(db_session, company, "Platform Overview", "AI Assistant", "ENGINEER")
    manual = Contact(company_id=company.id, name="Manual Entry", title="Anything", contact_type="OTHER", source_provider="manual")
    db_session.add(manual)
    db_session.add(Outreach(company_id=company.id, contact_id=referenced.id, purpose="COLD_OUTREACH", channel="EMAIL"))
    db_session.commit()

    dry = prune_contacts(db_session)
    assert {c.name for c, _ in dry.invalid} == {"Business Intelligence", "Chief Exec", "Platform Overview"}
    assert dry.deleted == 0 and db_session.query(Contact).count() == 5

    applied = prune_contacts(db_session, apply=True)
    db_session.commit()

    assert applied.deleted == 2 and [c.name for c in applied.kept_referenced] == ["Platform Overview"]
    assert {c.name for c in db_session.scalars(select(Contact))} == {"Gina Torres", "Platform Overview", "Manual Entry"}
    assert good.id and junk.id and ceo.id


def test_prune_contacts_cli_is_a_dry_run_by_default(tmp_path, monkeypatch, capsys):
    from test_company_hunter_cli import migrated_database
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session

    url, _ = migrated_database(tmp_path, monkeypatch)
    engine = create_engine(url)
    with Session(engine) as session:
        company = add_company(session, "Databricks")
        add_contact(session, company, "Business Intelligence", "Customer Data Platform", "ENGINEER")
        session.commit()
    assert main(["outreach", "prune-contacts", "--database-url", url]) == 0
    out = capsys.readouterr().out
    assert "INVALID: 1" in out and "dry run" in out
    with Session(engine) as session:
        assert session.query(Contact).count() == 1
    assert main(["outreach", "prune-contacts", "--apply", "--database-url", url]) == 0
    with Session(engine) as session:
        assert session.query(Contact).count() == 0
    engine.dispose()


# ---- roles that belong to another company, non-backend engineers, per-company cap --------------------


@pytest.mark.parametrize(
    "role,belongs",
    [
        ("CEO at Ent.Kow", False), ("CFO, Meine Erde", False), ("Founder & CEO, unwind your mind", False),
        ("Staff Engineer at Acme Pay", True), ("CTO, Acme", True), ("Senior Engineer, Platform Team", True),
        ("Head of Engineering - Data", True), ("Engineering Manager", True), ("Software Engineer @ Google", False),
        ("Tech Lead, Chief Technology Officer", True), ("CTO RawTree", False), ("CTO Acme", True), ("CTO", True),
        # Proton-style team suffixes after a team-level engineering title.
        ("Director of Engineering, Mail", True), ("Director of Engineering, VPN", True), ("Staff Engineer, Mail", True),
        ("Engineering Director, Machine Learning & AI", True), ("Backend Engineer - Drive", True),
        # Executives keep the strict rule; "at"/"@" always names the employer.
        ("CTO, Meine Erde", False), ("General Manager, VPN", False), ("Founder, SimpleLogin", False),
        ("Backend Engineer at Globex", False), ("Senior Engineer, Some Very Long Other Company Name", False),
    ],
)
def test_role_suffix_naming_another_company_is_rejected(role, belongs):
    assert role_belongs_to(role, ["Acme Pay", "acme"]) is belongs


@pytest.mark.parametrize("role", ["Support Engineer", "Product Marketing Engineer", "Sales Engineer", "Solutions Engineer",
                                  "QA Engineer", "Customer Engineering Manager", "Developer Advocate"])
def test_engineers_of_other_functions_are_not_targets(role):
    assert assess_role(role) is None


def test_testimonial_cards_on_a_team_like_page_are_not_stored(db_session):
    html = """<html><body><main>
    <div><h3>Julia Kovac</h3><p>Founder &amp; CEO, unwind your mind</p></div>
    <div><h3>Thomas Kern</h3><p>CEO at Ent.Kow</p></div>
    <div><h3>Ana Torres</h3><p>CTO</p></div></main></body></html>"""
    company = add_company(db_session, "Acme Pay", website="https://acme.example.test")
    db_session.add(CompanyEvidence(
        company_id=company.id, provider="manual", source_key="s", evidence_type="other", structured_data={"employee_count": 10},
    ))
    db_session.flush()

    result = discover_contacts(db_session, company.id, fetcher=make_fetcher(raisin_site(html))[0])

    assert [c.name for c in db_session.scalars(select(Contact))] == ["Ana Torres"]
    assert {n for n, _r, why in result.skipped if "another company" in why} == {"Julia Kovac", "Thomas Kern"}


def test_at_most_twelve_people_are_kept_per_company_most_relevant_first(db_session):
    first = ("Ana", "Bea", "Cai", "Dan", "Eli", "Fay", "Gus", "Hal", "Ivy", "Jon", "Kim", "Lou", "Max", "Ned")
    cards = "".join(f"<div><h3>{n} Perez</h3><p>Software Engineer</p></div>" for n in first)
    cards += "<div><h3>Zed Ortega</h3><p>Engineering Manager</p></div>"
    html = f"<html><body><main>{cards}</main></body></html>"
    company = add_company(db_session, website="https://acme.example.test")

    result = discover_contacts(db_session, company.id, fetcher=make_fetcher(raisin_site(html))[0])

    stored = [c.name for c in db_session.scalars(select(Contact))]
    assert len(stored) == 12 and "Zed Ortega" in stored
    assert len([s for s in result.skipped if "beyond the 12" in s[2]]) == 3
