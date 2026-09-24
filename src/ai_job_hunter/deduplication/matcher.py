"""Explainable matching rules for deciding whether two source records share a job."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID

from ai_job_hunter.deduplication.normalization import (
    extract_company_domain,
    is_job_specific_url,
    normalize_company_name,
    normalize_job_title,
    normalize_job_url,
    normalize_location,
)
from ai_job_hunter.domain.normalized_job import NormalizedJob, RemotePolicy
from ai_job_hunter.models import Job


class DeduplicationDecision(StrEnum):
    """A candidate's deterministic identity assessment."""

    MATCH = "match"
    POSSIBLE_MATCH = "possible_match"
    NO_MATCH = "no_match"


class TitleRelation(StrEnum):
    """Small token-overlap categories; these are not probabilities."""

    EXACT = "exact"
    SIMILAR = "similar"
    DIFFERENT = "different"


@dataclass(frozen=True, slots=True)
class DeduplicationSignals:
    """Evidence used by the matcher for one existing job candidate."""

    company_name_match: bool
    company_domain_match: bool
    company_domain_conflict: bool
    company_conflict: bool
    title_relation: TitleRelation
    seniority_match: bool
    stable_url_match: str | None
    stable_url_conflict: str | None
    location_match: bool | None
    remote_policy_match: bool | None
    remote_policy_conflict: bool
    published_within_14_days: bool | None
    salary_ranges_overlap: bool | None


@dataclass(frozen=True, slots=True)
class DeduplicationResult:
    """Candidate decision with evidence and human-readable reasons."""

    candidate_job_id: UUID
    decision: DeduplicationDecision
    signals: DeduplicationSignals
    reasons: tuple[str, ...]


def match_job(offer: NormalizedJob, candidate: Job) -> DeduplicationResult:
    """Compare an incoming offer with a canonical job and its loaded occurrences.

    Only an exact, job-specific canonical/apply/source URL can produce an
    automatic match. The title, seniority, employer evidence, work arrangement,
    and location must not contradict that URL. Company/title evidence alone is
    surfaced as a possible match and never merges records.
    """

    company_name_key = normalize_company_name(offer.company_name)
    candidate_company_name_key = normalize_company_name(
        candidate.company.name if candidate.company is not None else None
    )
    company_name_match = bool(
        company_name_key
        and candidate_company_name_key
        and company_name_key == candidate_company_name_key
    )

    company_domain = extract_company_domain(offer.company_website)
    candidate_domains = _candidate_company_domains(candidate)
    company_domain_match = bool(company_domain and company_domain in candidate_domains)
    domain_conflict = bool(
        company_domain and candidate_domains and not company_domain_match
    )
    name_conflict = bool(
        company_name_key
        and candidate_company_name_key
        and company_name_key != candidate_company_name_key
        and not company_domain_match
    )
    company_conflict = domain_conflict or name_conflict

    incoming_title = normalize_job_title(offer.title)
    candidate_title = normalize_job_title(candidate.title)
    title_relation = _compare_titles(incoming_title.tokens, candidate_title.tokens)
    seniority_match = incoming_title.seniority == candidate_title.seniority

    stable_url_match = _shared_specific_url(offer, candidate)
    stable_url_conflict = _different_same_kind_urls(offer, candidate)

    incoming_location = normalize_location(offer.location)
    candidate_location = normalize_location(candidate.location)
    location_match = (
        None
        if incoming_location is None or candidate_location is None
        else incoming_location == candidate_location
    )
    candidate_policies = _candidate_remote_policies(candidate)
    incoming_policy = offer.remote_policy.value if offer.remote_policy else None
    remote_policy_match = (
        None
        if incoming_policy is None or not candidate_policies
        else incoming_policy in candidate_policies
    )
    remote_policy_conflict = bool(
        (
            incoming_policy == RemotePolicy.ONSITE.value
            and RemotePolicy.REMOTE.value in candidate_policies
        )
        or (
            incoming_policy == RemotePolicy.REMOTE.value
            and RemotePolicy.ONSITE.value in candidate_policies
        )
    )
    published_within_14_days = _published_dates_are_close(offer, candidate)
    salary_ranges_overlap = _salary_ranges_overlap(offer, candidate)

    signals = DeduplicationSignals(
        company_name_match=company_name_match,
        company_domain_match=company_domain_match,
        company_domain_conflict=domain_conflict,
        company_conflict=company_conflict,
        title_relation=title_relation,
        seniority_match=seniority_match,
        stable_url_match=stable_url_match,
        stable_url_conflict=stable_url_conflict,
        location_match=location_match,
        remote_policy_match=remote_policy_match,
        remote_policy_conflict=remote_policy_conflict,
        published_within_14_days=published_within_14_days,
        salary_ranges_overlap=salary_ranges_overlap,
    )
    reasons = _explain(signals, incoming_title.seniority, candidate_title.seniority)

    if title_relation is TitleRelation.DIFFERENT:
        decision = DeduplicationDecision.NO_MATCH
    elif not seniority_match:
        decision = DeduplicationDecision.NO_MATCH
    elif company_conflict:
        decision = DeduplicationDecision.NO_MATCH
    elif stable_url_conflict is not None:
        decision = DeduplicationDecision.NO_MATCH
    elif signals.remote_policy_conflict:
        decision = DeduplicationDecision.NO_MATCH
    elif location_match is False and not _both_remote(incoming_policy, candidate_policies):
        decision = DeduplicationDecision.NO_MATCH
    elif stable_url_match is not None and remote_policy_match is not False:
        decision = DeduplicationDecision.MATCH
    elif company_name_match or company_domain_match:
        decision = DeduplicationDecision.POSSIBLE_MATCH
    else:
        decision = DeduplicationDecision.NO_MATCH

    return DeduplicationResult(
        candidate_job_id=candidate.id,
        decision=decision,
        signals=signals,
        reasons=reasons,
    )


def _candidate_company_domains(candidate: Job) -> set[str]:
    domains: set[str] = set()
    if candidate.company is not None:
        domain = extract_company_domain(candidate.company.website_url)
        if domain:
            domains.add(domain)
    for source in candidate.sources:
        domain = extract_company_domain(source.company_website)
        if domain:
            domains.add(domain)
    return domains


def _candidate_remote_policies(candidate: Job) -> set[str]:
    policies = {source.remote_policy for source in candidate.sources if source.remote_policy}
    if candidate.remote_policy:
        policies.add(candidate.remote_policy)
    return policies


def _compare_titles(left: frozenset[str], right: frozenset[str]) -> TitleRelation:
    if not left or not right:
        return TitleRelation.DIFFERENT
    if left == right:
        return TitleRelation.EXACT
    intersection = len(left & right)
    union = len(left | right)
    if min(len(left), len(right)) >= 2 and intersection * 3 >= union * 2:
        return TitleRelation.SIMILAR
    return TitleRelation.DIFFERENT


def _shared_specific_url(offer: NormalizedJob, candidate: Job) -> str | None:
    offer_urls = _offer_urls(offer)
    candidate_urls = _candidate_urls(candidate)
    shared = {url for urls in offer_urls.values() for url in urls} & {
        url for urls in candidate_urls.values() for url in urls
    }
    if not shared:
        return None

    for kind in ("canonical_url", "apply_url", "source_url"):
        if offer_urls[kind] & shared:
            return kind
    return None


def _different_same_kind_urls(offer: NormalizedJob, candidate: Job) -> str | None:
    offer_urls = _offer_urls(offer)
    candidate_urls = _candidate_urls(candidate)
    for kind in ("canonical_url", "apply_url"):
        if offer_urls[kind] and candidate_urls[kind] and not offer_urls[kind] & candidate_urls[kind]:
            return kind
    return None


def _offer_urls(offer: NormalizedJob) -> dict[str, set[str]]:
    values = {
        "canonical_url": offer.canonical_url,
        "apply_url": offer.apply_url,
        "source_url": offer.source_url,
    }
    return {
        kind: {normalized}
        if value and is_job_specific_url(value) and (normalized := normalize_job_url(value))
        else set()
        for kind, value in values.items()
    }


def _candidate_urls(candidate: Job) -> dict[str, set[str]]:
    values: dict[str, set[str]] = {
        "canonical_url": set(),
        "apply_url": set(),
        "source_url": set(),
    }
    for source in candidate.sources:
        for kind, value in (
            ("canonical_url", source.canonical_url),
            ("apply_url", source.apply_url),
            ("source_url", source.original_url),
        ):
            normalized = normalize_job_url(value)
            if normalized and is_job_specific_url(value):
                values[kind].add(normalized)
    return values


def _published_dates_are_close(offer: NormalizedJob, candidate: Job) -> bool | None:
    if offer.published_at is None:
        return None
    candidate_dates = [source.published_at for source in candidate.sources if source.published_at]
    if not candidate_dates:
        return None
    incoming = _as_utc(offer.published_at)
    return any(
        abs(incoming - _as_utc(value)) <= timedelta(days=14)
        for value in candidate_dates
    )


def _salary_ranges_overlap(offer: NormalizedJob, candidate: Job) -> bool | None:
    if (
        offer.salary_min is None
        or offer.salary_max is None
        or offer.currency is None
        or offer.salary_period is None
    ):
        return None
    ranges = [
        (source.salary_min, source.salary_max)
        for source in candidate.sources
        if (
            source.salary_min is not None
            and source.salary_max is not None
            and source.salary_currency == offer.currency
            and source.salary_period == offer.salary_period.value
        )
    ]
    if not ranges:
        return None
    return any(offer.salary_min <= salary_max and salary_min <= offer.salary_max for salary_min, salary_max in ranges)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        # SQLite drops timezone info on round-trip; normalized input is UTC-aware.
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _both_remote(incoming_policy: str | None, candidate_policies: set[str]) -> bool:
    return incoming_policy == RemotePolicy.REMOTE.value and RemotePolicy.REMOTE.value in candidate_policies


def _explain(
    signals: DeduplicationSignals,
    incoming_seniority: frozenset[str],
    candidate_seniority: frozenset[str],
) -> tuple[str, ...]:
    reasons: list[str] = []
    if signals.company_name_match:
        reasons.append("same normalized company name")
    if signals.company_domain_match:
        reasons.append("same company website domain")
    if signals.company_conflict:
        if signals.company_domain_conflict:
            reasons.append("company website domain differs")
        if not signals.company_name_match:
            reasons.append("normalized company names differ")
    if signals.title_relation is TitleRelation.EXACT:
        reasons.append("normalized titles are equivalent")
    elif signals.title_relation is TitleRelation.SIMILAR:
        reasons.append("title token overlap is at least two thirds")
    else:
        reasons.append("normalized titles are too different")
    if signals.seniority_match:
        reasons.append("seniority is compatible")
    else:
        incoming = ", ".join(sorted(incoming_seniority)) or "unspecified"
        existing = ", ".join(sorted(candidate_seniority)) or "unspecified"
        reasons.append(f"seniority differs (incoming: {incoming}; existing: {existing})")
    if signals.stable_url_match:
        reasons.append(f"same job-specific {signals.stable_url_match}")
    elif signals.stable_url_conflict:
        reasons.append(f"different job-specific {signals.stable_url_conflict}s")
    else:
        reasons.append("no shared job-specific canonical/apply/source URL")
    if signals.location_match is True:
        reasons.append("normalized locations agree")
    elif signals.location_match is False:
        reasons.append("normalized locations differ")
    if signals.remote_policy_match is True:
        reasons.append("work arrangement agrees")
    elif signals.remote_policy_match is False:
        reasons.append("work arrangement differs")
    if signals.remote_policy_conflict:
        reasons.append("explicit onsite/remote policies conflict")
    if signals.published_within_14_days is True:
        reasons.append("publication dates are within 14 days")
    if signals.salary_ranges_overlap is True:
        reasons.append("salary ranges overlap")
    return tuple(reasons)
