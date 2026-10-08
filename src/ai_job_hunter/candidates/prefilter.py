"""Conservative geographic, salary, seniority, and stack evaluation."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum
from typing import Iterable

from ai_job_hunter.sectors.engine import classify_role_family, get_template
from ai_job_hunter.candidates.experience import ExperienceAssessment, ExperienceOutcome, assess_experience
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


class RoleFamilyFit(StrEnum):
    TARGET = "TARGET"
    POTENTIALLY_RELEVANT = "POTENTIALLY_RELEVANT"
    NON_TARGET = "NON_TARGET"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class SignalAssessment:
    status: SignalStatus
    reason: str


@dataclass(frozen=True, slots=True)
class RoleFamilyAssessment:
    fit: RoleFamilyFit
    family: str
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


_NO_TECHNOLOGY = TechnologyMatch((), (), (), (), (), (), (), ())


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
    experience: ExperienceAssessment
    role_family: RoleFamilyAssessment


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
    _Country("South Korea", ("south korea", "republic of korea", "korea", "kr")),
    _Country("Indonesia", ("indonesia", "id")),
    _Country("Malaysia", ("malaysia", "my")),
    _Country("Philippines", ("philippines", "ph")),
    _Country("Thailand", ("thailand", "th")),
    _Country("Vietnam", ("vietnam", "viet nam", "vn")),
    _Country("Taiwan", ("taiwan", "tw")),
    _Country("Hong Kong", ("hong kong", "hk")),
    _Country("Pakistan", ("pakistan", "pk")),
    _Country("Bangladesh", ("bangladesh", "bd")),
    _Country("Nepal", ("nepal", "np")),
    _Country("Sri Lanka", ("sri lanka", "lk")),
    _Country("Myanmar", ("myanmar", "burma", "mm")),
    _Country("Cambodia", ("cambodia", "kh")),
    _Country("Laos", ("laos", "lao pdr", "la")),
    _Country("Mongolia", ("mongolia", "mn")),
    _Country("Japan", ("japan", "jp")),
    _Country("China", ("china", "cn")),
    _Country("Israel", ("israel", "il")),
    _Country("Turkey", ("turkey", "türkiye", "tr")),
    _Country("United Arab Emirates", ("united arab emirates", "uae", "ae")),
    _Country("South Africa", ("south africa", "za")),
    # Full names only for these: their two-letter codes are common words.
    _Country("Serbia", ("serbia",)),
    _Country("Ukraine", ("ukraine",)),
    _Country("Costa Rica", ("costa rica",)),
    _Country("Colombia", ("colombia",)),
    _Country("Chile", ("chile",)),
    _Country("Peru", ("peru",)),
    _Country("Uruguay", ("uruguay",)),
    _Country("Egypt", ("egypt",)),
    _Country("Nigeria", ("nigeria",)),
    _Country("Kenya", ("kenya",)),
    _Country("Morocco", ("morocco",)),
    _Country("Saudi Arabia", ("saudi arabia",)),
    _Country("Qatar", ("qatar",)),
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
_CODE_PATTERNS = {
    alias: re.compile(rf"(?<![A-Za-z]){alias.upper()}(?![A-Za-z])")
    for alias in _ALIAS_TO_COUNTRY
    if len(alias) == 2
}
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
_APAC_COUNTRIES = {
    "Australia",
    "Bangladesh",
    "Cambodia",
    "China",
    "Hong Kong",
    "India",
    "Indonesia",
    "Japan",
    "Laos",
    "Malaysia",
    "Mongolia",
    "Myanmar",
    "Nepal",
    "New Zealand",
    "Pakistan",
    "Philippines",
    "Singapore",
    "South Korea",
    "Sri Lanka",
    "Taiwan",
    "Thailand",
    "Vietnam",
}
_BACKEND_SKILL = re.compile(
    r"\b(?:back\s*end|backend|software\s+(?:engineering|development)|"
    r"api\s+development|distributed\s+systems)\b",
    re.IGNORECASE,
)
_NON_TECHNICAL_ROLE_MARKERS = {
    "designer": "design",
    "legal": "legal",
    "counsel": "legal",
    "attorney": "legal",
    "lawyer": "legal",
    "marketing": "marketing",
    "marketer": "marketing",
    "sales": "sales",
    "recruiter": "recruiting / HR",
    "recruiting": "recruiting / HR",
    "recruitment": "recruiting / HR",
    "hr": "recruiting / HR",
    "hrbp": "recruiting / HR",
    "finance": "finance",
    "accountant": "finance",
    "accounting": "finance",
    "operations": "operations",
    "community": "community",
    "producer": "production",
    "copywriter": "content",
    "writer": "content",
    "growth": "growth",
    "support": "customer support",
    "success": "customer success",
    # Unambiguous Spanish title markers.
    "ventas": "sales",
    "rrhh": "recruiting / HR",
    "reclutador": "recruiting / HR",
    "reclutadora": "recruiting / HR",
    "abogado": "legal",
    "abogada": "legal",
    "contable": "finance",
    "disenador": "design",
    "disenadora": "design",
    # Healthcare roles occasionally appear on tech companies' boards.
    "nurse": "healthcare",
    "physician": "healthcare",
    "doctor": "healthcare",
    "clinician": "healthcare",
    "pharmacist": "healthcare",
    "therapist": "healthcare",
    "dentist": "healthcare",
    "gtm": "go-to-market",
}
# Tokens naming an engineering job (not a technical domain such as "security"
# or "data"). Titles without one cannot be rescued by a domain word alone.
_ENGINEERING_JOB_TOKENS = {
    "engineer", "engineering", "programmer", "programming", "sre", "devops",
    "ingeniero", "ingeniera", "programador", "programadora", "desarrollador",
    "desarrolladora",
    # German, French, Italian, Portuguese and Croatian equivalents.
    "entwickler", "softwareentwickler", "ingenieur", "informatiker", "developpeur",
    "developpeuse", "sviluppatore", "desenvolvedor", "programer", "inzenjer",
}
_GOVERNANCE_TOKENS = {"governance", "compliance", "grc", "audit", "auditor", "risk"}
_ANALYST_TOKENS = {"analyst", "analista"}
_SCIENCE_TOKENS = {
    "scientist", "researcher", "cientifico", "cientifica", "investigador", "investigadora",
}
_AI_TOKENS = {"ai", "genai", "llm", "llms", "ml", "mlops"}
_ML_SPECIALTY_TOKENS = {"vision", "nlp", "deep", "cv"}
_DATA_TOKENS = {"data", "datos", "analytics"}
_CUSTOMER_FACING_ENGINEERING_TOKENS = {"field", "fde", "solutions", "solution", "forward", "deployed"}
_CORE_SOFTWARE_TOKENS = {
    "backend", "software", "fullstack", "api", "devtools", "sre", "devops",
}
_PLATFORM_TOKENS = {"platform", "infrastructure", "infra", "cloud"}
# Compound spellings are expanded both ways so "Back End" matches "Backend".
_TITLE_COMPOUNDS = (
    ({"back", "end"}, "backend"),
    ({"full", "stack"}, "fullstack"),
    ({"machine", "learning"}, "ml"),
    ({"gen", "ai"}, "genai"),
    ({"inteligencia", "artificial"}, "ai"),
    ({"artificial", "intelligence"}, "ai"),
)
_TECHNICAL_ROLE_MARKERS = {
    "engineer", "engineering", "developer", "software", "backend", "back",
    "end", "platform", "infrastructure", "devops", "devtools", "data",
    "database", "security", "systems", "programmer", "programming", "sre",
    "ai", "ml", "machine", "learning", "cloud", "api", "full", "stack",
    "technical", "tech", "technology", "architect", "architecture", "qa", "cto",
    "frontend", "fullstack", "mobile", "ios", "android", "web", "network",
    "postgres", "kubernetes", "java", "python", "golang", "rust",
}
_LEGACY_UNRELATED_ROLE = re.compile(
    r"^[\W_]*(?:(?:senior|junior|mid|lead|staff|principal|freelance|contract|temporary|"
    r"inbound|outbound|inside|field|technical|virtual|remote)\s+)*(?:sales|ventas|account executive|"
    r"business development|customer (?:support|service|success)|copywriter|writer|"
    r"content creator|social media manager|office assistant|administrative assistant|"
    r"executive assistant|virtual assistant|kundenservice|kundensupport|kundenbetreuung|"
    r"kundendienst|atenci[oó]n al cliente|servicio al cliente|service client|"
    r"assistance clientèle|assistenza clienti)\b",
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
    role_family = _classify_role_family(facts.title, preferences.sector)
    location =_evaluate_preferred_location(facts.location, preferences)
    # The technology vocabulary is software's: a sector without a stack neither compares nor penalizes technologies.
    compares_technology = get_template(preferences.sector).template.stack is not None
    technology = _evaluate_technology(facts, profile, preferences) if compares_technology else _NO_TECHNOLOGY
    experience = assess_experience(
        facts.experience_requirements,
        profile.years_of_experience,
        floor_shortfall_tolerance=preferences.experience_floor_shortfall_tolerance,
        range_shortfall_tolerance=preferences.experience_range_shortfall_tolerance,
    )

    signals = JobPreFilterSignals(
        geography=geography,
        salary=salary,
        seniority=seniority,
        employment_type=employment,
        remote_preference=remote,
        preferred_role=role,
        preferred_location=location,
        technology=technology,
        experience=experience,
        role_family=role_family,
    )
    hard_mismatches: list[str] = []
    review_reasons: list[str] = []
    if experience.outcome is ExperienceOutcome.INCOMPATIBLE:
        hard_mismatches.append(experience.reason + " " + experience.requirement_display)
    elif experience.outcome is not ExperienceOutcome.MEETS:
        review_reasons.append(experience.reason + " " + experience.requirement_display)

    if role_family.fit is RoleFamilyFit.NON_TARGET:
        hard_mismatches.append(role_family.reason)
    elif role_family.fit is RoleFamilyFit.POTENTIALLY_RELEVANT:
        review_reasons.append(role_family.reason)

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

    if (
        not preferences.accept_offers_without_salary
        and facts.salary_min is None
        and facts.salary_max is None
    ):
        hard_mismatches.append("The offer publishes no salary and the candidate asked not to receive those.")
    elif salary.evaluation is SalaryEvaluation.BELOW_MINIMUM:
        hard_mismatches.append(salary.reason)
    elif salary.evaluation is SalaryEvaluation.UNKNOWN and (
        preferences.minimum_salary is not None or preferences.target_salary is not None
    ):
        review_reasons.append(salary.reason)

    if not compares_technology:
        pass
    elif technology.critical_mismatches:
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


def _role_tokens(title: str, *, include_seniority: bool = True) -> frozenset[str]:
    """Normalized title tokens plus both spellings of known compound role words."""

    normalized = normalize_job_title(title)
    tokens = set(normalized.tokens | normalized.seniority if include_seniority else normalized.tokens)
    for parts, compound in _TITLE_COMPOUNDS:
        if parts <= tokens:
            tokens.add(compound)
        elif compound in tokens and compound not in {"ml", "ai"}:
            tokens |= parts
    return frozenset(tokens)


def title_may_be_relevant(title: str, sector: str = "software") -> bool:
    """Cheap title gate for expensive per-job fetches: False only for non-target families of the sector."""

    return _classify_role_family(title, sector).fit is not RoleFamilyFit.NON_TARGET


def _classify_role_family(title: str, sector: str = "software") -> RoleFamilyAssessment:
    """The title's role family according to the sector template (``src/ai_job_hunter/sectors/templates/<sector>.json``).

    Ambiguous families are left for review; the rules live in the template, see ``sectors/engine.py``.
    """

    result = classify_role_family(title, sector)
    return RoleFamilyAssessment(RoleFamilyFit(result.fit), result.family, result.reason)


def _classify_role_family_legacy(title: str) -> RoleFamilyAssessment:
    """The original hard-coded cascade, kept only to prove the software template equivalent (tests).

    Only explicit title evidence is used. Families whose fit depends on the
    actual work (data, AI/ML, customer-facing engineering) are never rejected
    here: the description decides, through review.
    """

    non_target = _clearly_non_technical_role(title)
    if non_target:
        return RoleFamilyAssessment(
            RoleFamilyFit.NON_TARGET,
            non_target,
            f"Title belongs to the non-target {non_target} role family.",
        )
    tokens = _role_tokens(title)
    if not tokens & _ENGINEERING_JOB_TOKENS:
        return RoleFamilyAssessment(
            RoleFamilyFit.UNKNOWN,
            "unclassified",
            "Title does not name a recognized engineering role family.",
        )

    def potentially_relevant(family: str, focus: str) -> RoleFamilyAssessment:
        return RoleFamilyAssessment(
            RoleFamilyFit.POTENTIALLY_RELEVANT,
            family,
            f"Role family '{family}' is only potentially relevant; review whether the work is {focus}.",
        )

    software_focus = "mainly software/backend engineering"
    if tokens & (_AI_TOKENS | _ML_SPECIALTY_TOKENS):
        if tokens & _ML_SPECIALTY_TOKENS:
            return potentially_relevant("ML specialist (vision/NLP/deep learning)", software_focus)
        if tokens & _CORE_SOFTWARE_TOKENS:
            return RoleFamilyAssessment(
                RoleFamilyFit.TARGET,
                "software/backend engineering (AI domain)",
                "Title names a software/backend engineering role in an AI domain.",
            )
        if tokens & _PLATFORM_TOKENS:
            return potentially_relevant("AI/ML platform engineering", "platform, serving or tooling engineering")
        if "ml" in tokens and not tokens & {"ai", "genai", "llm", "llms"}:
            return potentially_relevant("machine learning engineering", "software-heavy rather than model research")
        # The candidate targets AI engineering (software around models: APIs,
        # RAG, agents, evaluation) as a main family since 2026-10-04.
        return RoleFamilyAssessment(
            RoleFamilyFit.TARGET,
            "AI engineering",
            "Title names an AI engineering role (software around models).",
        )
    if tokens & _DATA_TOKENS:
        family = "analytics engineering" if "analytics" in tokens else "data engineering"
        return potentially_relevant(family, "software-heavy (pipelines, data platform, distributed systems)")
    if {"forward", "deployed"} <= tokens or "fde" in tokens:
        # Forward deployed engineering is a target family; solutions/field
        # engineering stays a review case (often pre-sales).
        return RoleFamilyAssessment(
            RoleFamilyFit.TARGET,
            "forward deployed engineering",
            "Title names a forward deployed engineering role.",
        )
    if tokens & _CUSTOMER_FACING_ENGINEERING_TOKENS:
        return potentially_relevant("customer-facing engineering", software_focus)
    if "research" in tokens:
        return potentially_relevant("research engineering", software_focus)
    if tokens & (_CORE_SOFTWARE_TOKENS | _PLATFORM_TOKENS):
        return RoleFamilyAssessment(
            RoleFamilyFit.TARGET,
            "software/backend/platform engineering",
            "Title names a software, backend or platform engineering role.",
        )
    return RoleFamilyAssessment(
        RoleFamilyFit.UNKNOWN,
        "other engineering",
        "Title names an engineering role outside the recognized target families.",
    )


_HARDWARE_TOKENS = {"hardware", "avionics", "mechanical", "electrical", "camera", "drone", "optical"}
_BUSINESS_DEVELOPMENT = re.compile(r"\bbusiness\s+develop(?:er|ment)\b", re.IGNORECASE)


def _clearly_non_technical_role(title: str) -> str | None:
    """Classify explicit non-technical title families using normalized title tokens."""

    tokens = _role_tokens(title)
    engineering_job = bool(tokens & _ENGINEERING_JOB_TOKENS)
    # Sales and support titles remain out of scope even when their names contain
    # the word "engineer" (for example, Sales Engineer).
    for marker in (
        "sales", "ventas", "support", "success", "designer", "legal", "counsel", "attorney",
        "lawyer", "marketing", "marketer", "recruiter", "recruiting", "recruitment",
        "hr", "hrbp", "finance", "accountant", "accounting", "community", "producer",
        "copywriter", "writer", "rrhh", "reclutador", "reclutadora", "abogado",
        "abogada", "contable", "disenador", "disenadora", "nurse", "physician",
        "doctor", "clinician", "pharmacist", "therapist", "dentist",
    ):
        if marker in tokens:
            if marker in {"sales", "ventas"} and tokens & _TECHNICAL_ROLE_MARKERS:
                if not _LEGACY_UNRELATED_ROLE.search(title):
                    continue
            return _NON_TECHNICAL_ROLE_MARKERS[marker]

    # Hardware disciplines ("Avionics Hardware Engineer", "Camera Engineer")
    # are out of scope unless the title also names software work.
    if tokens & _HARDWARE_TOKENS and not tokens & _CORE_SOFTWARE_TOKENS:
        return "hardware engineering"

    # A technical domain word ("security", "data") does not make a governance,
    # analyst or scientist title an engineering job; an engineering noun does.
    if not engineering_job:
        if tokens & _GOVERNANCE_TOKENS:
            return "governance / risk / compliance"
        if tokens & _ANALYST_TOKENS:
            return "non-engineering analyst"
        if tokens & _SCIENCE_TOKENS:
            return "science / research"
        if "comercial" in tokens:
            return "sales"
        if "gtm" in tokens or {"go", "market"} <= tokens:
            return "go-to-market"
    if "research" in tokens and tokens & (_AI_TOKENS | _ML_SPECIALTY_TOKENS):
        return "ML research"

    # Product management is its own family; "product engineer" remains technical.
    if {"product", "manager"} <= tokens:
        return "product management"
    # Role tokens fold "developer" into "engineer", so match the raw title.
    if _BUSINESS_DEVELOPMENT.search(title):
        return "business development"
    if "account" in tokens and ({"executive", "manager"} & tokens):
        return "sales"

    # Operations and growth can occur in technical titles; only reject when no
    # engineering/software family marker disambiguates them.
    technical = bool(tokens & _TECHNICAL_ROLE_MARKERS)
    engineering_context = bool(
        tokens & (_TECHNICAL_ROLE_MARKERS - {"engineer", "engineering"})
    )
    # Talent pools and spontaneous applications are not a concrete role, even
    # when they mention engineering ("Engineering Talent Pool").
    if {"talent", "pool"} <= tokens or (
        tokens & {"spontaneous", "espontanea", "unsolicited"} and tokens & {"application", "candidatura"}
    ):
        return "unscoped application"
    # A title with no engineering noun and no technical term in any supported
    # language ("Freelance Prodajni Predstavnik", "Steuerfachangestellte",
    # "Human Resources Business Partner") is not a technical role.
    if not tokens & (_ENGINEERING_JOB_TOKENS | _TECHNICAL_ROLE_MARKERS):
        return "non-technical (no technical term in title)"
    if not technical:
        if "product" in tokens:
            return "product"
        if "analyst" in tokens:
            return "non-engineering analyst"
        if ("open" in tokens or "general" in tokens) and "application" in tokens:
            return "unscoped application"
        if ("solution" in tokens or "solutions" in tokens) and "consultant" in tokens:
            return "solutions consulting"
    if not engineering_context:
        if "operations" in tokens:
            return "operations"
        if "growth" in tokens:
            return "growth"
    if not technical:
        if "commercial" in tokens and ({"head", "director", "manager"} & tokens):
            return "commercial"
        if {"office", "assistant"} <= tokens or {"administrative", "assistant"} <= tokens:
            return "administrative support"
    if _LEGACY_UNRELATED_ROLE.search(title):
        return "sales / customer service / administrative support"
    return None


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

    explicit_remote_location = bool(
        facts.location and re.search(r"\bremote\b", facts.location, re.IGNORECASE)
    )
    if explicit_remote_location:
        restricted_countries = _countries_in((facts.location,)) | _remote_region_countries(
            facts.location
        )
        if restricted_countries:
            return _assess_country_restriction(
                restricted_countries,
                current_countries,
                eligible_countries,
                known_countries,
                preferences,
                mode="remote",
            )
        if facts.location and re.search(
            r"\b(?:global|worldwide)\b", facts.location, re.IGNORECASE
        ):
            if facts.remote_eligibility is RemoteEligibility.COUNTRY_RESTRICTED:
                return SignalAssessment(
                    SignalStatus.UNKNOWN,
                    "Remote eligibility is marked country-restricted but no permitted country is identified.",
                )
            return SignalAssessment(
                SignalStatus.COMPATIBLE,
                "Explicit global remote eligibility includes the candidate's country.",
            )
        if facts.remote_eligibility not in {
            RemoteEligibility.WORLDWIDE,
            RemoteEligibility.SPAIN_ONLY,
            RemoteEligibility.EU_REMOTE,
            RemoteEligibility.EMEA_REMOTE,
        }:
            return SignalAssessment(
                SignalStatus.UNKNOWN,
                "Explicit remote location does not identify an eligible country or region.",
            )

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
        return _assess_country_restriction(
            restricted_countries,
            current_countries,
            eligible_countries,
            known_countries,
            preferences,
            mode="remote",
        )

    if facts.remote_policy is RemotePolicy.REMOTE:
        return SignalAssessment(
            SignalStatus.UNKNOWN,
            "Remote eligibility is unknown; the offer is retained for review.",
        )

    # A specific city/country without an explicit remote label is a location
    # restriction even when an ATS omitted the work-mode field.
    if offer_countries:
        if preferences.acceptable_locations and _location_matches(
            facts.location, preferences.acceptable_locations
        ):
            return SignalAssessment(
                SignalStatus.COMPATIBLE,
                "Offer location matches an explicitly acceptable location.",
            )
        if profile.current_city and _location_matches(facts.location, (profile.current_city,)):
            return SignalAssessment(
                SignalStatus.COMPATIBLE,
                "Offer location matches the candidate's current city.",
            )
        return _assess_country_restriction(
            offer_countries,
            current_countries,
            eligible_countries,
            known_countries,
            preferences,
            mode="listed",
        )

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
    title_tokens = _role_tokens(title, include_seniority=False)
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


def _fold_accents(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return " ".join("".join(char for char in decomposed if not unicodedata.combining(char)).split())


# Offices and bank headquarters are often in the metro area, not the city
# itself: "Madrid" also accepts these Comunidad de Madrid municipalities.
_METRO_AREAS = {
    "madrid": re.compile(
        r"\b(?:alcobendas|san sebastian de los reyes|tres cantos|las rozas|majadahonda|"
        r"pozuelo(?: de alarcon)?|boadilla(?: del monte)?|alcorcon|mostoles|leganes|getafe|"
        r"fuenlabrada|rivas[- ]vaciamadrid|coslada|san fernando de henares|torrejon de ardoz|"
        r"alcala de henares|villaviciosa de odon|villanueva de la canada|colmenar viejo|"
        r"aravaca|parla|pinto|valdemoro|arganda(?: del rey)?|la moraleja|el plantio)\b"
    ),
}


def _location_matches(location: str | None, allowed: Iterable[str]) -> bool:
    if not location:
        return False
    folded_location = " ".join(location.casefold().split())
    plain_location = _fold_accents(location)
    for value in allowed:
        normalized = " ".join(value.casefold().split())
        if normalized and normalized in folded_location:
            return True
        metro = _METRO_AREAS.get(_fold_accents(value))
        if metro is not None and metro.search(plain_location):
            return True
    listing_countries = _countries_in((location,))
    allowed_values = {" ".join(value.casefold().split()) for value in allowed}
    # Only a value that IS a country name allows that whole country: scanning
    # "Santiago de Compostela" for country codes found "de" (Germany).
    allowed_countries = {_ALIAS_TO_COUNTRY[value] for value in allowed_values if value in _ALIAS_TO_COUNTRY}
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
            if len(alias) == 2:
                # A two-letter code only counts when written as one ("Berlin, DE"): the word "de" in
                # "Esplugues de Llobregat" or "it"/"no"/"at" in free text are not countries.
                if _CODE_PATTERNS[alias].search(value):
                    result.add(_ALIAS_TO_COUNTRY[alias])
            elif pattern.search(folded):
                result.add(_ALIAS_TO_COUNTRY[alias])
        if _US_CITY.search(folded) or _US_STATE_SUFFIX.search(value):
            result.add("United States")
        for pattern, country in _FOREIGN_CITIES:
            if pattern.search(folded):
                result.add(country)
    return result


# "Woodinville, WA" / "Remote - TX": a comma or dash, then an upper-case US state code.
_US_STATE_SUFFIX = re.compile(
    r"(?:,|\s[-–])\s*(?:AL|AK|AZ|AR|CA|CO|CT|DE|DC|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|"
    r"NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY)\b"
)
_US_CITY = re.compile(
    r"\b(?:san francisco|sf\s+office|new york|nyc|los angeles|seattle|austin|boston|chicago|denver|"
    r"palo alto|mountain view|menlo park|san jose|san diego|washington,?\s+d\.?c\.?|atlanta|miami|"
    r"brooklyn|redmond|cambridge,\s*ma|eastern time|pacific time|central time|mountain time|"
    r"us time ?zones?|(?:est|pst|cst)\s*(?:time ?zone|hours)|"
    # Full state names ("Arizona; California; Utah"); Georgia is omitted (a country too).
    r"arizona|california|utah|texas|florida|colorado|oregon|massachusetts|illinois|"
    r"new jersey|pennsylvania|north carolina|michigan|minnesota|tennessee|wisconsin|"
    r"connecticut|maryland|virginia)\b"
)


# Frequent tech-hub cities named without their country in job locations.
_FOREIGN_CITIES = tuple(
    (re.compile(rf"\b(?:{cities})\b"), country)
    for cities, country in (
        # Spanish places as postings write them without the country ("28050, MADRID, Madrid", "Sant Cugat del Vallès").
        (
            "madrid|barcelona|valencia|sevilla|seville|bilbao|málaga|malaga|zaragoza|alicante|palma de mallorca|vigo|"
            "a coruña|la coruña|las palmas|tenerife|murcia|granada|valladolid|san sebastián|san sebastian|donostia|"
            "pamplona|cornellà|cornella|esplugues|l'hospitalet|hospitalet|sant cugat|alcobendas|pozuelo|boadilla|"
            "getafe|leganés|leganes|majadahonda|las rozas|tres cantos|castellón|castellon|gijón|gijon|oviedo|"
            "santiago de compostela|córdoba de españa|huelva|cádiz|cadiz|almería|almeria|logroño|logrono|salamanca|"
            "burgos|toledo|badajoz|cáceres|caceres|tarragona|girona|lleida|reus|sabadell|terrassa|mataró|mataro",
            "Spain",
        ),
        ("london|manchester|edinburgh", "United Kingdom"),
        ("paris", "France"),
        ("berlin|munich|münchen|hamburg", "Germany"),
        ("amsterdam|rotterdam|utrecht|eindhoven|the hague|den haag|delft|leiden", "Netherlands"),
        # Native country names and Dutch provinces / Swiss cantons as job sites write them.
        ("nederland|noord-holland|zuid-holland|noord-brabant|gelderland|overijssel|flevoland", "Netherlands"),
        ("schweiz|suisse|svizzera|kanton", "Switzerland"),
        ("dublin|cork|galway|limerick", "Ireland"),
        ("tel aviv|tel-aviv", "Israel"),
        ("toronto|vancouver|montreal|montréal", "Canada"),
        ("bangalore|bengaluru|pune|hyderabad|gurgaon|gurugram", "India"),
        ("singapore", "Singapore"),
        ("tokyo", "Japan"),
        ("seoul", "South Korea"),
        ("sydney|melbourne", "Australia"),
        ("zurich|zürich|geneva|genève|geneve|lausanne|basel|bern|zug", "Switzerland"),
        ("stockholm", "Sweden"),
        ("warsaw|kraków|krakow", "Poland"),
        ("lisbon|lisboa|porto", "Portugal"),
    )
)


def _remote_region_countries(location: str | None) -> set[str]:
    """Expand explicit remote-region labels to their included countries."""

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
    if re.search(r"\b(?:apac|asia[\s-]+pacific)\b", folded):
        result.update(_APAC_COUNTRIES)
    if re.search(r"\b(?:amer|americas|latam|latin america|north america|south america)\b", folded):
        result.update(_AMERICAS_COUNTRIES)
    return result


_AMERICAS_COUNTRIES = {"United States", "Canada", "Mexico", "Brazil", "Argentina"}


def _assess_country_restriction(
    restricted_countries: set[str],
    current_countries: set[str],
    eligible_countries: set[str],
    known_countries: set[str],
    preferences: CandidatePreferences,
    *,
    mode: str,
) -> SignalAssessment:
    if restricted_countries & current_countries:
        return SignalAssessment(
            SignalStatus.COMPATIBLE,
            f"The {mode} location includes the candidate's current country.",
        )
    if preferences.relocation_willingness and restricted_countries & eligible_countries:
        return SignalAssessment(
            SignalStatus.COMPATIBLE,
            f"The {mode} location matches an eligible country and relocation is allowed.",
        )
    if known_countries:
        return SignalAssessment(
            SignalStatus.INCOMPATIBLE,
            f"The {mode} location excludes the candidate's current and eligible countries.",
        )
    return SignalAssessment(
        SignalStatus.UNKNOWN,
        f"The {mode} country restriction cannot be checked without candidate country data.",
    )


def countries_in_text(*values: str | None) -> set[str]:
    """Countries named (directly or through a known city/region) in free location text."""

    return _countries_in(values)
