from __future__ import annotations

import pytest
from uuid import uuid4

from ai_job_hunter.ats_discovery import discover_ats_url
from ai_job_hunter.domain.company_intelligence import (
    ATSDiscoveryConfidence,
    ATSProvider,
    CompanyEvidenceType,
    company_facts,
)
from ai_job_hunter.models import Company, CompanyEvidence
from ai_job_hunter.services.company_intelligence import public_board_url


@pytest.mark.parametrize(
    ("url", "provider", "identifier", "region"),
    [
        ("https://boards.greenhouse.io/acme/jobs/123", ATSProvider.GREENHOUSE, "acme", None),
        ("https://job-boards.greenhouse.io/acme-platform", ATSProvider.GREENHOUSE, "acme-platform", None),
        ("https://job-boards.eu.greenhouse.io/submer/jobs/123", ATSProvider.GREENHOUSE, "submer", None),
        ("https://jobs.lever.co/acme/abc", ATSProvider.LEVER, "acme", "global"),
        ("https://jobs.eu.lever.co/acme-eu/abc", ATSProvider.LEVER, "acme-eu", "eu"),
        ("https://jobs.ashbyhq.com/acme-company/abc", ATSProvider.ASHBY, "acme-company", None),
        ("https://acme.teamtailor.com/jobs/123-role", ATSProvider.TEAMTAILOR, "acme", None),
        ("https://acme.recruitee.com/o/backend-engineer", ATSProvider.RECRUITEE, "acme", None),
        ("https://Acme-Co.teamtailor.com", ATSProvider.TEAMTAILOR, "Acme-Co".casefold(), None),
        ("https://jobs.smartrecruiters.com/AcmeCo/744-role", ATSProvider.SMARTRECRUITERS, "AcmeCo", None),
        ("https://careers.smartrecruiters.com/AcmeCo", ATSProvider.SMARTRECRUITERS, "AcmeCo", None),
        ("https://apply.workable.com/idoven/", ATSProvider.WORKABLE, "idoven", None),
        ("https://apply.workable.com/titanos/j/ABC123/", ATSProvider.WORKABLE, "titanos", None),
        ("https://acme-co.jobs.personio.de/job/123", ATSProvider.PERSONIO, "acme-co", None),
        ("https://acme.jobs.personio.com", ATSProvider.PERSONIO, "acme", "com"),
        ("https://embat.factorialhr.com/job_posting/x-1", ATSProvider.FACTORIAL, "embat", "com"),
        ("https://NextAILLabs.factorial.es/", ATSProvider.FACTORIAL, "nextaillabs", "es"),
        ("https://bbva.wd3.myworkdayjobs.com/BBVA", ATSProvider.WORKDAY, "bbva/BBVA", "wd3"),
        ("https://ING.wd3.myworkdayjobs.com/en-US/ICSGBLCOR/job/Madrid/X_R1", ATSProvider.WORKDAY, "ing/ICSGBLCOR", "wd3"),
        ("https://acme.wd103.myworkdayjobs.com/es_ES/Site", ATSProvider.WORKDAY, "acme/Site", "wd103"),
    ],
)
def test_discovery_extracts_exact_public_board_identifiers(url, provider, identifier, region):
    result = discover_ats_url(url)

    assert result.provider is provider
    assert result.identifier == identifier
    assert result.region == region
    assert result.confidence is ATSDiscoveryConfidence.DIRECT_URL_PATTERN
    assert result.source_url == url
    assert result.is_supported
    assert result.evidence


@pytest.mark.parametrize(
    ("url", "evidence_part"),
    [
        ("https://www.linkedin.com/jobs/search/?f_C=123", "LinkedIn"),
        ("https://careers.example.com/jobs", "does not match"),
        ("not a valid url ://", "malformed"),
        ("https://boards.greenhouse.io.evil.test/acme", "does not match"),
        ("https://user:pass@boards.greenhouse.io/acme", "credentials"),
        ("https://acme.teamtailor.com.evil.test/jobs", "does not match"),
        ("https://careers.acme.com/jobs", "does not match"),
        ("https://a.b.teamtailor.com/jobs", "does not match"),
        ("https://www.teamtailor.com/en/", "does not match"),
        ("https://teamtailor.com/", "does not match"),
        ("https://smartrecruiters.com/AcmeCo", "does not match"),
        ("https://jobs.smartrecruiters.com.evil.test/AcmeCo", "does not match"),
        ("https://apply.workable.com/", "does not match"),
        ("https://apply.workable.com/j/ABC123", "does not match"),
        ("https://apply.workable.com.evil.test/acme", "does not match"),
        ("https://acme.workable.com/jobs", "does not match"),
        ("https://www.jobs.personio.de/", "does not match"),
        ("https://a.b.jobs.personio.de/", "does not match"),
        ("https://acme.jobs.personio.de.evil.test/", "does not match"),
        ("https://www.factorialhr.com/careers", "does not match"),
        ("https://app.factorialhr.com/", "does not match"),
        ("https://factorialhr.com/", "does not match"),
        ("https://a.b.factorial.es/", "does not match"),
        ("https://acme.factorialhr.com.evil.test/", "does not match"),
        ("https://acme.myworkdayjobs.com/Site", "does not match"),
        ("https://acme.wd3.myworkdayjobs.com.evil.test/Site", "does not match"),
        ("https://a.b.wd3.myworkdayjobs.com/Site", "does not match"),
    ],
)
def test_unknown_urls_are_not_guessed(url, evidence_part):
    result = discover_ats_url(url)

    assert result.provider is ATSProvider.UNKNOWN
    assert result.identifier is None
    assert result.region is None
    assert result.confidence is ATSDiscoveryConfidence.UNKNOWN
    assert evidence_part.casefold() in result.evidence.casefold()
    assert not result.is_supported


def test_known_ats_host_without_a_board_path_is_not_monitorable():
    result = discover_ats_url("https://jobs.ashbyhq.com/")

    assert result.provider is ATSProvider.ASHBY
    assert result.identifier is None
    assert result.confidence is ATSDiscoveryConfidence.UNKNOWN
    assert not result.is_supported


def test_smartrecruiters_host_without_company_path_is_not_monitorable():
    result = discover_ats_url("https://jobs.smartrecruiters.com/")

    assert result.provider is ATSProvider.SMARTRECRUITERS
    assert result.identifier is None
    assert not result.is_supported


@pytest.mark.parametrize(
    ("provider", "identifier", "region", "expected"),
    [
        (ATSProvider.TEAMTAILOR, "acme", None, "https://acme.teamtailor.com/jobs"),
        (ATSProvider.SMARTRECRUITERS, "AcmeCo", None, "https://jobs.smartrecruiters.com/AcmeCo"),
        (ATSProvider.ASHBY, "acme", None, "https://jobs.ashbyhq.com/acme"),
        (ATSProvider.WORKABLE, "idoven", None, "https://apply.workable.com/idoven"),
        (ATSProvider.PERSONIO, "acme", None, "https://acme.jobs.personio.de"),
        (ATSProvider.PERSONIO, "acme", "com", "https://acme.jobs.personio.com"),
        (ATSProvider.WORKDAY, "bbva/BBVA", "wd3", "https://bbva.wd3.myworkdayjobs.com/BBVA"),
        (ATSProvider.FACTORIAL, "embat", "com", "https://embat.factorialhr.com"),
        (ATSProvider.FACTORIAL, "nextaillabs", "es", "https://nextaillabs.factorial.es"),
    ],
)
def test_public_board_url_for_new_providers(provider, identifier, region, expected):
    assert public_board_url(provider, identifier, region) == expected


def test_observed_job_source_evidence_takes_precedence_over_url_inference():
    company = Company(id=uuid4(), name="Example Co")
    company.evidence_items.extend(
        [
            CompanyEvidence(
                provider="company_catalog",
                source_key="careers",
                evidence_type=CompanyEvidenceType.CAREER_PAGE.value,
                structured_data={"career_page_url": "https://jobs.ashbyhq.com/inferred-board"},
            ),
            CompanyEvidence(
                provider="observed_job_source",
                source_key="example-observed-greenhouse",
                source_url="https://job-boards.greenhouse.io/observed-board/jobs/321",
                evidence_type=CompanyEvidenceType.ATS_OBSERVED.value,
                structured_data={
                    "ats_provider": "GREENHOUSE",
                    "identifier": "observed-board",
                    "region": None,
                    "observation_basis": "persisted_job_source",
                    "supporting_job_sources": [
                        {"source_url": "https://job-boards.greenhouse.io/observed-board/jobs/321"}
                    ],
                },
            ),
        ]
    )

    facts = company_facts(company)

    assert [item.provider for item in facts.ats_discoveries] == [ATSProvider.GREENHOUSE]
    assert facts.ats_discoveries[0].identifier == "observed-board"
    assert facts.ats_discoveries[0].confidence is ATSDiscoveryConfidence.OBSERVED_JOB_SOURCE


@pytest.mark.parametrize(
    "url", ["https://acme.wd3.myworkdayjobs.com", "https://acme.wd3.myworkdayjobs.com/en-US", "https://acme.wd3.myworkdayjobs.com/wday/cxs/acme/Site/jobs"]
)
def test_workday_host_without_site_is_not_supported(url):
    result = discover_ats_url(url)

    assert result.provider is ATSProvider.WORKDAY
    assert result.identifier is None
    assert result.confidence is ATSDiscoveryConfidence.UNKNOWN
    assert not result.is_supported


def test_workday_discovery_round_trips_through_job_sources():
    from ai_job_hunter.job_sources import JobSourceSpec

    result = discover_ats_url("https://bbva.wd3.myworkdayjobs.com/en-US/BBVA/job/x")
    spec = JobSourceSpec(provider=result.provider.value.casefold(), identifier=result.identifier, region=result.region)

    assert public_board_url(result.provider, spec.identifier, spec.region) == "https://bbva.wd3.myworkdayjobs.com/BBVA"
