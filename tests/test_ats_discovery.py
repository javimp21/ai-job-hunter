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


@pytest.mark.parametrize(
    ("url", "provider", "identifier", "region"),
    [
        ("https://boards.greenhouse.io/acme/jobs/123", ATSProvider.GREENHOUSE, "acme", None),
        ("https://job-boards.greenhouse.io/acme-platform", ATSProvider.GREENHOUSE, "acme-platform", None),
        ("https://jobs.lever.co/acme/abc", ATSProvider.LEVER, "acme", "global"),
        ("https://jobs.eu.lever.co/acme-eu/abc", ATSProvider.LEVER, "acme-eu", "eu"),
        ("https://jobs.ashbyhq.com/acme-company/abc", ATSProvider.ASHBY, "acme-company", None),
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
