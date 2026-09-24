"""Conservative geographic, salary, seniority, and stack evaluation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

from ai_job_hunter.candidates.facts import JobFacts
from ai_job_hunter.candidates.profile import (
    CandidateConfig,
    CandidateProfile,
    CandidatePreferences,
    RemotePreference,
    SENIORITY_ORDER,
    SeniorityLevel,
)
from ai_job_hunter.candidates.technologies import (
    TECHNOLOGY_FAMILY,
    normalize_technology_list,
)
from ai_job_hunter.deduplication.normalization import normalize_job_title
from ai_job_hunter.domain.normalized_job import (
    EmploymentType,
    RemoteEligibility,
    RemotePolicy,
)


class PreFilterDecision(StrEnum):
    PASS = "PASS"
    REVIEW = "REVIEW"
    REJECT = "REJECT"


class SignalStatus(StrEnum):
    COMPATIBLE = "COMPATIBLE"
    INCOMPATIBLE = "INCOMPATIBLE"
    UNKNOWN = "UNKNOWN"


class SalaryEvaluation(StrEnum):
    BELOW_MINIMUM = "BELOW_MINIMUM"
    BETWEEN_MINIMUM_AND_TARGET = "BETWEEN_MINIMUM_AND_TARGET"
    MEETS_TARGET = "MEETS_TARGET"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class SignalAssessment:
    status: SignalStatus
    reason: str


@dataclass(frozen=True, slots=True)
class SalaryAssessment:
    evaluation: SalaryEvaluation
    reason: str


@dataclass(frozen=True, slots=True)
class TechnologyMatch:
    matching_primary_skills: tuple[str, ...]
    matching_secondary_skills: tuple[str, ...]
    matching_candidate_technologies: tuple[str, ...]
    matching_preferred_technologies: tuple[str, ...]
    missing_technologies: tuple[str, ...]
    learnable_technologies: tuple[str, ...]
    transferable_technologies: tuple[str, ...]
    critical_mismatches: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class JobPreFilterSignals:
    geography: SignalAssessment
    salary: SalaryAssessment
    seniority: SignalAssessment
    employment_type: SignalAssessment
    remote_preference: SignalAssessment
    preferred_role: SignalAssessment
    preferred_location: SignalAssessment
    technology: TechnologyMatch


@dataclass(frozen=True, slots=True)
class JobPreFilterResult:
    decision: PreFilterDecision
    reasons: tuple[str, ...]
    signals: JobPreFilterSignals


@dataclass(frozen=True, slots=True)
class _Country:
    name: str
    aliases: tuple[str, ...]


_COUNTRIES = (
    _Country("Spain", ("spain", "españa", "es")),
    _Country("United States", ("united states of america", "united states", "usa", "us")),
    _Country("Canada", ("canada", "ca")),
    _Country("United Kingdom", ("united kingdom", "great britain", "uk", "gb")),
    _Country("Ireland", ("ireland", "ie")),
    _Country("Germany", ("germany", "de")),
    _Country("France", ("france", "fr")),
    _Country("Netherlands", ("netherlands", "the netherlands", "nl")),
    _Country("Portugal", ("portugal", "pt")),
    _Country("Italy", ("italy", "it")),
    _Country("Sweden", ("sweden", "se")),
    _Country("Denmark", ("denmark", "dk")),
    _Country("Finland", ("finland", "fi")),
    _Country("Norway", ("norway", "no")),
    _Country("Poland", ("poland", "pl")),
    _Country("Belgium", ("belgium", "be")),
    _Country("Switzerland", ("switzerland", "ch")),
    _Country("Austria", ("austria", "at")),
    _Country("Luxembourg", ("luxembourg", "lu")),
    _Country("Greece", ("greece", "gr")),
    _Country("Czechia", ("czechia", "czech republic", "cz")),
    _Country("Romania", ("romania", "ro")),
    _Country("Bulgaria", ("bulgaria", "bg")),
    _Country("Estonia", ("estonia", "ee")),
    _Country("Latvia", ("latvia", "lv")),
    _Country("Lithuania", ("lithuania", "lt")),
    _Country("Croatia", ("croatia", "hr")),
    _Country("Cyprus", ("cyprus", "cy")),
    _Country("Malta", ("malta", "mt")),
    _Country("Slovakia", ("slovakia", "sk")),
    _Country("Slovenia", ("slovenia", "si")),
    _Country("Hungary", ("hungary", "hu")),
    _Country("Iceland", ("iceland", "is")),
    _Country("Australia", ("australia", "au")),
    _Country("New Zealand", ("new zealand", "nz")),
    _Country("India", ("india", "in")),
    _Country("Brazil", ("brazil", "br")),
    _Country("Argentina", ("argentina", "ar")),
    _Country("Mexico", ("mexico", "mx")),
    _Country("Singapore", ("singapore", "sg")),
    _Country("Japan", ("japan", "jp")),
    _Country("China", ("china", "cn")),
    _Country("Israel", ("israel", "il")),
    _Country("Turkey", ("turkey", "türkiye", "tr")),
    _Country("United Arab Emirates", ("united arab emirates", "uae", "ae")),
    _Country("South Africa", ("south africa", "za")),
)
_ALIAS_TO_COUNTRY = {
    alias: country.name
    for country in _COUNTRIES
    for alias in country.aliases
}
_COUNTRY_PATTERNS = tuple(
    (alias, re.compile(rf"(?<![a-z]){re.escape(alias)}(?![a-z])", re.IGNORECASE))
    for alias in sorted(_ALIAS_TO_COUNTRY, key=len, reverse=True)
)
_EU_COUNTRIES = {
    "Austria",
    "Belgium",
    "Bulgaria",
    "Croatia",
    "Cyprus",
    "Czechia",
    "Denmark",
    "Estonia",
    "Finland",
    "France",
    "Germany",
    "Greece",
    "Hungary",
    "Ireland",
    "Italy",
    "Latvia",
    "Lithuania",
    "Luxembourg",
    "Malta",
    "Netherlands",
    "Poland",
    "Portugal",
    "Romania",
    "Slovakia",
    "Slovenia",
    "Spain",
    "Sweden",
}
_EMEA_COUNTRIES = _EU_COUNTRIES | {
    "United Kingdom",
    "Norway",
    "Switzerland",
    "Iceland",
    "Turkey",
    "Israel",
    "United Arab Emirates",
    "South Africa",
}
_EUROPE_COUNTRIES = _EU_COUNTRIES | {
    "United Kingdom",
    "Norway",
    "Switzerland",
    "Iceland",
    "Turkey",
}
_BACKEND_SKILL = re.compile(
    r"\b(?:back\s*end|backend|software\s+(?:engineering|development)|"
    r"api\s+development|distributed\s+systems)\b",
    re.IGNORECASE,
)


def evaluate_job(facts: JobFacts, candidate: CandidateConfig) -> JobPreFilterResult:
    """Evaluate one job deterministically and explain every non-neutral signal."""

    profile = candidate.profile
    preferences = candidate.preferences
    geography = _evaluate_geography(facts, candidate)
    salary = _evaluate_salary(facts, preferences)
    seniority = _evaluate_seniority(facts.inferred_seniority, preferences)
    employment = _evaluate_employment(facts.employment_type, preferences)
    remote = _evaluate_remote_preference(facts.remote_policy, preferences.remote_preference)
    if profile.remote_work_capability is False and facts.remote_policy is RemotePolicy.REMOTE:
        remote = SignalAssessment(
            SignalStatus.INCOMPATIBLE,
            "The candidate profile says remote work is not currently feasible.",
        )
    role = _evaluate_role(facts.title, preferences)
    location = _evaluate_preferred_location(facts.location, preferences)
    technology = _evaluate_technology(facts, profile, preferences)

    signals = JobPreFilterSignals(
        geography=geography,
        salary=salary,
        seniority=seniority,
        employment_type=employment,
        remote_preference=remote,
        preferred_role=role,
        preferred_location=location,
        technology=technology,
    )
    hard_mismatches: list[str] = []
    review_reasons: list[str] = []

    for label, assessment in (
        ("Geography", geography),
        ("Seniority", seniority),
        ("Employment type", employment),
        ("Remote preference", remote),
    ):
        if assessment.status is SignalStatus.INCOMPATIBLE:
            hard_mismatches.append(assessment.reason)
        elif assessment.status is SignalStatus.UNKNOWN:
            if label != "Seniority" or (
                preferences.minimum_seniority is not None
                or preferences.maximum_seniority is not None
            ):
                review_reasons.append(assessment.reason)

    if salary.evaluation is SalaryEvaluation.BELOW_MINIMUM:
        hard_mismatches.append(salary.reason)
    elif salary.evaluation is SalaryEvaluation.UNKNOWN and (
        preferences.minimum_salary is not None or preferences.target_salary is not None
    ):
        review_reasons.append(salary.reason)

    if technology.critical_mismatches:
        hard_mismatches.extend(
            f"Explicit required technology '{tech}' is absent and has no recorded transferable or learnable match."
            for tech in technology.critical_mismatches
        )
    elif technology.missing_technologies:
        if technology.learnable_technologies:
            review_reasons.append(
                "Some mentioned technologies are gaps the candidate is willing to learn: "
                + ", ".join(technology.learnable_technologies)
                + "."
            )
        if technology.transferable_technologies:
            review_reasons.append(
                "Some stack gaps have a recorded transferable technology foundation: "
                + ", ".join(technology.transferable_technologies)
                + "."
            )
        remaining_gaps = set(technology.missing_technologies) - set(
            technology.learnable_technologies
        ) - set(technology.transferable_technologies)
        if remaining_gaps:
            review_reasons.append(
                "Mentioned technologies are not in the candidate profile: "
                + ", ".join(sorted(remaining_gaps))
                + ". Mentions alone are not treated as mandatory requirements."
            )
    elif not facts.technologies and (
        profile.primary_skills or profile.secondary_skills or profile.technologies
    ):
        review_reasons.append("The offer does not explicitly mention a technology to compare.")

    if role.status is SignalStatus.UNKNOWN and preferences.preferred_roles:
        review_reasons.append(role.reason)
    if location.status is SignalStatus.UNKNOWN and preferences.preferred_locations:
        review_reasons.append(location.reason)
    elif location.status is SignalStatus.INCOMPATIBLE:
        # Preferred locations influence ranking, while acceptable locations are
        # handled as geographic constraints only for onsite/hybrid roles.
        review_reasons.append(location.reason)

    if hard_mismatches:
        decision = PreFilterDecision.REJECT
        reasons = tuple(hard_mismatches + review_reasons)
    elif review_reasons:
        decision = PreFilterDecision.REVIEW
        reasons = tuple(review_reasons)
    else:
        decision = PreFilterDecision.PASS
        reasons = ("No configured hard mismatch or material unknown signal was found.",)
    return JobPreFilterResult(decision=decision, reasons=reasons, signals=signals)


def _evaluate_geography(facts: JobFacts, candidate: CandidateConfig) -> SignalAssessment:
    profile = candidate.profile
    preferences = candidate.preferences
    current_countries = _countries_in((profile.current_country,))
    eligible_countries = _countries_in(
        (*profile.eligible_countries, *profile.work_authorization)
    )
    known_countries = current_countries | eligible_countries
    offer_countries = _countries_in((facts.location,))

    if facts.remote_policy in {RemotePolicy.ONSITE, RemotePolicy.HYBRID}:
        if preferences.acceptable_locations:
            if _location_matches(facts.location, preferences.acceptable_locations):
                return SignalAssessment(
                    SignalStatus.COMPATIBLE,
                    "Offer location matches an explicitly acceptable location.",
                )
            if facts.location:
                return SignalAssessment(
                    SignalStatus.INCOMPATIBLE,
                    f"Onsite/hybrid location '{facts.location}' is outside acceptable_locations.",
                )
        if profile.current_city and _location_matches(facts.location, (profile.current_city,)):
            return SignalAssessment(
                SignalStatus.COMPATIBLE,
                "Onsite/hybrid location matches the candidate's current city.",
            )
        if not offer_countries:
            return SignalAssessment(
                SignalStatus.UNKNOWN,
                "Onsite/hybrid location is missing or not recognized by the local country list.",
            )
        if offer_countries & current_countries:
            return SignalAssessment(
                SignalStatus.COMPATIBLE,
                "Onsite/hybrid location is in the candidate's current country.",
            )
        if (
            preferences.relocation_willingness
            and offer_countries & eligible_countries
        ):
            return SignalAssessment(
                SignalStatus.COMPATIBLE,
                "Onsite/hybrid location is in an eligible country and relocation is allowed.",
            )
        if known_countries:
            return SignalAssessment(
                SignalStatus.INCOMPATIBLE,
                "Onsite/hybrid location is outside the candidate's current or eligible countries.",
            )
        return SignalAssessment(SignalStatus.UNKNOWN, "Candidate country is not configured.")

    if facts.remote_eligibility is RemoteEligibility.WORLDWIDE:
        return SignalAssessment(SignalStatus.COMPATIBLE, "Worldwide remote eligibility includes the candidate.")
    if facts.remote_eligibility is RemoteEligibility.SPAIN_ONLY:
        if "Spain" in current_countries:
            return SignalAssessment(SignalStatus.COMPATIBLE, "Spain-only remote role matches the candidate's country.")
        if preferences.relocation_willingness and "Spain" in eligible_countries:
            return SignalAssessment(SignalStatus.COMPATIBLE, "Spain-only remote role is reachable after permitted relocation.")
        if current_countries:
            return SignalAssessment(SignalStatus.INCOMPATIBLE, "Spain-only remote role does not include the candidate's current country.")
        return SignalAssessment(SignalStatus.UNKNOWN, "Spain-only remote role cannot be checked without the candidate's country.")
    if facts.remote_eligibility is RemoteEligibility.EU_REMOTE:
        if current_countries & _EU_COUNTRIES:
            return SignalAssessment(SignalStatus.COMPATIBLE, "EU remote eligibility includes the candidate's country.")
        if preferences.relocation_willingness and eligible_countries & _EU_COUNTRIES:
            return SignalAssessment(SignalStatus.COMPATIBLE, "EU remote role matches an eligible country and relocation is allowed.")
        if current_countries:
            return SignalAssessment(SignalStatus.INCOMPATIBLE, "EU remote eligibility does not include the candidate's current country.")
        return SignalAssessment(SignalStatus.UNKNOWN, "EU remote eligibility cannot be checked without the candidate's country.")
    if facts.remote_eligibility is RemoteEligibility.EMEA_REMOTE:
        if current_countries & _EMEA_COUNTRIES:
            return SignalAssessment(SignalStatus.COMPATIBLE, "EMEA remote eligibility includes the candidate's country.")
        if preferences.relocation_willingness and eligible_countries & _EMEA_COUNTRIES:
            return SignalAssessment(SignalStatus.COMPATIBLE, "EMEA remote role matches an eligible country and relocation is allowed.")
        if current_countries:
            return SignalAssessment(SignalStatus.INCOMPATIBLE, "EMEA remote eligibility does not include the candidate's current country.")
        return SignalAssessment(SignalStatus.UNKNOWN, "EMEA remote eligibility cannot be checked without the candidate's country.")

    if facts.remote_eligibility is RemoteEligibility.COUNTRY_RESTRICTED or (
        facts.remote_policy is RemotePolicy.REMOTE and offer_countries
    ):
        restricted_countries = offer_countries | _remote_region_countries(facts.location)
        if not restricted_countries:
            return SignalAssessment(SignalStatus.UNKNOWN, "Remote country restriction is not recognized.")
        if restricted_countries & current_countries:
            return SignalAssessment(SignalStatus.COMPATIBLE, "Remote country restriction includes the candidate's current country.")
        if not preferences.international_remote_openness and current_countries:
            return SignalAssessment(
                SignalStatus.INCOMPATIBLE,
                "The remote role is restricted to another country and international remote work is disabled in preferences.",
            )
        if preferences.relocation_willingness and restricted_countries & eligible_countries:
            return SignalAssessment(SignalStatus.COMPATIBLE, "Remote country restriction matches an eligible country and relocation is allowed.")
        if known_countries:
            return SignalAssessment(SignalStatus.INCOMPATIBLE, "Remote country restriction excludes the candidate's current and eligible countries.")
        return SignalAssessment(SignalStatus.UNKNOWN, "Remote country restriction cannot be checked without candidate country data.")

    return SignalAssessment(
        SignalStatus.UNKNOWN,
        "Remote eligibility is unknown; the offer is retained for review.",
    )


def _evaluate_salary(facts: JobFacts, preferences: CandidatePreferences) -> SalaryAssessment:
    minimum = preferences.minimum_salary
    target = preferences.target_salary
    if minimum is None and target is None:
        return SalaryAssessment(SalaryEvaluation.UNKNOWN, "No salary threshold is configured.")
    if (
        facts.salary_min is None and facts.salary_max is None
    ) or facts.currency != preferences.salary_currency or facts.salary_period != preferences.salary_period:
        return SalaryAssessment(
            SalaryEvaluation.UNKNOWN,
            "Salary is absent or its currency/period does not match the configured threshold; no conversion was applied.",
        )

    floor = minimum if minimum is not None else target
    threshold = target if target is not None else floor
    assert floor is not None and threshold is not None
    if facts.salary_max is not None and facts.salary_max < floor:
        return SalaryAssessment(
            SalaryEvaluation.BELOW_MINIMUM,
            f"Published salary range ends at {facts.salary_max} {facts.currency} per {facts.salary_period.value.lower()}, below the configured floor of {floor}.",
        )
    if facts.salary_min is not None and facts.salary_min >= threshold:
        return SalaryAssessment(
            SalaryEvaluation.MEETS_TARGET,
            f"Published salary starts at {facts.salary_min} {facts.currency} per {facts.salary_period.value.lower()}, meeting the configured target of {threshold}.",
        )
    return SalaryAssessment(
        SalaryEvaluation.BETWEEN_MINIMUM_AND_TARGET,
        "Published salary range reaches the configured floor but does not guarantee the target.",
    )


def _evaluate_seniority(
    level: SeniorityLevel,
    preferences: CandidatePreferences,
) -> SignalAssessment:
    if preferences.minimum_seniority is None and preferences.maximum_seniority is None:
        return SignalAssessment(SignalStatus.COMPATIBLE, "No seniority boundary is configured.")
    if level is SeniorityLevel.UNKNOWN:
        return SignalAssessment(SignalStatus.UNKNOWN, "Offer seniority is unknown; configured seniority boundaries need review.")
    if (
        preferences.minimum_seniority is not None
        and SENIORITY_ORDER[level] < SENIORITY_ORDER[preferences.minimum_seniority]
    ):
        return SignalAssessment(SignalStatus.INCOMPATIBLE, f"Offer seniority {level.value} is below the configured minimum.")
    if (
        preferences.maximum_seniority is not None
        and SENIORITY_ORDER[level] > SENIORITY_ORDER[preferences.maximum_seniority]
    ):
        return SignalAssessment(SignalStatus.INCOMPATIBLE, f"Offer seniority {level.value} is above the configured maximum.")
    return SignalAssessment(SignalStatus.COMPATIBLE, f"Offer seniority {level.value} is within configured boundaries.")


def _evaluate_employment(
    employment_type: EmploymentType | None,
    preferences: CandidatePreferences,
) -> SignalAssessment:
    if not preferences.acceptable_employment_types:
        return SignalAssessment(SignalStatus.COMPATIBLE, "No employment type restriction is configured.")
    if employment_type is None:
        return SignalAssessment(SignalStatus.UNKNOWN, "Offer employment type is unknown.")
    if employment_type in preferences.acceptable_employment_types:
        return SignalAssessment(SignalStatus.COMPATIBLE, f"Employment type {employment_type.value} is acceptable.")
    return SignalAssessment(SignalStatus.INCOMPATIBLE, f"Employment type {employment_type.value} is outside the configured acceptable types.")


def _evaluate_remote_preference(
    policy: RemotePolicy | None,
    preference: RemotePreference,
) -> SignalAssessment:
    if preference is RemotePreference.ANY:
        return SignalAssessment(SignalStatus.COMPATIBLE, "No work-mode restriction is configured.")
    if policy is None:
        return SignalAssessment(SignalStatus.UNKNOWN, "Offer work mode is unknown for the configured remote preference.")
    accepted = {
        RemotePreference.REMOTE_ONLY: {RemotePolicy.REMOTE},
        RemotePreference.HYBRID_OR_REMOTE: {RemotePolicy.HYBRID, RemotePolicy.REMOTE},
        RemotePreference.ONSITE_OR_HYBRID: {RemotePolicy.ONSITE, RemotePolicy.HYBRID},
        RemotePreference.ONSITE_ONLY: {RemotePolicy.ONSITE},
    }[preference]
    if policy in accepted:
        return SignalAssessment(SignalStatus.COMPATIBLE, f"Work mode {policy.value} matches the configured preference.")
    return SignalAssessment(SignalStatus.INCOMPATIBLE, f"Work mode {policy.value} conflicts with the configured {preference.value} preference.")


def _evaluate_role(title: str, preferences: CandidatePreferences) -> SignalAssessment:
    if not preferences.preferred_roles:
        return SignalAssessment(SignalStatus.COMPATIBLE, "No preferred role keywords are configured.")
    title_tokens = normalize_job_title(title).tokens
    for role in preferences.preferred_roles:
        role_tokens = normalize_job_title(role).tokens
        if role_tokens and role_tokens <= title_tokens:
            return SignalAssessment(
                SignalStatus.COMPATIBLE,
                f"Offer title contains all normalized role terms from '{role}'.",
            )
    return SignalAssessment(
        SignalStatus.UNKNOWN,
        "Offer title has no complete normalized preferred-role match.",
    )


def _evaluate_preferred_location(
    location: str | None,
    preferences: CandidatePreferences,
) -> SignalAssessment:
    if not preferences.preferred_locations:
        return SignalAssessment(SignalStatus.COMPATIBLE, "No preferred location is configured.")
    if location is None:
        return SignalAssessment(SignalStatus.UNKNOWN, "Offer location is missing for preferred-location comparison.")
    if _location_matches(location, preferences.preferred_locations):
        return SignalAssessment(SignalStatus.COMPATIBLE, "Offer location matches a preferred location.")
    return SignalAssessment(SignalStatus.UNKNOWN, "Offer does not explicitly match a preferred location; preference is informational only.")


def _evaluate_technology(
    facts: JobFacts,
    profile: CandidateProfile,
    preferences: CandidatePreferences,
) -> TechnologyMatch:
    primary = normalize_technology_list(profile.primary_skills)
    secondary = normalize_technology_list(profile.secondary_skills)
    technologies = normalize_technology_list(profile.technologies)
    learnable = normalize_technology_list(preferences.willing_to_learn_technologies)
    preferred = normalize_technology_list(preferences.preferred_technologies)
    detected = set(facts.technologies)
    supported = primary | secondary | technologies
    missing = detected - supported
    learnable_matches = missing & learnable
    transferable = {
        tech for tech in missing - learnable_matches
        if _has_transferable_foundation(tech, supported, (*profile.primary_skills, *profile.secondary_skills))
    }
    critical = (set(facts.required_technologies) & missing) - learnable_matches - transferable
    return TechnologyMatch(
        matching_primary_skills=tuple(sorted(detected & primary)),
        matching_secondary_skills=tuple(sorted(detected & secondary)),
        matching_candidate_technologies=tuple(sorted(detected & technologies)),
        matching_preferred_technologies=tuple(sorted(detected & preferred)),
        missing_technologies=tuple(sorted(missing)),
        learnable_technologies=tuple(sorted(learnable_matches)),
        transferable_technologies=tuple(sorted(transferable)),
        critical_mismatches=tuple(sorted(critical)),
    )


def _has_transferable_foundation(
    technology: str,
    supported: frozenset[str],
    candidate_skills: Iterable[str],
) -> bool:
    family = TECHNOLOGY_FAMILY.get(technology)
    if family and any(TECHNOLOGY_FAMILY.get(item) == family for item in supported):
        return True
    if family in {"language", "jvm_framework", "javascript_runtime", "javascript_framework"}:
        return any(_BACKEND_SKILL.search(skill) for skill in candidate_skills)
    return False


def _location_matches(location: str | None, allowed: Iterable[str]) -> bool:
    if not location:
        return False
    folded_location = " ".join(location.casefold().split())
    for value in allowed:
        normalized = " ".join(value.casefold().split())
        if normalized and normalized in folded_location:
            return True
    listing_countries = _countries_in((location,))
    allowed_values = {" ".join(value.casefold().split()) for value in allowed}
    allowed_countries = _countries_in(allowed)
    if listing_countries & allowed_countries:
        return True
    if allowed_values & {"eu", "europe", "european union"}:
        if listing_countries & _EU_COUNTRIES:
            return True
    if allowed_values & {"emea", "europe middle east africa"}:
        if listing_countries & _EMEA_COUNTRIES:
            return True
    return False


def _countries_in(values: Iterable[str | None]) -> set[str]:
    result: set[str] = set()
    for value in values:
        if not value:
            continue
        folded = value.casefold()
        for alias, pattern in _COUNTRY_PATTERNS:
            if pattern.search(folded):
                result.add(_ALIAS_TO_COUNTRY[alias])
    return result


def _remote_region_countries(location: str | None) -> set[str]:
    """Expand explicit EU/Europe/EMEA eligibility labels to their countries."""

    if not location:
        return set()
    folded = location.casefold()
    result: set[str] = set()
    if re.search(r"\b(?:eu|european union)\b", folded):
        result.update(_EU_COUNTRIES)
    if re.search(r"\beurope\b", folded):
        result.update(_EUROPE_COUNTRIES)
    if re.search(r"\bemea\b", folded):
        result.update(_EMEA_COUNTRIES)
    return result
