from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select

from ai_job_hunter.company_sources import CompanySourceBatch, SkippedCompanySource
from ai_job_hunter.deduplication.normalization import normalize_company_name
from ai_job_hunter.domain.company_intelligence import (
    ATSProvider,
    CompanyEvidenceRecord,
    CompanyEvidenceType,
    FactStatus,
    company_facts,
    identify_ats,
)
from ai_job_hunter.models import Company, CompanyEvidence, Job
from ai_job_hunter.services.company_intelligence import (
    CompanyIdentityAmbiguous,
    CompanyMonitorFilters,
    find_companies_to_monitor,
    get_company_facts,
    get_company_facts_for_job,
    refresh_company_evidence,
    summarize_company_catalog,
)


def _record(
    provider: str,
    name: str,
    evidence_type: CompanyEvidenceType = CompanyEvidenceType.OTHER,
    *,
    structured_data: dict | None = None,
    website_url: str | None = None,
    source_key: str | None = None,
) -> CompanyEvidenceRecord:
    return CompanyEvidenceRecord(
        provider=provider,
        evidence_type=evidence_type,
        source_key=source_key or normalize_company_name(name),
        company_name=name,
        source_url=f"https://sources.example.test/{provider}/{name.casefold().replace(' ', '-')}",
        website_url=website_url,
        structured_data=structured_data or {},
    )


def _batch(provider: str, records: tuple[CompanyEvidenceRecord, ...]) -> CompanySourceBatch:
    return CompanySourceBatch(
        provider=provider,
        readme_url=f"https://sources.example.test/{provider}/README.md",
        repository_url=f"https://sources.example.test/{provider}",
        license_name="Fixture license",
        license_url="https://sources.example.test/license",
        fetched_at=datetime(2026, 9, 24, tzinfo=UTC),
        body_sha256="fixture-sha256",
        source_file_sha="fixture-file-sha",
        snapshot_path=Path("data/local/company-intelligence/example.md"),
        records=records,
    )


def test_company_names_strip_legal_suffix_but_keep_distinct_company_words() -> None:
    assert normalize_company_name("New Relic") == normalize_company_name("NEW RELIC, Inc.")
    assert normalize_company_name("Acme") == normalize_company_name("ACME Inc.")
    assert normalize_company_name("Acme") != normalize_company_name("Acme Technologies")


def test_company_identity_uses_domain_when_equal_and_keeps_conflicting_domains_separate(db_session) -> None:
    existing = Company(name="Acme", website_url="https://acme.example")
    db_session.add(existing)
    db_session.flush()

    result = refresh_company_evidence(
        db_session,
        (
            _batch(
                "fixture-source",
                (
                    _record("fixture-source", "ACME Inc."),
                    _record(
                        "fixture-source",
                        "Acme",
                        CompanyEvidenceType.OTHER,
                        website_url="https://acme-other.example",
                        source_key="acme-other-domain",
                    ),
                    _record(
                        "fixture-source",
                        "Acme Technologies",
                        CompanyEvidenceType.OTHER,
                    ),
                ),
            ),
        ),
    )

    companies = db_session.scalars(select(Company).order_by(Company.name)).all()
    assert result.companies_created == 2
    assert len(companies) == 3
    assert any("Acme: Acme" in item for item in result.companies_with_possible_matches)
    assert len({item.company_id for item in db_session.scalars(select(CompanyEvidence)).all()}) == 3


def test_evidence_is_persistent_idempotent_and_updateable(db_session) -> None:
    first = _record(
        "spanish_top_tech_companies",
        "New Relic, Inc.",
        CompanyEvidenceType.COMPENSATION,
        website_url="https://newrelic.com",
        structured_data={"compensation": {"base_annual_eur": 80000, "sample_size": 4}},
    )
    first_batch = _batch("spanish_top_tech_companies", (first,))
    created = refresh_company_evidence(db_session, (first_batch,))
    item = db_session.scalars(select(CompanyEvidence)).one()
    discovered_at = item.discovered_at
    assert created.companies_created == 1
    assert created.evidence_created == 1

    updated_record = first.model_copy(
        update={"company_name": "NEW RELIC", "structured_data": {"compensation": {"base_annual_eur": 85000, "sample_size": 5}}}
    )
    updated = refresh_company_evidence(
        db_session,
        (_batch("spanish_top_tech_companies", (updated_record,)),),
    )

    assert updated.companies_created == 0
    assert updated.evidence_created == 0
    assert updated.evidence_updated == 1
    assert db_session.scalar(select(func.count(CompanyEvidence.id))) == 1
    stored = db_session.scalars(select(CompanyEvidence)).one()
    assert stored.discovered_at == discovered_at
    assert stored.structured_data["compensation"]["base_annual_eur"] == 85000
    assert stored.updated_at is not None


def test_multiple_providers_are_attached_to_one_normalized_company(db_session) -> None:
    top_tech = _record(
        "spanish_top_tech_companies",
        "Acme, Inc.",
        CompanyEvidenceType.COMPENSATION,
        structured_data={
            "high_compensation_evidence": True,
            "career_page_url": "https://boards.greenhouse.io/acme",
            "compensation": {
                "metric": "median",
                "base_annual_eur": 80000,
                "total_compensation_annual_eur": 100000,
                "currency": "EUR",
                "period": "year",
                "sample_size": 6,
                "population": "Engineers with 5+ years in Spain",
                "observation_period": "2024-01 to 2026-08",
            },
        },
    )
    manfred = _record(
        "manfred_public_salary_companies",
        "ACME",
        CompanyEvidenceType.PUBLIC_SALARY,
        structured_data={
            "public_salary": True,
            "career_page_url": "https://jobs.ashbyhq.com/acme",
        },
    )
    remote = _record(
        "manual_company_evidence",
        "Acme",
        CompanyEvidenceType.REMOTE_FROM_SPAIN,
        structured_data={"remote_from_spain": True},
    )
    refresh_company_evidence(db_session, (_batch("spanish_top_tech_companies", (top_tech,)),))
    refresh_company_evidence(
        db_session,
        (_batch("manfred_public_salary_companies", (manfred,)), _batch("manual_company_evidence", (remote,))),
    )

    facts = get_company_facts(db_session, "acme")
    assert facts is not None
    assert facts.normalized_identity == "acme"
    assert facts.remote_from_spain is FactStatus.YES
    assert facts.public_salary is FactStatus.YES
    assert len(facts.high_compensation_evidence) == 1
    assert len(facts.compensation_evidence) == 1
    assert facts.source_count == 3
    assert {page.ats_provider for page in facts.career_pages} == {ATSProvider.GREENHOUSE, ATSProvider.ASHBY}
    assert sum(page.is_supported for page in facts.career_pages) == 1
    assert not hasattr(facts, "company_score")

    summary = summarize_company_catalog(db_session)
    assert summary.company_count == 1
    assert summary.evidence_count == 3
    assert summary.companies_with_remote_from_spain == 1
    assert summary.companies_with_public_salary == 1
    assert summary.companies_with_compensation_evidence == 1
    assert summary.companies_with_career_page == 1
    assert summary.companies_with_supported_ats == 1


def test_unknown_facts_stay_unknown_and_company_type_is_not_inferred(db_session) -> None:
    company = Company(name="Acme Technologies")
    db_session.add(company)
    db_session.flush()

    facts = company_facts(company)

    assert facts.remote_from_spain is FactStatus.UNKNOWN
    assert facts.public_salary is FactStatus.UNKNOWN
    assert facts.career_pages == ()
    assert facts.company_type is None
    assert not facts.high_compensation_evidence
    assert not hasattr(facts, "company_score")


def test_high_compensation_derives_from_source_nested_evidence(db_session) -> None:
    high = Company(name="High Evidence Co")
    high.evidence_items.append(
        CompanyEvidence(
            provider="spanish_top_tech_companies",
            source_key="high evidence co",
            evidence_type=CompanyEvidenceType.COMPENSATION.value,
            structured_data={"compensation": {"high_compensation_evidence": True}},
        )
    )
    lower = Company(name="Lower Evidence Co")
    lower.evidence_items.append(
        CompanyEvidence(
            provider="spanish_top_tech_companies",
            source_key="lower evidence co",
            evidence_type=CompanyEvidenceType.COMPENSATION.value,
            structured_data={"compensation": {"high_compensation_evidence": False}},
        )
    )
    db_session.add_all([high, lower])
    db_session.flush()

    assert get_company_facts(db_session, "High Evidence Co").high_compensation is FactStatus.YES
    assert get_company_facts(db_session, "High Evidence Co").high_compensation_evidence
    assert get_company_facts(db_session, "Lower Evidence Co").high_compensation is FactStatus.NO


def test_supported_ats_identification_never_fetches_or_follows_urls() -> None:
    assert identify_ats("https://boards.greenhouse.io/acme/jobs/123")[0] is ATSProvider.GREENHOUSE
    assert identify_ats("https://jobs.lever.co/acme/123")[0] is ATSProvider.LEVER
    assert identify_ats("https://jobs.ashbyhq.com/acme")[0] is ATSProvider.ASHBY
    assert identify_ats("https://careers.acme.example/jobs")[0] is ATSProvider.OTHER
    assert identify_ats(None) == (ATSProvider.UNKNOWN, None)


def test_company_facts_are_available_through_job_relationship(db_session) -> None:
    company = Company(name="Example Product Co")
    company.evidence_items.append(
        CompanyEvidence(
            provider="manual_company_evidence",
            source_key="example product co",
            evidence_type=CompanyEvidenceType.REMOTE_FROM_SPAIN.value,
            structured_data={"remote_from_spain": True},
        )
    )
    job = Job(company=company, title="Backend Engineer")
    db_session.add(job)
    db_session.flush()

    facts = get_company_facts_for_job(db_session, job.id)

    assert facts is not None
    assert facts.company_name == "Example Product Co"
    assert facts.remote_from_spain is FactStatus.YES


def test_monitor_filters_are_structured_and_require_at_least_one_filter(db_session) -> None:
    supported = Company(name="Supported Co")
    supported.evidence_items.append(
        CompanyEvidence(
            provider="manfred_public_salary_companies",
            source_key="supported co",
            evidence_type=CompanyEvidenceType.PUBLIC_SALARY.value,
            structured_data={
                "public_salary": True,
                "career_page_url": "https://jobs.lever.co/supported-co",
            },
        )
    )
    unsupported = Company(name="Other Co")
    unsupported.evidence_items.append(
        CompanyEvidence(
            provider="manfred_public_salary_companies",
            source_key="other co",
            evidence_type=CompanyEvidenceType.PUBLIC_SALARY.value,
            structured_data={
                "public_salary": True,
                "career_page_url": "https://jobs.ashbyhq.com/other-co",
            },
        )
    )
    db_session.add_all([supported, unsupported])

    with pytest.raises(ValueError, match="(?i)at least one"):
        find_companies_to_monitor(db_session, CompanyMonitorFilters())

    results = find_companies_to_monitor(
        db_session,
        CompanyMonitorFilters(has_career_page=True, public_salary=True, supported_ats=True),
    )
    assert [result.company_name for result in results] == ["Supported Co"]


def test_ambiguous_exact_name_is_reported_instead_of_merged(db_session) -> None:
    db_session.add_all(
        [
            Company(name="Acme", website_url="https://acme-one.example"),
            Company(name="ACME Inc.", website_url="https://acme-two.example"),
        ]
    )
    db_session.flush()

    with pytest.raises(CompanyIdentityAmbiguous):
        get_company_facts(db_session, "Acme")


def test_skipped_source_is_documented_without_company_rows() -> None:
    skipped = SkippedCompanySource(
        provider="remote_es",
        repository_url="https://github.com/remote-es/remotes",
        reason="No explicit license",
    )
    assert skipped.imported_records == 0
    assert "license" in skipped.reason.casefold()
