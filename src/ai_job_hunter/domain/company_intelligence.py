"""Typed, source-attributed company facts; this module never assigns a score."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from urllib.parse import unquote, urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CompanyEvidenceType(StrEnum):
    COMPENSATION = "compensation"
    PUBLIC_SALARY = "public_salary"
    REMOTE_FROM_SPAIN = "remote_from_spain"
    CAREER_PAGE = "career_page"
    ATS_OBSERVED = "ats_observed"
    COMPANY_TYPE = "company_type"
    OTHER = "other"


class ATSProvider(StrEnum):
    GREENHOUSE = "GREENHOUSE"
    LEVER = "LEVER"
    ASHBY = "ASHBY"
    TEAMTAILOR = "TEAMTAILOR"
    SMARTRECRUITERS = "SMARTRECRUITERS"
    WORKABLE = "WORKABLE"
    PERSONIO = "PERSONIO"
    UNKNOWN = "UNKNOWN"


SUPPORTED_ATS_PROVIDERS = frozenset(
    {
        ATSProvider.GREENHOUSE,
        ATSProvider.LEVER,
        ATSProvider.ASHBY,
        ATSProvider.TEAMTAILOR,
        ATSProvider.SMARTRECRUITERS,
        ATSProvider.WORKABLE,
        ATSProvider.PERSONIO,
    }
)


class ATSDiscoveryConfidence(StrEnum):
    DIRECT_URL_PATTERN = "DIRECT_URL_PATTERN"
    OBSERVED_JOB_SOURCE = "OBSERVED_JOB_SOURCE"
    UNKNOWN = "UNKNOWN"


class FactStatus(StrEnum):
    YES = "YES"
    NO = "NO"
    UNKNOWN = "UNKNOWN"


class CompanyEvidenceRecord(BaseModel):
    """Validated import row used before persistence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str = Field(min_length=1, max_length=100)
    evidence_type: CompanyEvidenceType
    source_key: str = Field(min_length=1, max_length=512)
    company_name: str = Field(min_length=1, max_length=255)
    source_url: str | None = Field(default=None, max_length=2048)
    external_identifier: str | None = Field(default=None, max_length=512)
    website_url: str | None = Field(default=None, max_length=2048)
    structured_data: dict[str, Any] = Field(default_factory=dict)
    raw_metadata: dict[str, Any] | None = None


class CareerPageFact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    url: str
    ats_provider: ATSProvider
    ats_identifier: str | None = None

    @property
    def is_supported(self) -> bool:
        """Whether this URL identifies a board handled by an existing connector."""

        return self.ats_provider in SUPPORTED_ATS_PROVIDERS


class ATSDiscoveryResult(BaseModel):
    """Explainable ATS identification with a categorical evidence basis."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: ATSProvider
    identifier: str | None = None
    region: str | None = None
    confidence: ATSDiscoveryConfidence
    evidence: str
    source_url: str | None = None

    @property
    def is_supported(self) -> bool:
        return self.provider in SUPPORTED_ATS_PROVIDERS and bool(
            self.identifier and self.identifier.strip()
        )


class CompanyMonitorTarget(BaseModel):
    """A company board that can be passed to a supported public connector."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    company_id: UUID
    company_name: str
    provider: ATSProvider
    identifier: str
    region: str | None = None
    careers_url: str
    evidence_source: str
    confidence: ATSDiscoveryConfidence
    # Set when the target comes from a reviewed monitored_sources row.
    source_id: UUID | None = None


class CompanyEvidenceFact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str
    evidence_type: CompanyEvidenceType
    source_url: str | None = None
    external_identifier: str | None = None
    discovered_at: datetime | None = None
    updated_at: datetime | None = None
    structured_data: dict[str, Any] = Field(default_factory=dict)


class CompanyFacts(BaseModel):
    """A derivation over evidence that keeps unknown facts unknown."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    company_id: UUID
    company_name: str
    normalized_identity: str
    website_domain: str | None = None
    career_pages: tuple[CareerPageFact, ...] = ()
    ats_discoveries: tuple[ATSDiscoveryResult, ...] = ()
    remote_from_spain: FactStatus = FactStatus.UNKNOWN
    public_salary: FactStatus = FactStatus.UNKNOWN
    high_compensation: FactStatus = FactStatus.UNKNOWN
    high_compensation_evidence: tuple[CompanyEvidenceFact, ...] = ()
    compensation_evidence: tuple[CompanyEvidenceFact, ...] = ()
    source_count: int = 0
    evidence_count: int = 0
    evidence_freshness: datetime | None = None
    company_type: str | None = None
    evidence: tuple[CompanyEvidenceFact, ...] = ()


def identify_ats(url: str | None) -> tuple[ATSProvider, str | None]:
    """Backward-compatible tuple view of independent ATS URL discovery."""

    from ai_job_hunter.ats_discovery import discover_ats_url

    result = discover_ats_url(url)
    return result.provider, result.identifier


def company_facts(company: Any) -> CompanyFacts:
    """Derive explainable facts from a Company ORM object and its evidence."""

    from ai_job_hunter.deduplication.normalization import extract_company_domain, normalize_company_name

    evidence_rows = tuple(getattr(company, "evidence_items", ()) or ())
    evidence = tuple(
        CompanyEvidenceFact(
            provider=row.provider,
            evidence_type=CompanyEvidenceType(row.evidence_type),
            source_url=row.source_url,
            external_identifier=row.external_identifier,
            discovered_at=row.discovered_at,
            updated_at=row.updated_at,
            structured_data=dict(row.structured_data or {}),
        )
        for row in evidence_rows
    )

    def status_for(key: str, evidence_type: CompanyEvidenceType) -> FactStatus:
        values = {
            bool(item.structured_data[key])
            for item in evidence
            if item.evidence_type is evidence_type and key in item.structured_data
        }
        if values == {True}:
            return FactStatus.YES
        if values == {False}:
            return FactStatus.NO
        return FactStatus.UNKNOWN

    pages: dict[str, CareerPageFact] = {}
    inferred_ats: dict[tuple[ATSProvider, str | None, str | None], ATSDiscoveryResult] = {}
    for item in evidence:
        raw_pages: list[str] = []
        single_page = item.structured_data.get("career_page_url")
        if isinstance(single_page, str):
            raw_pages.append(single_page)
        multi_page = item.structured_data.get("career_page_urls")
        if isinstance(multi_page, list):
            raw_pages.extend(page for page in multi_page if isinstance(page, str))
        for page in raw_pages:
            from ai_job_hunter.ats_discovery import discover_ats_url

            discovery = discover_ats_url(page)
            provider, identifier = discovery.provider, discovery.identifier
            pages.setdefault(
                page.strip(),
                CareerPageFact(url=page.strip(), ats_provider=provider, ats_identifier=identifier),
            )
            if discovery.is_supported:
                inferred_ats.setdefault(
                    (discovery.provider, discovery.identifier, discovery.region), discovery
                )

    observed_ats: dict[tuple[ATSProvider, str | None, str | None], ATSDiscoveryResult] = {}
    for item in evidence:
        if item.evidence_type is not CompanyEvidenceType.ATS_OBSERVED:
            continue
        data = item.structured_data
        try:
            provider = ATSProvider(str(data.get("ats_provider", "")).upper())
        except ValueError:
            continue
        if provider is ATSProvider.UNKNOWN:
            continue
        identifier = data.get("identifier")
        identifier = identifier.strip() if isinstance(identifier, str) and identifier.strip() else None
        region = data.get("region")
        region = region.strip().casefold() if isinstance(region, str) and region.strip() else None
        source_refs = data.get("supporting_job_sources")
        first_ref = source_refs[0] if isinstance(source_refs, list) and source_refs else {}
        source_url = first_ref.get("source_url") if isinstance(first_ref, dict) else None
        source_url = source_url if isinstance(source_url, str) else item.source_url
        observed = ATSDiscoveryResult(
            provider=provider,
            identifier=identifier,
            region=region,
            confidence=ATSDiscoveryConfidence.OBSERVED_JOB_SOURCE,
            evidence=f"Observed on an existing {provider.value} job source.",
            source_url=source_url,
        )
        observed_ats.setdefault((provider, identifier, region), observed)

    # A persisted job-source observation is stronger than hostname inference.
    ats_discoveries = observed_ats or inferred_ats

    compensation = tuple(item for item in evidence if item.evidence_type is CompanyEvidenceType.COMPENSATION)
    def explicit_high_compensation_value(item: CompanyEvidenceFact) -> Any:
        if "high_compensation_evidence" in item.structured_data:
            return item.structured_data["high_compensation_evidence"]
        nested = item.structured_data.get("compensation")
        return nested.get("high_compensation_evidence") if isinstance(nested, dict) else None

    high_compensation_values = [explicit_high_compensation_value(item) for item in compensation]
    high_compensation = tuple(
        item
        for item in compensation
        if explicit_high_compensation_value(item) is True
    )
    high_compensation_status = (
        FactStatus.YES
        if any(value is True for value in high_compensation_values)
        else FactStatus.NO
        if high_compensation_values and all(value is False for value in high_compensation_values)
        else FactStatus.UNKNOWN
    )
    manual_types = [
        item.structured_data.get("value")
        for item in evidence
        if item.evidence_type is CompanyEvidenceType.COMPANY_TYPE
        and item.structured_data.get("classification_method") in {"manual", "external_source"}
    ]
    freshness = max(
        (item.updated_at for item in evidence if item.updated_at is not None),
        key=lambda value: (value.replace(tzinfo=UTC) if value.tzinfo is None else value).timestamp(),
        default=None,
    )
    return CompanyFacts(
        company_id=company.id,
        company_name=company.name,
        normalized_identity=normalize_company_name(company.name) or "",
        website_domain=extract_company_domain(company.website_url),
        career_pages=tuple(pages.values()),
        ats_discoveries=tuple(ats_discoveries.values()),
        remote_from_spain=status_for(
            "remote_from_spain", CompanyEvidenceType.REMOTE_FROM_SPAIN
        ),
        public_salary=status_for("public_salary", CompanyEvidenceType.PUBLIC_SALARY),
        high_compensation=high_compensation_status,
        high_compensation_evidence=high_compensation,
        compensation_evidence=compensation,
        source_count=len({item.provider for item in evidence}),
        evidence_count=len(evidence),
        evidence_freshness=freshness,
        company_type=manual_types[-1] if manual_types else None,
        evidence=evidence,
    )
