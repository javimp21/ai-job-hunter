"""Explainable fit ranking of known companies, even when they have no matching open role.

Candidates are companies reachable from company leads (resolved to a company)
or from monitored sources that were not rejected. Every factor records where
its evidence came from; a fact we do not have stays UNKNOWN and scores 0.
Hints (curated-list notes, a lead's location hint) earn only partial credit
and are labelled as hints. The score is a review priority (0-100), not a
probability.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ai_job_hunter.candidates.technologies import extract_job_technologies
from ai_job_hunter.domain.company_intelligence import FactStatus, company_facts
from ai_job_hunter.domain.normalized_job import RemoteEligibility
from ai_job_hunter.models import (
    Application,
    ApplicationStatus,
    Company,
    CompanyLead,
    Job,
    JobReview,
    MonitoredSource,
    MonitoredSourceState,
    Outreach,
    OutreachStatus,
)
from ai_job_hunter.models.job_review import HumanReviewStatus

MAX_SCORE = 100
SECTOR_POINTS = 25
SECTOR_HINT_POINTS = 12
PRODUCT_POINTS = 10
PRODUCT_HINT_POINTS = 5
GEOGRAPHY_POINTS = 20
STACK_POINTS = 35
SIZE_POINTS = 10

# Stack tiers requested by the candidate: Java/Spring/Kotlin first, then Python/Go.
PRIMARY_STACK = frozenset({"java", "spring", "spring boot", "kotlin"})
SECONDARY_STACK = frozenset({"python", "go"})

_SECTORS: dict[str, re.Pattern[str]] = {
    "fintech": re.compile(
        r"\bfintech\b|\bpayments?\b|\bpagos\b|\bneobank\b|\binsurtech\b|\bopen banking\b|\bPSD2\b"
        r"|\blending\b|\bpréstamos\b",
        re.IGNORECASE,
    ),
    "AI": re.compile(
        r"\bAI\b|\bartificial intelligence\b|\bmachine learning\b|\bLLMs?\b|\bgenerative\b"
        r"|\binteligencia artificial\b|\baprendizaje autom[aá]tico\b",
        re.IGNORECASE,
    ),
    "banking": re.compile(r"\bbank(?:s|ing)?\b|\bbanca\b|\bbancos?\b", re.IGNORECASE),
    "developer tools": re.compile(
        r"\bdeveloper tools?\b|\bdevtools?\b|\bdeveloper platform\b|\bSDKs?\b|\bobservability\b"
        r"|\bherramientas para desarrolladores\b|\bCI/CD\b|\binfrastructure as code\b",
        re.IGNORECASE,
    ),
}
_PRODUCT_HINT = re.compile(r"\bproduct (?:company|led|-led)\b|\bSaaS\b|\bempresa de producto\b", re.IGNORECASE)
_NOT_PRODUCT = re.compile(
    r"\bconsult(?:ancy|ing)\b|\bconsultora\b|\boutsourc|\bstaffing\b|\bagency\b|\bagencia\b|\bbody.?shop",
    re.IGNORECASE,
)
_NOT_PRODUCT_TYPES = frozenset({"consultancy", "consulting", "agency", "outsourcing", "staffing", "services"})
_MADRID = re.compile(r"\bmadrid\b", re.IGNORECASE)
_SPAIN = re.compile(r"\bspain\b|\bespa[ñn]a\b|\bbarcelona\b|\bvalencia\b|\bsevilla\b|\bm[aá]laga\b|\bbilbao\b", re.IGNORECASE)
_EARLY_BUCKETS = frozenset({"startup", "small_startup", "seed", "pre_seed", "early", "early_stage", "small"})
_EARLY_EMPLOYEES = 30  # below this the draft follows the early-stage rules; 30+ is mid-size.


class CompanyStage(StrEnum):
    EARLY_STAGE = "EARLY_STAGE"
    MID_SIZE = "MID_SIZE"
    UNKNOWN = "UNKNOWN"


class FactorStatus(StrEnum):
    YES = "YES"
    PARTIAL = "PARTIAL"  # only a hint or weaker evidence
    NO = "NO"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class FitFactor:
    name: str
    status: FactorStatus
    points: int
    max_points: int
    reason: str
    provenance: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class PostingEvidence:
    """One stored posting (open or closed) of the company; fields stay None when unknown."""

    title: str
    description: str | None
    location: str | None
    remote_policy: str | None
    remote_eligibility: str | None
    url: str | None = None


@dataclass(frozen=True, slots=True)
class CompanyInputs:
    company_id: UUID
    name: str
    website_url: str | None = None
    description: str | None = None
    # Curated-list text and location hints are hints, never facts.
    lead_notes: tuple[str, ...] = ()
    lead_location_hints: tuple[str, ...] = ()
    lead_sources: tuple[str, ...] = ()
    company_type: str | None = None
    remote_from_spain: FactStatus = FactStatus.UNKNOWN
    remote_from_spain_provenance: tuple[str, ...] = ()
    employee_count: int | None = None
    size_bucket: str | None = None
    size_provenance: str | None = None
    sector_evidence: tuple[str, ...] = ()
    postings: tuple[PostingEvidence, ...] = ()


@dataclass(frozen=True, slots=True)
class CompanyFit:
    company_id: UUID
    name: str
    website_url: str | None
    score: int
    stage: CompanyStage
    factors: tuple[FitFactor, ...]
    unknowns: tuple[str, ...]
    posting_count: int
    lead_sources: tuple[str, ...] = ()

    def explanation(self) -> str:
        return "; ".join(
            f"{factor.name}: {factor.reason} (+{factor.points})" for factor in self.factors if factor.points
        ) or "no positive evidence"


@dataclass(frozen=True, slots=True)
class ExcludedCompany:
    company_id: UUID
    name: str
    reason: str


@dataclass(frozen=True, slots=True)
class RankingResult:
    ranked: tuple[CompanyFit, ...]
    excluded: tuple[ExcludedCompany, ...] = ()
    # Leads that are not linked to a company row yet (resolve them first).
    unresolved_leads: int = 0


def company_stage(employee_count: int | None, size_bucket: str | None) -> CompanyStage:
    if employee_count is not None and employee_count > 0:
        return CompanyStage.EARLY_STAGE if employee_count < _EARLY_EMPLOYEES else CompanyStage.MID_SIZE
    bucket = (size_bucket or "").strip().casefold().replace("-", "_").replace(" ", "_")
    if bucket in _EARLY_BUCKETS:
        return CompanyStage.EARLY_STAGE
    if bucket in {"mid", "mid_size", "midsize", "scaleup", "scale_up", "large", "enterprise"}:
        return CompanyStage.MID_SIZE
    return CompanyStage.UNKNOWN


def score_company(inputs: CompanyInputs) -> CompanyFit:
    """Score one company from the evidence in ``inputs``; pure and deterministic."""

    factors = (
        _sector_factor(inputs),
        _product_factor(inputs),
        _geography_factor(inputs),
        _stack_factor(inputs),
        _size_factor(inputs),
    )
    unknowns = tuple(factor.name for factor in factors if factor.status is FactorStatus.UNKNOWN)
    return CompanyFit(
        company_id=inputs.company_id,
        name=inputs.name,
        website_url=inputs.website_url,
        score=min(MAX_SCORE, sum(factor.points for factor in factors)),
        stage=company_stage(inputs.employee_count, inputs.size_bucket),
        factors=factors,
        unknowns=unknowns,
        posting_count=len(inputs.postings),
        lead_sources=inputs.lead_sources,
    )


def _sector_factor(inputs: CompanyInputs) -> FitFactor:
    for label, texts, points, status in (
        ("company description", (inputs.description or "", *inputs.sector_evidence), SECTOR_POINTS, FactorStatus.YES),
        ("curated-list note (hint)", inputs.lead_notes, SECTOR_HINT_POINTS, FactorStatus.PARTIAL),
    ):
        for sector, pattern in _SECTORS.items():
            if any(pattern.search(text) for text in texts if text):
                return FitFactor(
                    "sector", status, points, SECTOR_POINTS,
                    f"{sector} mentioned in {label}",
                    (label,),
                )
    return FitFactor("sector", FactorStatus.UNKNOWN, 0, SECTOR_POINTS, "no sector evidence (UNKNOWN)")


def _product_factor(inputs: CompanyInputs) -> FitFactor:
    kind = (inputs.company_type or "").strip().casefold()
    if kind:
        if kind in _NOT_PRODUCT_TYPES:
            return FitFactor(
                "product company", FactorStatus.NO, 0, PRODUCT_POINTS,
                f"company type recorded as {kind}", ("company_type evidence",),
            )
        if "product" in kind:
            return FitFactor(
                "product company", FactorStatus.YES, PRODUCT_POINTS, PRODUCT_POINTS,
                f"company type recorded as {kind}", ("company_type evidence",),
            )
    hint_text = " ".join(inputs.lead_notes)
    if hint_text and _NOT_PRODUCT.search(hint_text):
        return FitFactor(
            "product company", FactorStatus.NO, 0, PRODUCT_POINTS,
            "curated-list note suggests services/consulting (hint)", ("curated-list note (hint)",),
        )
    if hint_text and _PRODUCT_HINT.search(hint_text):
        return FitFactor(
            "product company", FactorStatus.PARTIAL, PRODUCT_HINT_POINTS, PRODUCT_POINTS,
            "curated-list note suggests a product company (hint)", ("curated-list note (hint)",),
        )
    return FitFactor("product company", FactorStatus.UNKNOWN, 0, PRODUCT_POINTS, "not recorded (UNKNOWN)")


def _geography_factor(inputs: CompanyInputs) -> FitFactor:
    best: tuple[int, FactorStatus, str, str] | None = None

    def consider(points: int, status: FactorStatus, reason: str, source: str) -> None:
        nonlocal best
        if best is None or points > best[0]:
            best = (points, status, reason, source)

    if inputs.remote_from_spain is FactStatus.YES:
        consider(
            GEOGRAPHY_POINTS, FactorStatus.YES, "remote-from-Spain evidence recorded",
            ", ".join(inputs.remote_from_spain_provenance) or "company evidence",
        )
    for posting in inputs.postings:
        location = posting.location or ""
        where = posting.url or "stored posting"
        if _MADRID.search(location):
            consider(GEOGRAPHY_POINTS, FactorStatus.YES, f"posting located in Madrid ({location})", where)
        elif _SPAIN.search(location):
            consider(15, FactorStatus.YES, f"posting located in Spain ({location})", where)
        eligibility = (posting.remote_eligibility or "").upper()
        if eligibility == RemoteEligibility.SPAIN_ONLY.value:
            consider(GEOGRAPHY_POINTS, FactorStatus.YES, "posting open to remote work from Spain", where)
        elif eligibility in {
            RemoteEligibility.EU_REMOTE.value,
            RemoteEligibility.EMEA_REMOTE.value,
            RemoteEligibility.WORLDWIDE.value,
        }:
            consider(10, FactorStatus.YES, f"posting remote eligibility {eligibility} includes Spain", where)
    if best is None and any(_MADRID.search(h) or _SPAIN.search(h) for h in inputs.lead_location_hints):
        consider(8, FactorStatus.PARTIAL, "lead location hint mentions Spain/Madrid (hint)", "lead location hint")
    if best is None:
        return FitFactor("Spain presence", FactorStatus.UNKNOWN, 0, GEOGRAPHY_POINTS, "no Spain evidence (UNKNOWN)")
    points, status, reason, source = best
    return FitFactor("Spain presence", status, points, GEOGRAPHY_POINTS, reason, (source,))


def stack_matches(inputs: CompanyInputs) -> tuple[list[PostingEvidence], list[PostingEvidence]]:
    """Postings mentioning the primary (Java/Spring/Kotlin) and secondary (Python/Go) stack."""

    primary: list[PostingEvidence] = []
    secondary: list[PostingEvidence] = []
    for posting in inputs.postings:
        found = set(extract_job_technologies(posting.title, posting.description)[0])
        if found & PRIMARY_STACK:
            primary.append(posting)
        elif found & SECONDARY_STACK:
            secondary.append(posting)
    return primary, secondary


def _stack_factor(inputs: CompanyInputs) -> FitFactor:
    if not inputs.postings:
        return FitFactor("stack", FactorStatus.UNKNOWN, 0, STACK_POINTS, "no stored postings to read a stack from (UNKNOWN)")
    primary, secondary = stack_matches(inputs)
    total = len(inputs.postings)
    if primary:
        points = min(STACK_POINTS, 25 + 5 * (len(primary) - 1))
        return FitFactor(
            "stack", FactorStatus.YES, points, STACK_POINTS,
            f"Java/Spring/Kotlin in {len(primary)} of {total} stored postings",
            tuple(dict.fromkeys(p.url for p in primary if p.url))[:3] or ("stored postings",),
        )
    if secondary:
        points = min(20, 12 + 4 * (len(secondary) - 1))
        return FitFactor(
            "stack", FactorStatus.YES, points, STACK_POINTS,
            f"Python/Go in {len(secondary)} of {total} stored postings (no Java/Spring/Kotlin)",
            tuple(dict.fromkeys(p.url for p in secondary if p.url))[:3] or ("stored postings",),
        )
    return FitFactor(
        "stack", FactorStatus.NO, 0, STACK_POINTS,
        f"none of {total} stored postings mentions Java/Spring/Kotlin/Python/Go", ("stored postings",),
    )


def _size_factor(inputs: CompanyInputs) -> FitFactor:
    source = (inputs.size_provenance or "company evidence",)
    if inputs.employee_count is not None and inputs.employee_count > 0:
        count = inputs.employee_count
        if 20 <= count <= 1000:
            return FitFactor("size/stage", FactorStatus.YES, SIZE_POINTS, SIZE_POINTS, f"about {count} employees", source)
        if count < 20 or count <= 5000:
            return FitFactor("size/stage", FactorStatus.PARTIAL, 5, SIZE_POINTS, f"about {count} employees", source)
        return FitFactor("size/stage", FactorStatus.NO, 0, SIZE_POINTS, f"about {count} employees (very large)", source)
    stage = company_stage(None, inputs.size_bucket)
    if stage is not CompanyStage.UNKNOWN:
        return FitFactor(
            "size/stage", FactorStatus.PARTIAL, 5, SIZE_POINTS, f"recorded size bucket {inputs.size_bucket}", source
        )
    return FitFactor("size/stage", FactorStatus.UNKNOWN, 0, SIZE_POINTS, "size not recorded (UNKNOWN)")


# --------------------------------------------------------------------------------------
# Database gathering


def rank_companies(
    session: Session,
    *,
    limit: int | None = None,
    company_ids: Iterable[UUID] | None = None,
) -> RankingResult:
    """Rank leads' companies and companies with monitored sources by explainable fit."""

    leads = session.scalars(select(CompanyLead)).all()
    lead_by_company: dict[UUID, list[CompanyLead]] = {}
    for lead in leads:
        if lead.company_id is not None:
            lead_by_company.setdefault(lead.company_id, []).append(lead)
    unresolved = sum(1 for lead in leads if lead.company_id is None)
    monitored = set(
        session.scalars(
            select(MonitoredSource.company_id).where(
                MonitoredSource.state != MonitoredSourceState.REJECTED.value
            )
        ).all()
    )
    wanted = set(lead_by_company) | monitored
    if company_ids is not None:
        wanted &= set(company_ids)
    if not wanted:
        return RankingResult(ranked=(), unresolved_leads=unresolved)

    companies = session.scalars(
        select(Company)
        .options(
            selectinload(Company.evidence_items),
            selectinload(Company.jobs).selectinload(Job.sources),
        )
        .where(Company.id.in_(wanted))
    ).all()
    blocked = _blocked_companies(session, wanted)
    ranked: list[CompanyFit] = []
    excluded: list[ExcludedCompany] = []
    for company in companies:
        if company.id in blocked:
            excluded.append(ExcludedCompany(company.id, company.name, blocked[company.id]))
            continue
        ranked.append(score_company(company_inputs(company, lead_by_company.get(company.id, []))))
    ranked.sort(key=lambda fit: (-fit.score, -fit.posting_count, fit.name.casefold()))
    excluded.sort(key=lambda item: item.name.casefold())
    positive = tuple(fit for fit in ranked if fit.score > 0)
    return RankingResult(
        ranked=positive[:limit] if limit is not None else positive,
        excluded=tuple(excluded),
        unresolved_leads=unresolved,
    )


def company_inputs(company: Company, leads: Sequence[CompanyLead]) -> CompanyInputs:
    facts = company_facts(company)
    employee_count: int | None = None
    size_bucket: str | None = None
    size_provenance: str | None = None
    sector_evidence: list[str] = []
    for item in company.evidence_items:
        data = item.structured_data or {}
        count = data.get("employee_count")
        if employee_count is None and isinstance(count, int) and not isinstance(count, bool) and count > 0:
            employee_count, size_provenance = count, f"{item.provider} ({item.source_url or 'no url'})"
        bucket = data.get("size_bucket") or data.get("stage")
        if size_bucket is None and isinstance(bucket, str) and bucket.strip():
            size_bucket = bucket.strip()
            size_provenance = size_provenance or f"{item.provider} ({item.source_url or 'no url'})"
        for key in ("sector", "industry", "description"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                sector_evidence.append(value.strip())
    postings = tuple(
        PostingEvidence(
            title=source.source_title or job.title,
            description=source.source_description or job.description,
            location=source.source_location or job.location,
            remote_policy=source.remote_policy or job.remote_policy,
            remote_eligibility=source.remote_eligibility,
            url=source.canonical_url or source.original_url,
        )
        for job in company.jobs
        for source in job.sources
    )
    # Jobs whose sources were all removed still carry their own fields.
    postings += tuple(
        PostingEvidence(job.title, job.description, job.location, job.remote_policy, None)
        for job in company.jobs
        if not job.sources
    )
    return CompanyInputs(
        company_id=company.id,
        name=company.name,
        website_url=company.website_url or next((lead.website_url for lead in leads if lead.website_url), None),
        description=company.description,
        lead_notes=tuple(text for lead in leads for text in (lead.notes, lead.hiring_hint) if text),
        lead_location_hints=tuple(lead.location_hint for lead in leads if lead.location_hint),
        lead_sources=tuple(dict.fromkeys(f"{lead.source_label}" for lead in leads)),
        company_type=facts.company_type,
        remote_from_spain=facts.remote_from_spain,
        remote_from_spain_provenance=tuple(
            dict.fromkeys(
                f"{item.provider}" for item in facts.evidence if item.evidence_type.value == "remote_from_spain"
            )
        ),
        employee_count=employee_count,
        size_bucket=size_bucket,
        size_provenance=size_provenance,
        sector_evidence=tuple(sector_evidence),
        postings=postings,
    )


_DISMISS_COMPANY_REASONS = frozenset({"company", "not_interesting"})


def _blocked_companies(session: Session, company_ids: set[UUID]) -> dict[UUID, str]:
    """Companies the candidate already applied to, dismissed, or who declined outreach."""

    blocked: dict[UUID, str] = {}
    applied = session.execute(
        select(Job.company_id).join(Application, Application.job_id == Job.id).where(
            Job.company_id.in_(company_ids),
            Application.status != ApplicationStatus.DRAFT.value,
        )
    ).all()
    for (company_id,) in applied:
        blocked[company_id] = "already applied"
    reviews = session.execute(
        select(Job.company_id, Job.id, JobReview.state, JobReview.reason)
        .outerjoin(JobReview, JobReview.job_id == Job.id)
        .where(Job.company_id.in_(company_ids))
    ).all()
    per_company: dict[UUID, list[tuple[str | None, str | None]]] = {}
    for company_id, _job_id, state, reason in reviews:
        per_company.setdefault(company_id, []).append((state, reason))
    for company_id, rows in per_company.items():
        if company_id in blocked:
            continue
        dismissed = [(state, reason) for state, reason in rows if state == HumanReviewStatus.DISMISSED.value]
        if any(reason in _DISMISS_COMPANY_REASONS for _state, reason in dismissed):
            blocked[company_id] = "dismissed (company-level reason)"
        elif rows and len(dismissed) == len(rows):
            blocked[company_id] = "every known job dismissed"
    declined = session.scalars(
        select(Outreach.company_id).where(
            Outreach.company_id.in_(company_ids), Outreach.status == OutreachStatus.DECLINED.value
        )
    ).all()
    for company_id in declined:
        blocked.setdefault(company_id, "outreach declined")
    return blocked


def describe(fit: CompanyFit) -> dict[str, Any]:
    """Plain structure for CLI/JSON output."""

    return {
        "company_id": str(fit.company_id),
        "name": fit.name,
        "score": fit.score,
        "stage": fit.stage.value,
        "unknown": list(fit.unknowns),
        "factors": [
            {"name": f.name, "status": f.status.value, "points": f.points, "reason": f.reason}
            for f in fit.factors
        ],
    }
