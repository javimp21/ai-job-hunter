"""Persistence, conservative identity resolution, and queries for company evidence."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Iterable
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from ai_job_hunter.ats_discovery import discover_ats_url
from ai_job_hunter.company_sources import CompanySourceBatch, REMOTE_ES, SkippedCompanySource
from ai_job_hunter.deduplication.normalization import (
    extract_company_domain,
    normalize_company_name,
)
from ai_job_hunter.domain.company_intelligence import (
    ATSDiscoveryConfidence,
    ATSProvider,
    CompanyEvidenceRecord,
    CompanyEvidenceType,
    CompanyFacts,
    CompanyMonitorTarget,
    FactStatus,
    company_facts,
)
from ai_job_hunter.domain.normalized_job import NormalizedJob
from ai_job_hunter.models import Company, CompanyEvidence, Job
from ai_job_hunter.models.job_source import JobSource


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
class ATSObservationSummary:
    sources_examined: int
    companies_with_observed_ats: int
    evidence_created: int
    evidence_updated: int


@dataclass(frozen=True, slots=True)
class CompanyMonitorFilters:
    spanish_top_tech: bool = False
    remote_from_spain: bool = False
    has_career_page: bool = False
    supported_ats: bool = False
    public_salary: bool = False
    compensation_evidence: bool = False
    multiple_evidence_sources: bool = False

    @property
    def is_empty(self) -> bool:
        return not any(
            (
                self.spanish_top_tech,
                self.remote_from_spain,
                self.has_career_page,
                self.supported_ats,
                self.public_salary,
                self.compensation_evidence,
                self.multiple_evidence_sources,
            )
        )


class CompanyIdentityAmbiguous(ValueError):
    """A normalized company name maps to multiple incompatible identities."""


@dataclass(frozen=True, slots=True)
class CompanyEvidenceUpsert:
    company: Company
    created: bool
    updated: bool
    possible_matches: tuple[str, ...] = ()


def upsert_company_evidence_record(
    session: Session,
    record: CompanyEvidenceRecord,
    *,
    raw_metadata: dict | None = None,
) -> CompanyEvidenceUpsert:
    """Persist one evidence record through Company Intelligence identity matching."""

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

    company, _new_company, possible = _find_or_create_company(
        session,
        record,
        companies_by_name=companies_by_name,
        companies_by_domain=companies_by_domain,
    )
    existing = session.scalar(
        select(CompanyEvidence).where(
            CompanyEvidence.provider == record.provider,
            CompanyEvidence.evidence_type == record.evidence_type.value,
            CompanyEvidence.source_key == record.source_key,
        )
    )
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
                raw_metadata=dict(raw_metadata or {}) or None,
            )
        )
        created, updated = True, False
    else:
        existing.company = company
        existing.source_url = record.source_url
        existing.external_identifier = record.external_identifier
        existing.structured_data = dict(record.structured_data)
        existing.raw_metadata = dict(raw_metadata or {}) or None
        existing.updated_at = datetime.now(UTC)
        created, updated = False, True
    session.flush()
    return CompanyEvidenceUpsert(
        company=company,
        created=created,
        updated=updated,
        possible_matches=tuple(possible),
    )


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
        companies_with_supported_ats=sum(
            any(discovery.is_supported for discovery in item.ats_discoveries)
            for item in facts
        ),
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
            (not filters.has_career_page or bool(facts.career_pages or facts.ats_discoveries)),
            (not filters.supported_ats or any(item.is_supported for item in facts.ats_discoveries)),
            (not filters.public_salary or facts.public_salary is FactStatus.YES),
            (not filters.compensation_evidence or bool(facts.compensation_evidence)),
            (not filters.multiple_evidence_sources or facts.source_count > 1),
        )
        if all(checks):
            results.append(facts)
    return results


def company_matches_filters(facts: CompanyFacts, filters: CompanyMonitorFilters) -> bool:
    """True when the company's evidence satisfies every enabled monitor filter."""

    checks = (
        (not filters.spanish_top_tech or _has_evidence(facts, "compensation", "spanish_top_tech_companies")),
        (not filters.remote_from_spain or facts.remote_from_spain is FactStatus.YES),
        (not filters.has_career_page or bool(facts.career_pages or facts.ats_discoveries)),
        (not filters.public_salary or facts.public_salary is FactStatus.YES),
        (not filters.compensation_evidence or bool(facts.compensation_evidence)),
        (not filters.multiple_evidence_sources or facts.source_count > 1),
    )
    return all(checks)


def build_company_monitor_targets(
    session: Session,
    filters: CompanyMonitorFilters,
    *,
    company_name: str | None = None,
    provider: ATSProvider | None = None,
    limit_companies: int = 10,
) -> list[CompanyMonitorTarget]:
    """Build bounded public-board targets from supported, identified ATS facts."""

    if limit_companies < 1:
        raise ValueError("limit_companies must be positive")
    name_key = normalize_company_name(company_name) if company_name else None
    if company_name and name_key is None:
        raise ValueError("company_name must contain a normalizable name")
    if filters.is_empty and name_key is None and provider is None:
        raise ValueError("At least one company filter is required to build monitor targets.")

    companies = session.scalars(
        select(Company).options(selectinload(Company.evidence_items)).order_by(Company.name)
    ).all()
    targets: list[CompanyMonitorTarget] = []
    included_company_ids: set[UUID] = set()
    seen_targets: set[tuple[UUID, ATSProvider, str, str | None]] = set()
    for company in companies:
        if name_key is not None and normalize_company_name(company.name) != name_key:
            continue
        facts = company_facts(company)
        if not company_matches_filters(facts, filters):
            continue

        company_targets: list[CompanyMonitorTarget] = []
        for discovery in facts.ats_discoveries:
            if not discovery.is_supported or (provider is not None and discovery.provider is not provider):
                continue
            identifier = discovery.identifier
            assert identifier is not None
            key = (company.id, discovery.provider, identifier.casefold(), discovery.region)
            if key in seen_targets:
                continue
            careers_url = discovery.source_url or public_board_url(
                discovery.provider, identifier, discovery.region
            )
            company_targets.append(
                CompanyMonitorTarget(
                    company_id=company.id,
                    company_name=company.name,
                    provider=discovery.provider,
                    identifier=identifier,
                    region=discovery.region,
                    careers_url=careers_url,
                    evidence_source=(
                        "observed_job_source"
                        if discovery.confidence is ATSDiscoveryConfidence.OBSERVED_JOB_SOURCE
                        else "career_url"
                    ),
                    confidence=discovery.confidence,
                )
            )
        if not company_targets:
            continue
        if company.id not in included_company_ids and len(included_company_ids) >= limit_companies:
            break
        included_company_ids.add(company.id)
        for target in company_targets:
            targets.append(target)
            seen_targets.add((target.company_id, target.provider, target.identifier.casefold(), target.region))
    return targets


def sync_ats_evidence_from_job_sources(
    session: Session,
    *,
    normalized_jobs: Iterable[NormalizedJob] | None = None,
    source_label: str = "persisted_job_source",
) -> ATSObservationSummary:
    """Record observed ATS boards from persisted JobSources or an existing normalized snapshot."""

    if normalized_jobs is None:
        job_sources = session.scalars(
            select(JobSource)
            .options(selectinload(JobSource.job).selectinload(Job.company))
            .where(JobSource.provider.in_(("greenhouse", "lever", "ashby", "teamtailor", "recruitee", "smartrecruiters", "workable", "personio", "workday", "factorial", "amazon_jobs")))
            .order_by(JobSource.provider, JobSource.id)
        ).all()
        observations = [
            _observation_from_job_source(source)
            for source in job_sources
            if source.job is not None and source.job.company is not None
        ]
    else:
        observations = [_observation_from_normalized_job(job) for job in normalized_jobs]
    observations = [observation for observation in observations if observation is not None]
    if not observations:
        return ATSObservationSummary(0, 0, 0, 0)

    grouped: dict[tuple[str, str, str | None, str | None], list[dict[str, object]]] = defaultdict(list)
    source_by_group: dict[tuple[str, str, str | None, str | None], tuple[str, str | None, UUID | None]] = {}
    for observation in observations:
        key = (
            observation["company_identity"],
            observation["provider"],
            observation["identifier"],
            observation["region"],
        )
        grouped[key].append(observation["supporting_job_source"])
        source_by_group[key] = (
            observation["company_name"],
            observation["company_website"],
            observation["company_id"],
        )

    created = 0
    updated = 0
    companies_observed: set[str] = set()
    transaction = session.begin_nested() if session.in_transaction() else session.begin()
    with transaction:
        companies = list(session.scalars(select(Company).order_by(Company.id)).all())
        companies_by_name: dict[str, list[Company]] = {}
        companies_by_domain: dict[str, list[Company]] = {}
        for company in companies:
            name = normalize_company_name(company.name)
            domain = extract_company_domain(company.website_url)
            if name:
                companies_by_name.setdefault(name, []).append(company)
            if domain:
                companies_by_domain.setdefault(domain, []).append(company)

        for group, support_rows in grouped.items():
            company_name, website_url, company_id = source_by_group[group]
            company = session.get(Company, company_id) if company_id is not None else None
            if company is None:
                identity_record = CompanyEvidenceRecord(
                    provider="observed_job_source",
                    evidence_type=CompanyEvidenceType.ATS_OBSERVED,
                    source_key="pending-identity",
                    company_name=company_name,
                    website_url=website_url,
                )
                company, _created, _possible = _find_or_create_company(
                    session,
                    identity_record,
                    companies_by_name=companies_by_name,
                    companies_by_domain=companies_by_domain,
                )
                session.flush()
            _, ats_provider, identifier, region = group
            source_key = ":".join(
                (
                    company.id.hex,
                    ats_provider,
                    identifier or "unresolved",
                    region or "default",
                )
            )
            merged_support: dict[str, dict[str, object]] = {}
            existing = session.scalar(
                select(CompanyEvidence).where(
                    CompanyEvidence.provider == "observed_job_source",
                    CompanyEvidence.evidence_type == CompanyEvidenceType.ATS_OBSERVED.value,
                    CompanyEvidence.source_key == source_key,
                )
            )
            if existing is not None:
                previous = (existing.structured_data or {}).get("supporting_job_sources", [])
                if isinstance(previous, list):
                    for ref in previous:
                        if isinstance(ref, dict) and isinstance(ref.get("reference_key"), str):
                            merged_support[ref["reference_key"]] = ref
            for ref in support_rows:
                reference_key = str(ref["reference_key"])
                merged_support[reference_key] = ref
            sorted_support = [merged_support[key] for key in sorted(merged_support)]
            structured_data = {
                "ats_provider": ats_provider.upper(),
                "identifier": identifier,
                "region": region,
                "supporting_job_sources": sorted_support,
                "observation_basis": source_label,
            }
            source_url = next(
                (ref.get("source_url") for ref in sorted_support if ref.get("source_url")),
                None,
            )
            if existing is None:
                session.add(
                    CompanyEvidence(
                        company=company,
                        provider="observed_job_source",
                        source_key=source_key,
                        source_url=source_url,
                        external_identifier=identifier,
                        evidence_type=CompanyEvidenceType.ATS_OBSERVED.value,
                        structured_data=structured_data,
                        raw_metadata={"observation_basis": source_label},
                    )
                )
                created += 1
            else:
                existing.structured_data = structured_data
                existing.source_url = source_url
                existing.external_identifier = identifier
                existing.raw_metadata = {"observation_basis": source_label}
                existing.updated_at = datetime.now(UTC)
                updated += 1
            companies_observed.add(company.id.hex)
            session.flush()
    return ATSObservationSummary(len(observations), len(companies_observed), created, updated)


def _observation_from_job_source(source: JobSource) -> dict[str, object] | None:
    company = source.job.company
    if company is None:
        return None
    urls = (source.canonical_url, source.original_url, source.apply_url)
    return _make_ats_observation(
        company_name=company.name,
        company_website=company.website_url,
        company_id=company.id,
        provider=source.provider,
        external_id=source.external_id,
        urls=urls,
        discovered_at=source.discovered_at,
        reference_key=f"job_source:{source.id}",
        job_id=source.job_id,
        job_source_id=source.id,
    )


def _observation_from_normalized_job(job: NormalizedJob) -> dict[str, object] | None:
    if not job.company_name:
        return None
    return _make_ats_observation(
        company_name=job.company_name,
        company_website=job.company_website,
        company_id=None,
        provider=job.provider,
        external_id=job.external_id,
        urls=(job.canonical_url, job.source_url, job.apply_url),
        discovered_at=job.discovered_at,
        reference_key=f"snapshot:{job.provider}:{job.external_id or job.source_url or job.canonical_url}",
        job_id=None,
        job_source_id=None,
    )


def _make_ats_observation(
    *,
    company_name: str,
    company_website: str | None,
    company_id: UUID | None,
    provider: str,
    external_id: str | None,
    urls: tuple[str | None, ...],
    discovered_at: datetime | None,
    reference_key: str,
    job_id: UUID | None,
    job_source_id: UUID | None,
) -> dict[str, object] | None:
    try:
        ats_provider = ATSProvider(provider.strip().upper())
    except ValueError:
        return None
    if ats_provider is ATSProvider.UNKNOWN:
        return None
    url_discoveries = [discover_ats_url(url) for url in urls if url]
    matching_url = next((result for result in url_discoveries if result.provider is ats_provider), None)
    identifier = matching_url.identifier if matching_url else None
    region = matching_url.region if matching_url else ("global" if ats_provider is ATSProvider.LEVER else None)
    source_url = matching_url.source_url if matching_url else next((url for url in urls if url), None)
    ref = {
        "reference_key": reference_key,
        "provider": ats_provider.value.casefold(),
        "external_id": external_id,
        "job_id": str(job_id) if job_id else None,
        "job_source_id": str(job_source_id) if job_source_id else None,
        "source_url": source_url,
        "discovered_at": discovered_at.isoformat() if discovered_at else None,
    }
    identity = normalize_company_name(company_name)
    if identity is None:
        return None
    return {
        "company_identity": company_id.hex if company_id else identity,
        "company_name": company_name,
        "company_website": company_website,
        "company_id": company_id,
        "provider": ats_provider.value.casefold(),
        "identifier": identifier,
        "region": region,
        "supporting_job_source": ref,
    }


def public_board_url(provider: ATSProvider, identifier: str, region: str | None) -> str:
    from urllib.parse import quote

    slug = quote(identifier, safe="")
    if provider is ATSProvider.GREENHOUSE:
        return f"https://boards.greenhouse.io/{slug}"
    if provider is ATSProvider.LEVER:
        host = "jobs.eu.lever.co" if region == "eu" else "jobs.lever.co"
        return f"https://{host}/{slug}"
    if provider is ATSProvider.TEAMTAILOR:
        return f"https://{slug}.teamtailor.com/jobs"
    if provider is ATSProvider.RECRUITEE:
        return f"https://{slug}.recruitee.com"
    if provider is ATSProvider.SMARTRECRUITERS:
        return f"https://jobs.smartrecruiters.com/{slug}"
    if provider is ATSProvider.WORKABLE:
        return f"https://apply.workable.com/{slug}"
    if provider is ATSProvider.WORKDAY:
        from ai_job_hunter.connectors.workday import workday_board_url

        return workday_board_url(identifier, region or "wd1")
    if provider is ATSProvider.PERSONIO:
        return f"https://{slug}.jobs.personio.{'com' if region == 'com' else 'de'}"
    if provider is ATSProvider.FACTORIAL:
        return f"https://{slug}.factorial.es" if region == "es" else f"https://{slug}.factorialhr.com"
    if provider is ATSProvider.CAREERS_SITE:
        from ai_job_hunter.connectors.careers_site import careers_site_board_url

        return careers_site_board_url(identifier)
    if provider is ATSProvider.AMAZON_JOBS:
        return "https://www.amazon.jobs/en/"
    return f"https://jobs.ashbyhq.com/{slug}"


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
