from __future__ import annotations

import json
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select

from ai_job_hunter.company_leads import (
    CompanyLeadInput,
    CompanyLeadsConfig,
    CompanyLeadsConfigError,
    import_company_leads,
    load_company_leads,
    resolve_company_leads,
)
from ai_job_hunter.company_leads_cli import main as leads_cli_main
from ai_job_hunter.domain.company_intelligence import (
    ATSProvider,
    CompanyEvidenceType,
    FactStatus,
)
from ai_job_hunter.models import Company, CompanyEvidence, CompanyLead, CompanyLeadStatus, Job
from ai_job_hunter.services.company_intelligence import (
    CompanyMonitorFilters,
    build_company_monitor_targets,
    get_company_facts,
)


PUBLIC_DNS = lambda _host, _port: ("93.184.216.34",)


def _input(
    *,
    name: str = "Acme Robotics",
    website: str | None = "https://acme.test",
    careers: str | None = None,
    source_label: str = "curated list",
    **changes,
) -> CompanyLeadInput:
    values = {
        "company_name": name,
        "website_url": website,
        "careers_url": careers,
        "source_type": "curated_list",
        "source_label": source_label,
    }
    values.update(changes)
    return CompanyLeadInput.model_validate(values)


def _import_one(session, item: CompanyLeadInput) -> CompanyLead:
    import_company_leads(session, CompanyLeadsConfig(leads=[item]))
    session.flush()
    return session.scalar(select(CompanyLead).where(CompanyLead.company_name == item.company_name))


def _client(pages: dict[str, str], *, requests: list[str] | None = None) -> httpx.Client:
    def respond(request: httpx.Request) -> httpx.Response:
        if requests is not None:
            requests.append(str(request.url))
        body = pages.get(str(request.url))
        if body is None:
            return httpx.Response(404, request=request, text="not found")
        return httpx.Response(
            200,
            request=request,
            headers={"content-type": "text/html; charset=utf-8"},
            text=body,
        )

    return httpx.Client(transport=httpx.MockTransport(respond), follow_redirects=False)


def test_company_leads_json_valid_and_invalid(tmp_path):
    path = tmp_path / "leads.json"
    path.write_text(
        json.dumps({"leads": [{
            "company_name": "Example Robotics",
            "website_url": "https://example.test",
            "source_type": "curated_list",
            "source_label": "example",
        }]}),
        encoding="utf-8",
    )
    assert load_company_leads(path).leads[0].company_name == "Example Robotics"

    path.write_text('{"leads": [{"company_name": "Missing source"}]}', encoding="utf-8")
    with pytest.raises(CompanyLeadsConfigError, match="Invalid company leads config"):
        load_company_leads(path)


def test_company_leads_config_rejects_non_http_and_credentials():
    for url in ("javascript:alert(1)", "https://user:password@example.test"):
        with pytest.raises(ValueError):
            _input(website=url)


def test_import_is_idempotent_and_deduplicates_by_name_and_exact_domain(db_session):
    item = _input()
    first = import_company_leads(db_session, CompanyLeadsConfig(leads=[item, item]))
    second = import_company_leads(db_session, CompanyLeadsConfig(leads=[item]))

    assert (first.created, first.duplicates, first.unchanged) == (1, 1, 1)
    assert (second.created, second.duplicates, second.updated, second.unchanged) == (0, 1, 0, 1)
    assert db_session.scalar(select(func.count(CompanyLead.id))) == 1


def test_duplicate_import_preserves_additional_provenance(db_session):
    first = _input(source_label="launch list")
    second = _input(source_label="X hiring thread", source_url="https://social.example.test/thread/1")
    import_company_leads(db_session, CompanyLeadsConfig(leads=[first]))
    summary = import_company_leads(db_session, CompanyLeadsConfig(leads=[second]))
    lead = db_session.scalar(select(CompanyLead))

    assert summary.created == 0
    assert summary.duplicates == 1
    assert summary.updated == 1
    assert len(lead.source_provenance) == 2
    assert lead.source_url == "https://social.example.test/thread/1"


def test_distinct_domains_for_same_normalized_name_are_not_merged(db_session):
    import_company_leads(
        db_session,
        CompanyLeadsConfig(
            leads=[
                _input(website="https://acme-one.test"),
                _input(website="https://acme-two.test"),
            ]
        ),
    )
    assert db_session.scalar(select(func.count(CompanyLead.id))) == 2


def test_existing_company_intelligence_identity_is_reused(db_session):
    company = Company(name="Acme Robotics", website_url="https://acme.test")
    db_session.add(company)
    lead = _import_one(db_session, _input(careers="https://boards.greenhouse.io/acme/jobs/123"))

    result = resolve_company_leads(db_session, client=_client({}), host_resolver=PUBLIC_DNS)

    db_session.flush()
    assert result.results[0].status is CompanyLeadStatus.SUPPORTED_ATS
    assert lead.company_id == company.id
    assert db_session.scalar(select(func.count(Company.id))) == 1


def test_website_careers_link_resolves_greenhouse_and_persists_evidence_and_target(db_session):
    lead = _import_one(db_session, _input(location_hint="Europe remote", hiring_hint="Hiring engineers"))
    requests: list[str] = []
    client = _client(
        {
            "https://acme.test": '<a href="/careers">Careers</a>',
            "https://acme.test/careers": '<a href="https://boards.greenhouse.io/acme/jobs/123">Open roles</a>',
        },
        requests=requests,
    )
    try:
        summary = resolve_company_leads(db_session, client=client, host_resolver=PUBLIC_DNS)
    finally:
        client.close()

    assert requests == ["https://acme.test", "https://acme.test/careers"]
    assert summary.count(CompanyLeadStatus.SUPPORTED_ATS) == 1
    assert lead.ats_provider == ATSProvider.GREENHOUSE.value
    assert lead.ats_identifier == "acme"
    evidence = db_session.scalar(
        select(CompanyEvidence).where(CompanyEvidence.provider == "company_lead")
    )
    assert evidence.evidence_type == CompanyEvidenceType.CAREER_PAGE.value
    assert evidence.structured_data["career_page_url"] == "https://boards.greenhouse.io/acme/jobs/123"
    assert evidence.structured_data["discovery_chain"]["source_label"] == "curated list"
    targets = build_company_monitor_targets(
        db_session, CompanyMonitorFilters(supported_ats=True), limit_companies=10
    )
    assert len(targets) == 1
    assert targets[0].company_id == lead.company_id
    assert targets[0].provider is ATSProvider.GREENHOUSE
    assert targets[0].identifier == "acme"
    facts = get_company_facts(db_session, lead.company_name)
    assert facts.remote_from_spain is FactStatus.UNKNOWN


@pytest.mark.parametrize(
    ("url", "provider", "identifier", "region"),
    [
        ("https://boards.greenhouse.io/linear/jobs/123", ATSProvider.GREENHOUSE, "linear", None),
        ("https://jobs.eu.lever.co/attio/abc", ATSProvider.LEVER, "attio", "eu"),
        ("https://jobs.ashbyhq.com/duna/abc", ATSProvider.ASHBY, "duna", None),
    ],
)
def test_direct_supported_ats_urls_are_detected_without_http_fetch(
    db_session, url, provider, identifier, region
):
    lead = _import_one(db_session, _input(careers=url))
    result = resolve_company_leads(db_session, client=_client({}), host_resolver=PUBLIC_DNS)

    assert result.results[0].status is CompanyLeadStatus.SUPPORTED_ATS
    assert lead.ats_provider == provider.value
    assert lead.ats_identifier == identifier
    assert lead.ats_region == region


def test_unsupported_external_careers_host_is_not_mapped_to_new_provider(db_session):
    lead = _import_one(db_session, _input())
    client = _client(
        {
            "https://acme.test": '<a href="https://jobs.workable.com/acme">Careers</a>',
        }
    )
    try:
        summary = resolve_company_leads(db_session, client=client, host_resolver=PUBLIC_DNS)
    finally:
        client.close()

    assert summary.results[0].status is CompanyLeadStatus.UNSUPPORTED_ATS
    assert lead.ats_provider is None
    assert "unrecognized external host" in lead.resolution_note


def test_careers_subdomain_is_inspected_for_supported_ats(db_session):
    lead = _import_one(db_session, _input())
    client = _client(
        {
            "https://acme.test": '<a href="https://careers.acme.test">Careers</a>',
            "https://careers.acme.test": '<a href="https://jobs.ashbyhq.com/acme">Open roles</a>',
        }
    )
    try:
        result = resolve_company_leads(db_session, client=client, host_resolver=PUBLIC_DNS)
    finally:
        client.close()

    assert result.results[0].status is CompanyLeadStatus.SUPPORTED_ATS
    assert lead.ats_provider == ATSProvider.ASHBY.value


def test_no_careers_link_and_name_only_leads_are_not_guessed(db_session):
    website_lead = _import_one(db_session, _input(name="No Jobs Co"))
    name_only = _import_one(db_session, _input(name="Name Only Co", website=None))
    client = _client({"https://acme.test": '<a href="/about">About</a>'})
    try:
        summary = resolve_company_leads(db_session, client=client, host_resolver=PUBLIC_DNS)
    finally:
        client.close()

    assert website_lead.status == CompanyLeadStatus.NO_CAREERS_PAGE.value
    assert name_only.status == CompanyLeadStatus.AMBIGUOUS.value
    assert summary.count(CompanyLeadStatus.NO_CAREERS_PAGE) == 1
    assert summary.count(CompanyLeadStatus.AMBIGUOUS) == 1


def test_multiple_careers_links_are_ambiguous_and_not_fetched(db_session):
    lead = _import_one(db_session, _input())
    requests: list[str] = []
    client = _client(
        {"https://acme.test": '<a href="/careers">Careers</a><a href="/jobs">Jobs</a>'},
        requests=requests,
    )
    try:
        summary = resolve_company_leads(db_session, client=client, host_resolver=PUBLIC_DNS)
    finally:
        client.close()

    assert summary.results[0].status is CompanyLeadStatus.AMBIGUOUS
    assert lead.careers_url is None
    assert len(requests) == 1


def test_multiple_supported_boards_are_ambiguous(db_session):
    lead = _import_one(db_session, _input(careers="https://acme.test/careers"))
    client = _client(
        {
            "https://acme.test/careers": (
                '<a href="https://boards.greenhouse.io/acme">Greenhouse</a>'
                '<a href="https://jobs.ashbyhq.com/acme">Ashby</a>'
            )
        }
    )
    try:
        result = resolve_company_leads(db_session, client=client, host_resolver=PUBLIC_DNS)
    finally:
        client.close()

    assert result.results[0].status is CompanyLeadStatus.AMBIGUOUS
    assert lead.company_id is None
    assert db_session.scalar(select(func.count(CompanyEvidence.id))) == 0


def test_existing_company_with_conflicting_domain_marks_lead_ambiguous(db_session):
    db_session.add(Company(name="Acme Robotics", website_url="https://old-acme.test"))
    lead = _import_one(db_session, _input(careers="https://jobs.ashbyhq.com/acme"))

    result = resolve_company_leads(db_session, client=_client({}), host_resolver=PUBLIC_DNS)

    assert result.results[0].status is CompanyLeadStatus.AMBIGUOUS
    assert lead.company_id is None
    assert db_session.scalar(select(func.count(Company.id))) == 1


def test_resolution_is_idempotent_and_does_not_create_duplicate_evidence(db_session):
    lead = _import_one(db_session, _input(careers="https://jobs.ashbyhq.com/acme"))
    first = resolve_company_leads(db_session, client=_client({}), host_resolver=PUBLIC_DNS)
    second = resolve_company_leads(db_session, client=_client({}), host_resolver=PUBLIC_DNS)

    assert first.count(CompanyLeadStatus.SUPPORTED_ATS) == 1
    assert second.selected == 0
    assert lead.status == CompanyLeadStatus.SUPPORTED_ATS.value
    assert db_session.scalar(select(func.count(CompanyEvidence.id))) == 1


def test_generic_careers_page_is_resolved_without_remote_inference(db_session):
    lead = _import_one(db_session, _input(careers="https://acme.test/careers", location_hint="EU remote"))
    client = _client({"https://acme.test/careers": "<h1>Work with us</h1><p>Open roles</p>"})
    try:
        result = resolve_company_leads(db_session, client=client, host_resolver=PUBLIC_DNS)
    finally:
        client.close()

    assert result.results[0].status is CompanyLeadStatus.RESOLVED
    assert lead.company_id is None
    assert get_company_facts(db_session, lead.company_name) is None


def test_resolution_blocks_private_hosts_and_unbounded_redirects(db_session):
    private_lead = _import_one(db_session, _input(name="Private Host Co", website="http://127.0.0.1/"))
    private_result = resolve_company_leads(db_session, client=_client({}), host_resolver=PUBLIC_DNS)
    assert private_result.results[0].status is CompanyLeadStatus.FAILED
    assert "non-public" in private_lead.resolution_note

    redirect_lead = _import_one(db_session, _input(name="Redirect Co", website="https://redirect.test/"))

    def redirect(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, request=request, headers={"location": "/again"})

    client = httpx.Client(transport=httpx.MockTransport(redirect), follow_redirects=False)
    try:
        result = resolve_company_leads(db_session, client=client, host_resolver=PUBLIC_DNS)
    finally:
        client.close()
    assert result.results[0].status is CompanyLeadStatus.FAILED
    assert "redirect limit" in redirect_lead.resolution_note


def test_resolution_keeps_a_bounded_html_response_limit(db_session, monkeypatch):
    from ai_job_hunter import company_leads

    monkeypatch.setattr(company_leads, "MAX_HTML_BYTES", 32)
    lead = _import_one(db_session, _input())
    client = _client({"https://acme.test": "<html>" + ("x" * 64) + "</html>"})
    try:
        result = resolve_company_leads(db_session, client=client, host_resolver=PUBLIC_DNS)
    finally:
        client.close()
    assert result.results[0].status is CompanyLeadStatus.FAILED
    assert "size limit" in lead.resolution_note


def test_cli_invalid_config_and_missing_lead_return_nonzero(tmp_path, capsys, monkeypatch):
    from sqlalchemy import create_engine

    from ai_job_hunter.config import Settings
    from ai_job_hunter.db.base import Base

    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    monkeypatch.setattr("ai_job_hunter.company_leads_cli.get_settings", lambda: Settings())
    monkeypatch.setattr("ai_job_hunter.company_leads_cli.create_database_engine", lambda _settings: engine)
    invalid = tmp_path / "invalid.json"
    invalid.write_text('{"leads": [{"company_name": "No source"}]}', encoding="utf-8")
    assert leads_cli_main(["import", "--file", str(invalid)]) == 2
    assert "Invalid company leads config" in capsys.readouterr().err
    assert leads_cli_main(["show", str(uuid4())]) == 2


def test_cli_import_and_list_return_zero(tmp_path, capsys, monkeypatch):
    from sqlalchemy import create_engine

    from ai_job_hunter.config import Settings
    from ai_job_hunter.db.base import Base

    engine = create_engine(f"sqlite+pysqlite:///{(tmp_path / 'cli.db').as_posix()}")
    Base.metadata.create_all(engine)
    monkeypatch.setattr("ai_job_hunter.company_leads_cli.get_settings", lambda: Settings())
    monkeypatch.setattr("ai_job_hunter.company_leads_cli.create_database_engine", lambda _settings: engine)
    path = tmp_path / "leads.json"
    path.write_text(
        json.dumps({
            "leads": [{
                "company_name": "Example Robotics",
                "website_url": "https://example.test",
                "source_type": "curated_list",
                "source_label": "CLI example",
            }]
        }),
        encoding="utf-8",
    )

    assert leads_cli_main(["import", "--file", str(path)]) == 0
    assert "CREATED 1" in capsys.readouterr().out
    assert leads_cli_main(["list", "--status", "NEW"]) == 0
    assert "Example Robotics" in capsys.readouterr().out


def test_recheck_unsupported_reinspects_resolved_leads_only_on_request(db_session):
    lead = _import_one(db_session, _input(careers="https://acme.teamtailor.com/jobs"))
    lead.status = CompanyLeadStatus.RESOLVED.value
    db_session.commit()

    skipped = resolve_company_leads(db_session, client=_client({}), host_resolver=PUBLIC_DNS)
    rechecked = resolve_company_leads(
        db_session, client=_client({}), host_resolver=PUBLIC_DNS, recheck_unsupported=True
    )

    assert tuple(skipped.results) == ()
    assert rechecked.results[0].status is CompanyLeadStatus.SUPPORTED_ATS
    assert lead.ats_provider == "TEAMTAILOR" and lead.ats_identifier == "acme"


def test_directories_become_leads_without_linkedin_careers_pages():
    from datetime import UTC, datetime
    from pathlib import Path as _Path

    from ai_job_hunter.company_leads import leads_from_company_directories
    from ai_job_hunter.company_sources import CompanyEvidenceRecord, CompanySourceBatch
    from ai_job_hunter.domain.company_intelligence import CompanyEvidenceType

    def record(name, data):
        return CompanyEvidenceRecord(
            provider="p", evidence_type=CompanyEvidenceType.COMPENSATION, source_key=name,
            company_name=name, source_url="https://github.example.test/readme", structured_data=data,
        )

    batch = CompanySourceBatch(
        provider="spanish_top_tech_companies", readme_url="https://github.example.test/readme",
        repository_url="r", license_name="l", license_url="u", fetched_at=datetime.now(UTC),
        body_sha256="x", source_file_sha=None, snapshot_path=_Path("x"),
        records=(
            record("TopCo", {"career_page_url": "https://www.linkedin.com/jobs/search/?f_C=1",
                             "compensation": {"base_annual_eur": 90000}}),
            record("SalaryCo", {"career_page_urls": ["https://jobs.lever.co/salaryco"], "public_salary": True}),
        ),
    )

    leads = {lead.company_name: lead for lead in leads_from_company_directories([batch]).leads}

    assert leads["TopCo"].careers_url is None
    assert "linkedin.com" in leads["TopCo"].notes
    assert "90000" in leads["TopCo"].hiring_hint
    assert leads["SalaryCo"].careers_url == "https://jobs.lever.co/salaryco"
    assert leads["SalaryCo"].source_type == "curated_directory"


def test_repeated_rechecks_rotate_through_unchanged_leads(db_session):
    pages = {
        "https://a.test/careers": "<p>Open roles by email</p>",
        "https://b.test/careers": "<p>Open roles by email</p>",
    }
    for name, host in (("A Co", "a.test"), ("B Co", "b.test")):
        lead = _import_one(db_session, _input(name=name, website=f"https://{host}", careers=f"https://{host}/careers"))
        lead.status = CompanyLeadStatus.RESOLVED.value
    db_session.commit()

    checked = [
        resolve_company_leads(
            db_session, client=_client(pages), host_resolver=PUBLIC_DNS, recheck_unsupported=True, limit=1
        ).results[0].company_name
        for _ in range(2)
    ]

    assert sorted(checked) == ["A Co", "B Co"]
