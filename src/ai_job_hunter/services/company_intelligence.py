"""Persistence, conservative identity resolution, and queries for company evidence."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ai_job_hunter.company_sources import CompanySourceBatch, REMOTE_ES, SkippedCompanySource
from ai_job_hunter.deduplication.normalization import extract_company_domain, normalize_company_name
from ai_job_hunter.domain.company_intelligence import (
    CompanyEvidenceRecord,
    CompanyEvidenceType,
    CompanyFacts,
    FactStatus,
    company_facts,
)
from ai_job_hunter.models import Company, CompanyEvidence, Job


@dataclass(frozen=True, slots=True)
class CompanyRefreshSummary:
    source_record_counts: dict[str, int]
    companies_created: int
    evidence_created: int
    evidence_updated: int
    companies_with_possible_matches: tuple[str, ...] = ()
    skipped_sources: tuple[SkippedCompanySource, ...] = ()


@dataclass(frozen=True, slots=True)
class CompanyCatalogSummary:
    company_count: int
    evidence_count: int
    companies_with_remote_from_spain: int
    companies_with_public_salary: int
    companies_with_compensation_evidence: int
    companies_with_career_page: int
    companies_with_supported_ats: int
    evidence_by_provider: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class CompanyMonitorFilters:
    spanish_top_tech: bool = False
    remote_from_spain: bool = False
    has_career_page: bool = False
    supported_ats: bool = False
    public_salary: bool = False

    @property
    def is_empty(self) -> bool:
        return not any(
            (
                self.spanish_top_tech,
                self.remote_from_spain,
                self.has_career_page,
                self.supported_ats,
                self.public_salary,
            )
        )


class CompanyIdentityAmbiguous(ValueError):
    """A normalized company name maps to multiple incompatible identities."""


def refresh_company_evidence(
    session: Session,
    batches: tuple[CompanySourceBatch, ...],
    *,
    skipped_sources: tuple[SkippedCompanySource, ...] = (),
) -> CompanyRefreshSummary:
    """Persist imported source facts atomically; repeated rows update the same evidence."""

    source_record_counts = {batch.provider: len(batch.records) for batch in batches}
    companies_created = 0
    evidence_created = 0
    evidence_updated = 0
    possible_matches: set[str] = set()
    # Respect an existing caller-owned transaction (common in request handlers
    # and tests) while keeping a savepoint around this import batch.
    transaction = session.begin_nested() if session.in_transaction() else session.begin()
    with transaction:
        companies = list(session.scalars(select(Company).order_by(Company.id)).all())
        companies_by_name: dict[str, list[Company]] = {}
        companies_by_domain: dict[str, list[Company]] = {}
        for company in companies:
            name_key = normalize_company_name(company.name)
            domain = extract_company_domain(company.website_url)
            if name_key:
                companies_by_name.setdefault(name_key, []).append(company)
            if domain:
                companies_by_domain.setdefault(domain, []).append(company)

        for batch in batches:
            for record in batch.records:
                company, new_company, possible = _find_or_create_company(
                    session,
                    record,
                    companies_by_name=companies_by_name,
                    companies_by_domain=companies_by_domain,
                )
                if new_company:
                    companies_created += 1
                if possible:
                    possible_matches.add(f"{record.company_name}: {', '.join(possible)}")
                existing = session.scalar(
                    select(CompanyEvidence).where(
                        CompanyEvidence.provider == record.provider,
                        CompanyEvidence.evidence_type == record.evidence_type.value,
                        CompanyEvidence.source_key == record.source_key,
                    )
                )
                raw_metadata = dict(record.raw_metadata or {})
                raw_metadata["source_snapshot"] = {
                    "sha256": batch.body_sha256,
                    "file_sha": batch.source_file_sha,
                    "fetched_at": batch.fetched_at.isoformat(),
                    "snapshot_path": str(batch.snapshot_path),
                }
                if existing is None:
                    session.add(
                        CompanyEvidence(
                            company=company,
                            provider=record.provider,
                            evidence_type=record.evidence_type.value,
                            source_key=record.source_key,
                            source_url=record.source_url,
                            external_identifier=record.external_identifier,
                            structured_data=dict(record.structured_data),
                            raw_metadata=raw_metadata,
                        )
                    )
                    evidence_created += 1
                else:
                    existing.company = company
                    existing.source_url = record.source_url
                    existing.external_identifier = record.external_identifier
                    existing.structured_data = dict(record.structured_data)
                    existing.raw_metadata = raw_metadata
                    existing.updated_at = datetime.now(UTC)
                    evidence_updated += 1
                session.flush()

    return CompanyRefreshSummary(
        source_record_counts=source_record_counts,
        companies_created=companies_created,
        evidence_created=evidence_created,
        evidence_updated=evidence_updated,
        companies_with_possible_matches=tuple(sorted(possible_matches)),
        skipped_sources=skipped_sources,
    )


def get_company_facts(session: Session, company_name: str) -> CompanyFacts | None:
    """Resolve by exact conservative identity normalization; never fuzzy-merge."""

    key = normalize_company_name(company_name)
    if key is None:
        return None
    matches = session.scalars(
        select(Company)
        .options(selectinload(Company.evidence_items))
        .order_by(Company.id)
    ).all()
    exact = [company for company in matches if normalize_company_name(company.name) == key]
    if len(exact) > 1:
        raise CompanyIdentityAmbiguous(company_name)
    return company_facts(exact[0]) if exact else None


def get_company_facts_for_job(session: Session, job_id: UUID) -> CompanyFacts | None:
    """Resolve a job's existing company relationship, then derive that company's facts."""

    job = session.scalar(
        select(Job)
        .options(selectinload(Job.company).selectinload(Company.evidence_items))
        .where(Job.id == job_id)
    )
    return company_facts(job.company) if job is not None and job.company is not None else None


def summarize_company_catalog(session: Session) -> CompanyCatalogSummary:
    companies = session.scalars(
        select(Company).options(selectinload(Company.evidence_items)).order_by(Company.name)
    ).all()
    evidence_by_provider = dict(
        session.execute(
            select(CompanyEvidence.provider, func.count(CompanyEvidence.id)).group_by(CompanyEvidence.provider)
        ).all()
    )
    facts = [company_facts(company) for company in companies]
    return CompanyCatalogSummary(
        company_count=len(companies),
        evidence_count=sum(item.evidence_count for item in facts),
        companies_with_remote_from_spain=sum(item.remote_from_spain is FactStatus.YES for item in facts),
        companies_with_public_salary=sum(item.public_salary is FactStatus.YES for item in facts),
        companies_with_compensation_evidence=sum(bool(item.compensation_evidence) for item in facts),
        companies_with_career_page=sum(bool(item.career_pages) for item in facts),
        companies_with_supported_ats=sum(any(page.is_supported for page in item.career_pages) for item in facts),
        evidence_by_provider=evidence_by_provider,
    )


def find_companies_to_monitor(
    session: Session,
    filters: CompanyMonitorFilters,
) -> list[CompanyFacts]:
    if filters.is_empty:
        raise ValueError("At least one structured company-monitor filter is required.")
    companies = session.scalars(
        select(Company).options(selectinload(Company.evidence_items)).order_by(Company.name)
    ).all()
    results: list[CompanyFacts] = []
    for company in companies:
        facts = company_facts(company)
        checks = (
            (not filters.spanish_top_tech or _has_evidence(facts, "compensation", "spanish_top_tech_companies")),
            (not filters.remote_from_spain or facts.remote_from_spain is FactStatus.YES),
            (not filters.has_career_page or bool(facts.career_pages)),
            (not filters.supported_ats or any(page.is_supported for page in facts.career_pages)),
            (not filters.public_salary or facts.public_salary is FactStatus.YES),
        )
        if all(checks):
            results.append(facts)
    return results


def _has_evidence(facts: CompanyFacts, evidence_type: str, provider: str | None = None) -> bool:
    return any(
        item.evidence_type.value == evidence_type and (provider is None or item.provider == provider)
        for item in facts.evidence
    )


def _find_or_create_company(
    session: Session,
    record: CompanyEvidenceRecord,
    *,
    companies_by_name: dict[str, list[Company]],
    companies_by_domain: dict[str, list[Company]],
) -> tuple[Company, bool, list[str]]:
    name_key = normalize_company_name(record.company_name)
    if name_key is None:
        raise ValueError("A company evidence record requires a normalizable company name.")
    domain = extract_company_domain(record.website_url)

    if domain is not None:
        same_domain = companies_by_domain.get(domain, [])
        if len(same_domain) == 1:
            return same_domain[0], False, []
        named_domain_matches = [
            company for company in same_domain if normalize_company_name(company.name) == name_key
        ]
        if len(named_domain_matches) == 1:
            return named_domain_matches[0], False, []

    same_name = companies_by_name.get(name_key, [])
    compatible = [
        company
        for company in same_name
        if domain is None
        or extract_company_domain(company.website_url) is None
        or extract_company_domain(company.website_url) == domain
    ]
    if len(compatible) == 1:
        company = compatible[0]
        if company.website_url is None and record.website_url is not None:
            company.website_url = record.website_url
            companies_by_domain.setdefault(domain or "", []).append(company)
        return company, False, []

    possible = [company.name for company in same_name]
    company = Company(name=record.company_name, website_url=record.website_url)
    session.add(company)
    companies_by_name.setdefault(name_key, []).append(company)
    if domain is not None:
        companies_by_domain.setdefault(domain, []).append(company)
    return company, True, possible
