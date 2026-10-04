"""Provider-independent job decision contracts, policy, and private cache."""

from __future__ import annotations

import hashlib
import json
import re
import tempfile
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from ai_job_hunter.candidates import (
    CandidateConfig,
    JobFacts,
    JobPreFilterResult,
    PreFilterDecision,
    evaluate_job,
)
from ai_job_hunter.candidates.experience import EXPERIENCE_POLICY_VERSION, ExperienceOutcome
from ai_job_hunter.deduplication.normalization import is_job_specific_url, normalize_job_url
from ai_job_hunter.domain.normalized_job import NormalizedJob
from ai_job_hunter.rubric import RUBRIC_SPEC, RUBRIC_VERSION

DEFAULT_CACHE_PATH = Path("data/local/job-decision-cache.local.json")
CACHE_FORMAT = "ai-job-hunter.job-decision-cache"
CACHE_VERSION = 1
POLICY_VERSION_V1 = "job_decision_v1"
POLICY_VERSION_V2 = "job_decision_v2"
SUPPORTED_POLICY_VERSIONS = (POLICY_VERSION_V1, POLICY_VERSION_V2)


def experience_blocks_apply(experience: Any) -> bool:
    """Whether the explicit experience check prevents APPLY.

    A posting that states no experience-years requirement at all (no
    mandatory, preferred or ambiguous requirement) does not block APPLY; Jev's
    experience accessibility gate (>= 0.60) still has to pass. A stated
    requirement that is unmet, a stretch or ambiguous keeps the job in REVIEW.
    """

    if experience.outcome is ExperienceOutcome.MEETS:
        return False
    states_nothing = (
        experience.outcome is ExperienceOutcome.UNKNOWN
        and not experience.mandatory
        and not experience.preferred
        and not getattr(experience, "ambiguous", ())
    )
    return not states_nothing


class FinalDecision(StrEnum):
    APPLY = "APPLY"
    REVIEW = "REVIEW"
    SKIP = "SKIP"


class ReviewReasonCode(StrEnum):
    LOCATION_UNCERTAIN = "LOCATION_UNCERTAIN"
    COMPENSATION_UNKNOWN = "COMPENSATION_UNKNOWN"
    EXPERIENCE_BORDERLINE = "EXPERIENCE_BORDERLINE"
    EXPERIENCE_UNKNOWN = "EXPERIENCE_UNKNOWN"
    ROLE_FAMILY_UNCERTAIN = "ROLE_FAMILY_UNCERTAIN"
    INSUFFICIENT_DESCRIPTION = "INSUFFICIENT_DESCRIPTION"
    STACK_UNCERTAIN = "STACK_UNCERTAIN"
    SENIORITY_UNCERTAIN = "SENIORITY_UNCERTAIN"
    OTHER = "OTHER"


class StructuredReviewReason(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: ReviewReasonCode
    message: str = Field(min_length=1)


class JobDecisionError(ValueError):
    """A decision response or private cache is malformed."""


class JevSignal(BaseModel):
    """One typed Jev answer, normalized to 0..1 for policy comparisons."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    question_type: Literal["noul", "score"]
    value: float | None = Field(default=None, ge=0, le=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    raw_value: float | None = None
    probabilities: dict[str, float] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_signal_values(self) -> JevSignal:
        if self.raw_value is not None and not 0 <= self.raw_value <= 4:
            raise ValueError("raw_value must be between 0 and 4")
        if any(not 0 <= probability <= 1 for probability in self.probabilities.values()):
            raise ValueError("probabilities must be between 0 and 1")
        return self


class JevAnswers(BaseModel):
    """Independent semantic signals returned by Jev; any missing answer stays unknown."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    role_relevance: JevSignal | None = None
    experience_accessibility: JevSignal | None = None
    backend_relevance: JevSignal | None = None
    stack_transferability: JevSignal | None = None
    requirements_flexibility: JevSignal | None = None
    career_value: JevSignal | None = None
    observable_role_quality: JevSignal | None = None

    @model_validator(mode="after")
    def validate_question_types(self) -> JevAnswers:
        expected = {
            "role_relevance": "noul",
            "experience_accessibility": "noul",
            "backend_relevance": "score",
            "stack_transferability": "noul",
            "requirements_flexibility": "noul",
            "career_value": "score",
            "observable_role_quality": "score",
        }
        for name, question_type in expected.items():
            answer = getattr(self, name)
            if answer is not None and answer.question_type != question_type:
                raise ValueError(f"{name} must be a {question_type} answer")
        return self


class DecisionEvidence(BaseModel):
    """Signals and provider metadata only; this type has no final decision field."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    answers: JevAnswers
    model_version: str
    engine_configuration: str
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)


@dataclass(frozen=True, slots=True)
class JobDecisionContext:
    """Only the data needed by the deterministic filter and semantic evaluator."""

    offer: NormalizedJob
    candidate: CandidateConfig
    facts: JobFacts
    deterministic: JobPreFilterResult
    duplicate_reason: str | None = None


def build_decision_contexts(
    offers: list[NormalizedJob],
    candidate: CandidateConfig,
) -> list[JobDecisionContext]:
    """Prefilter offers and mark exact repeated source identities within this batch."""

    first_seen: dict[str, int] = {}
    contexts: list[JobDecisionContext] = []
    for index, offer in enumerate(offers):
        facts = JobFacts.from_normalized_job(offer)
        deterministic = evaluate_job(facts, candidate)
        identity_keys: list[str] = []
        if offer.external_id:
            identity_keys.append(f"source:{offer.provider.casefold()}:{offer.external_id.casefold()}")
        for url in (offer.canonical_url, offer.apply_url, offer.source_url):
            if is_job_specific_url(url) and (normalized := normalize_job_url(url)):
                identity_keys.append(f"url:{normalized}")
        duplicate_index = next((first_seen[key] for key in identity_keys if key in first_seen), None)
        duplicate_reason = (
            f"Duplicate of snapshot offer #{duplicate_index + 1} by exact source ID or job URL."
            if duplicate_index is not None
            else None
        )
        for key in identity_keys:
            first_seen.setdefault(key, index)
        contexts.append(
            JobDecisionContext(
                offer=offer,
                candidate=candidate,
                facts=facts,
                deterministic=deterministic,
                duplicate_reason=duplicate_reason,
            )
        )
    return contexts


@runtime_checkable
class JobDecisionEngine(Protocol):
    """Provider contract: return typed evidence; deterministic code decides what it means."""

    @property
    def cache_identity(self) -> str:
        """Stable provider, package, model, and configuration identity."""

    def evaluate(self, context: JobDecisionContext) -> DecisionEvidence:
        """Evaluate one ambiguous offer and return structured evidence."""


class DeterministicDecisionSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    prefilter_decision: PreFilterDecision
    reasons: tuple[str, ...]


class JobDecisionResult(BaseModel):
    """Final recommendation plus the deterministic and Jev evidence behind it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    final_decision: FinalDecision
    reasons: tuple[str, ...]
    jev_answers: JevAnswers | None
    deterministic_result: DeterministicDecisionSummary
    model_version: str | None
    engine_configuration: str | None
    rubric_version: str = RUBRIC_VERSION
    policy_version: str = POLICY_VERSION_V1
    review_reasons: tuple[StructuredReviewReason, ...] = ()
    evaluated_at: datetime
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    cache_hit: bool = False


def apply_decision_policy(
    context: JobDecisionContext,
    evidence: DecisionEvidence,
    *,
    rubric_version: str = RUBRIC_VERSION,
) -> JobDecisionResult:
    """Combine Jev's signals with explicit thresholds; Jev never chooses APPLY."""

    deterministic = _deterministic_summary(context)
    answers = evidence.answers
    missing = [
        name
        for name in (
            "role_relevance",
            "experience_accessibility",
            "backend_relevance",
            "stack_transferability",
            "requirements_flexibility",
            "career_value",
            "observable_role_quality",
        )
        if getattr(answers, name) is None or getattr(answers, name).value is None
    ]
    low_confidence = [
        name
        for name in ("backend_relevance", "career_value", "observable_role_quality")
        if (
            (signal := getattr(answers, name)) is not None
            and (signal.confidence is None or signal.confidence < 0.40)
        )
    ]

    role = _value_or_none(answers.role_relevance)
    experience = _value_or_none(answers.experience_accessibility)
    if role is not None and role < 0.20:
        decision = FinalDecision.SKIP
        reasons = (f"Role relevance is very low ({role:.2f}).",)
        return _decision_result(context, evidence, decision, reasons, rubric_version)
    if experience is not None and experience < 0.15:
        decision = FinalDecision.SKIP
        reasons = (f"Experience accessibility is very low ({experience:.2f}).",)
        return _decision_result(context, evidence, decision, reasons, rubric_version)

    if missing or low_confidence:
        explanations = []
        if missing:
            explanations.append("Missing Jev signals: " + ", ".join(missing) + ".")
        if low_confidence:
            explanations.append(
                "Insufficient confidence in score signals: " + ", ".join(low_confidence) + "."
            )
        decision = FinalDecision.REVIEW
        reasons = tuple(explanations)
    else:
        role = _value(answers.role_relevance)
        experience = _value(answers.experience_accessibility)
        backend = _value(answers.backend_relevance)
        stack = _value(answers.stack_transferability)
        flexibility = _value(answers.requirements_flexibility)
        career = _value(answers.career_value)
        quality = _value(answers.observable_role_quality)
        assert all(value is not None for value in (role, experience, backend, stack, flexibility, career, quality))
        assert answers.role_relevance is not None
        assert answers.experience_accessibility is not None

        if role < 0.20:
            decision = FinalDecision.SKIP
            reasons = (f"Role relevance is very low ({role:.2f}).",)
        elif experience < 0.15:
            decision = FinalDecision.SKIP
            reasons = (f"Experience accessibility is very low ({experience:.2f}).",)
        else:
            high_career_value = career >= 0.80
            minimum_flexibility = 0.35 if high_career_value else 0.45
            minimum_stack = 0.45 if high_career_value else 0.55
            apply_gates = (
                role >= 0.70
                and experience >= 0.60
                and backend >= 0.60
                and stack >= minimum_stack
                and flexibility >= minimum_flexibility
                and quality >= 0.35
            )
            contradictory = (
                (role >= 0.60 and backend < 0.25)
                or (backend >= 0.70 and stack < 0.20)
                or (experience < 0.35 and career >= 0.80)
            )
            if apply_gates and not contradictory:
                decision = FinalDecision.APPLY
                reasons_list = [
                    "Strong role relevance, experience accessibility, backend fit, and stack transferability.",
                    "Requirements flexibility and observable role quality meet the apply policy.",
                ]
                if high_career_value:
                    reasons_list.append(
                        "High career value allows the documented lower stack/flexibility thresholds."
                    )
                reasons = tuple(reasons_list)
            else:
                decision = FinalDecision.REVIEW
                reasons_list = []
                if contradictory:
                    reasons_list.append("Jev signals conflict across role, experience, or stack fit.")
                if role < 0.70:
                    reasons_list.append(f"Role relevance is below the APPLY threshold ({role:.2f} < 0.70).")
                if experience < 0.60:
                    reasons_list.append(
                        f"Experience accessibility is below the APPLY threshold ({experience:.2f} < 0.60)."
                    )
                if backend < 0.60:
                    reasons_list.append(f"Backend relevance is below the APPLY threshold ({backend:.2f} < 0.60).")
                if stack < minimum_stack:
                    reasons_list.append(
                        f"Stack transferability is below the APPLY threshold ({stack:.2f} < {minimum_stack:.2f})."
                    )
                if flexibility < minimum_flexibility:
                    reasons_list.append(
                        "Requirements flexibility is below the APPLY threshold "
                        f"({flexibility:.2f} < {minimum_flexibility:.2f})."
                    )
                if quality < 0.35:
                    reasons_list.append(
                        f"Observable role quality is below the APPLY threshold ({quality:.2f} < 0.35)."
                    )
                reasons = tuple(reasons_list or ("Signals do not satisfy the APPLY policy.",))

    return _decision_result(context, evidence, decision, reasons, rubric_version)


def apply_decision_policy_v2(
    context: JobDecisionContext,
    evidence: DecisionEvidence,
    *,
    rubric_version: str = RUBRIC_VERSION,
) -> JobDecisionResult:
    """Apply v2's application-upside policy and preserve material uncertainty."""

    if context.duplicate_reason is not None or context.deterministic.decision is PreFilterDecision.REJECT:
        return _hard_skip(
            context,
            context.duplicate_reason or "Deterministic prefilter rejected the offer; Jev was not called.",
            evidence.engine_configuration,
            rubric_version,
            policy_version=POLICY_VERSION_V2,
        )

    answers = evidence.answers
    values = {
        name: _value_or_none(getattr(answers, name))
        for name in (
            "role_relevance",
            "experience_accessibility",
            "backend_relevance",
            "stack_transferability",
            "requirements_flexibility",
            "career_value",
            "observable_role_quality",
        )
    }
    role = values["role_relevance"]
    experience = values["experience_accessibility"]
    backend = values["backend_relevance"]
    stack = values["stack_transferability"]
    flexibility = values["requirements_flexibility"]
    career = values["career_value"]
    quality = values["observable_role_quality"]

    missing = [name for name, value in values.items() if value is None]
    if role is not None and role < 0.20:
        return _decision_result(
            context,
            evidence,
            FinalDecision.SKIP,
            (f"Role relevance is extremely low ({role:.2f} < 0.20).",),
            rubric_version,
            policy_version=POLICY_VERSION_V2,
        )
    if experience is not None and experience < 0.15:
        return _decision_result(
            context,
            evidence,
            FinalDecision.SKIP,
            (f"Experience accessibility is extremely low ({experience:.2f} < 0.15).",),
            rubric_version,
            policy_version=POLICY_VERSION_V2,
        )

    if missing:
        reasons = tuple(
            _structured_reason_for_signal(name, f"Jev did not return {name.replace('_', ' ')}.")
            for name in missing
        )
        return _v2_review(context, evidence, reasons, rubric_version)

    assert role is not None and experience is not None and backend is not None
    assert stack is not None and flexibility is not None
    assert career is not None and quality is not None

    low_confidence_backend = (
        answers.backend_relevance is not None
        and (answers.backend_relevance.confidence is None or answers.backend_relevance.confidence < 0.40)
    )
    if low_confidence_backend:
        return _v2_review(
            context,
            evidence,
            (StructuredReviewReason(
                code=ReviewReasonCode.ROLE_FAMILY_UNCERTAIN,
                message="Backend relevance has insufficient confidence to determine the role family.",
            ),),
            rubric_version,
        )

    # Low fit combinations indicate a different job family or a rigid stack gap.
    if role < 0.45 and backend < 0.60 and stack < 0.45:
        return _decision_result(
            context,
            evidence,
            FinalDecision.SKIP,
            ("Role relevance, backend relevance, and stack transferability are all low; this is a clear family mismatch.",),
            rubric_version,
            policy_version=POLICY_VERSION_V2,
        )
    if role < 0.75 and stack < 0.40 and flexibility < 0.35:
        return _decision_result(
            context,
            evidence,
            FinalDecision.SKIP,
            ("Moderate role relevance combines with a narrow, poorly transferable stack; the mismatch is unlikely to be worth applying for.",),
            rubric_version,
            policy_version=POLICY_VERSION_V2,
        )
    if backend < 0.25 and role < 0.60:
        return _decision_result(
            context,
            evidence,
            FinalDecision.SKIP,
            ("Backend relevance and overall role relevance are both very low for this backend search.",),
            rubric_version,
            policy_version=POLICY_VERSION_V2,
        )

    description_length = len((context.offer.description or "").strip())
    insufficient_description = description_length < 1_000
    geography = context.deterministic.signals.geography
    if geography.status.value != "COMPATIBLE" or _has_material_location_uncertainty(context):
        return _v2_review(
            context,
            evidence,
            (StructuredReviewReason(
                code=ReviewReasonCode.LOCATION_UNCERTAIN,
                message=(
                    "The offer's geography is not confirmed compatible with the candidate's configured locations: "
                    f"{geography.reason}"
                ),
            ),),
            rubric_version,
        )
    strong_core_fit = role >= 0.75 and backend >= 0.70 and stack >= 0.60 and flexibility >= 0.50
    standard_apply = strong_core_fit and experience >= 0.50 and not insufficient_description
    high_upside_experience_exception = (
        strong_core_fit
        and not insufficient_description
        and experience >= 0.40
        and career >= 0.90
        and role >= 0.85
        and backend >= 0.90
        and stack >= 0.70
        and flexibility >= 0.65
        and (answers.career_value.confidence or 0.0) >= 0.40
    )
    if standard_apply or high_upside_experience_exception:
        messages = [
            "Role relevance, backend fit, stack transferability, and requirements flexibility make this worth applying for."
        ]
        if experience < 0.50:
            messages.append(
                "Borderline experience is accepted because career value and the other fit signals are exceptionally strong."
            )
        return _decision_result(
            context,
            evidence,
            FinalDecision.APPLY,
            tuple(messages),
            rubric_version,
            policy_version=POLICY_VERSION_V2,
        )

    review_reasons: list[StructuredReviewReason] = []
    if experience < 0.50:
        review_reasons.append(StructuredReviewReason(
            code=ReviewReasonCode.EXPERIENCE_BORDERLINE,
            message=f"Experience accessibility {experience:.2f} is below the standard APPLY level of 0.50 and does not meet the high-upside exception.",
        ))
    if role < 0.75 or backend < 0.70:
        review_reasons.append(StructuredReviewReason(
            code=ReviewReasonCode.ROLE_FAMILY_UNCERTAIN,
            message=f"Role/backend fit is not decisive enough for APPLY (role {role:.2f}; backend {backend:.2f}).",
        ))
    if stack < 0.60 or flexibility < 0.50:
        review_reasons.append(StructuredReviewReason(
            code=ReviewReasonCode.STACK_UNCERTAIN,
            message=f"Stack transferability or requirements flexibility is too uncertain for APPLY (stack {stack:.2f}; flexibility {flexibility:.2f}).",
        ))
    salary = context.deterministic.signals.salary
    if (
        salary.evaluation.value == "UNKNOWN"
        and (context.candidate.preferences.minimum_salary is not None
             or context.candidate.preferences.target_salary is not None)
    ):
        review_reasons.append(StructuredReviewReason(
            code=ReviewReasonCode.COMPENSATION_UNKNOWN,
            message="A salary threshold is configured, but the offer does not provide a comparable salary range.",
        ))
    if (
        context.deterministic.signals.seniority.status.value == "UNKNOWN"
        and (context.candidate.preferences.minimum_seniority is not None
             or context.candidate.preferences.maximum_seniority is not None)
    ):
        review_reasons.append(StructuredReviewReason(
            code=ReviewReasonCode.SENIORITY_UNCERTAIN,
            message="The posting does not establish seniority clearly enough to compare with the configured seniority range.",
        ))
    if quality < 0.35 and not insufficient_description:
        review_reasons.append(StructuredReviewReason(
            code=ReviewReasonCode.INSUFFICIENT_DESCRIPTION,
            message="Observable role quality is low; review the posting for missing responsibilities or requirements.",
        ))
    if not review_reasons:
        review_reasons.append(StructuredReviewReason(
            code=ReviewReasonCode.OTHER,
            message="The available signals leave a material question that needs human review.",
        ))
    if insufficient_description:
        review_reasons.append(StructuredReviewReason(
            code=ReviewReasonCode.INSUFFICIENT_DESCRIPTION,
            message=f"The offer description has only {description_length} characters, which is not enough to verify responsibilities or requirements.",
        ))
    return _v2_review(context, evidence, tuple(review_reasons), rubric_version)


def apply_versioned_decision_policy(
    context: JobDecisionContext,
    evidence: DecisionEvidence,
    *,
    policy_version: str = POLICY_VERSION_V1,
    rubric_version: str = RUBRIC_VERSION,
) -> JobDecisionResult:
    if policy_version == POLICY_VERSION_V1:
        return apply_decision_policy(context, evidence, rubric_version=rubric_version)
    if policy_version == POLICY_VERSION_V2:
        return apply_decision_policy_v2(context, evidence, rubric_version=rubric_version)
    raise JobDecisionError(f"Unsupported decision policy version: {policy_version}.")


def _v2_review(
    context: JobDecisionContext,
    evidence: DecisionEvidence,
    review_reasons: tuple[StructuredReviewReason, ...],
    rubric_version: str,
) -> JobDecisionResult:
    return _decision_result(
        context,
        evidence,
        FinalDecision.REVIEW,
        tuple(reason.message for reason in review_reasons),
        rubric_version,
        policy_version=POLICY_VERSION_V2,
        review_reasons=review_reasons,
    )


def _structured_reason_for_signal(name: str, message: str) -> StructuredReviewReason:
    code_by_signal = {
        "role_relevance": ReviewReasonCode.ROLE_FAMILY_UNCERTAIN,
        "experience_accessibility": ReviewReasonCode.EXPERIENCE_BORDERLINE,
        "backend_relevance": ReviewReasonCode.ROLE_FAMILY_UNCERTAIN,
        "stack_transferability": ReviewReasonCode.STACK_UNCERTAIN,
        "requirements_flexibility": ReviewReasonCode.STACK_UNCERTAIN,
        "career_value": ReviewReasonCode.OTHER,
        "observable_role_quality": ReviewReasonCode.INSUFFICIENT_DESCRIPTION,
    }
    return StructuredReviewReason(code=code_by_signal.get(name, ReviewReasonCode.OTHER), message=message)


def _has_material_location_uncertainty(context: JobDecisionContext) -> bool:
    """Catch explicit hybrid/onsite location text the normalized facts could not classify."""

    if context.offer.remote_policy is not None:
        return False
    location = context.facts.location or ""
    explicit_mode = re.search(r"\b(?:hybrid|on[ -]?site|in[ -]?office)\b", location, re.IGNORECASE)
    if explicit_mode is None:
        return False

    preferences = context.candidate.preferences
    profile = context.candidate.profile
    remote_preference = getattr(preferences.remote_preference, "value", preferences.remote_preference)
    if remote_preference == "ANY" and not preferences.acceptable_locations:
        return False
    mode = explicit_mode.group(0).casefold().replace(" ", "-")
    mode_conflicts = (
        (mode == "hybrid" and remote_preference in {"REMOTE_ONLY", "ONSITE_ONLY"})
        or (mode in {"on-site", "onsite", "in-office"} and remote_preference in {"REMOTE_ONLY", "HYBRID_OR_REMOTE"})
    )
    if mode_conflicts:
        return True
    configured_locations = (
        profile.current_city,
        profile.current_country,
        *profile.eligible_countries,
        *preferences.acceptable_locations,
        *preferences.preferred_locations,
    )
    return bool(configured_locations) and not any(
        _location_text_matches(location, configured)
        for configured in configured_locations
        if configured
    )


def _location_text_matches(offer_location: str, configured_location: str) -> bool:
    def normalized(value: str) -> str:
        decomposed = unicodedata.normalize("NFKD", value.casefold())
        ascii_text = "".join(char for char in decomposed if not unicodedata.combining(char))
        return re.sub(r"[^a-z0-9]+", " ", ascii_text).strip()

    offer_text = normalized(offer_location)
    configured_text = normalized(configured_location)
    return bool(configured_text and (configured_text in offer_text or offer_text in configured_text))


def _decision_result(
    context: JobDecisionContext,
    evidence: DecisionEvidence,
    decision: FinalDecision,
    reasons: tuple[str, ...],
    rubric_version: str,
    *,
    policy_version: str = POLICY_VERSION_V1,
    review_reasons: tuple[StructuredReviewReason, ...] = (),
) -> JobDecisionResult:
    experience = context.deterministic.signals.experience
    if context.deterministic.decision is PreFilterDecision.REJECT:
        decision = FinalDecision.SKIP
        reasons = context.deterministic.reasons
    elif decision is FinalDecision.APPLY and experience_blocks_apply(experience):
        decision = FinalDecision.REVIEW
        reason = StructuredReviewReason(
            code=(ReviewReasonCode.EXPERIENCE_BORDERLINE
                  if experience.outcome is ExperienceOutcome.STRETCH
                  else ReviewReasonCode.EXPERIENCE_UNKNOWN),
            message=experience.reason + " " + experience.requirement_display,
        )
        reasons = (reason.message, *reasons)
        review_reasons = (reason, *review_reasons)
    return JobDecisionResult(
        final_decision=decision,
        reasons=reasons,
        jev_answers=evidence.answers,
        deterministic_result=_deterministic_summary(context),
        model_version=evidence.model_version,
        engine_configuration=evidence.engine_configuration,
        rubric_version=rubric_version,
        policy_version=policy_version,
        review_reasons=review_reasons,
        evaluated_at=datetime.now(UTC),
        input_tokens=evidence.input_tokens,
        output_tokens=evidence.output_tokens,
    )


def evaluate_job_decision(
    context: JobDecisionContext,
    engine: JobDecisionEngine,
    *,
    cache: DecisionCache | None = None,
    rubric_version: str = RUBRIC_VERSION,
    policy_version: str = POLICY_VERSION_V1,
) -> JobDecisionResult:
    """Apply deterministic hard gates, consult cache, then call the engine once."""

    if policy_version not in SUPPORTED_POLICY_VERSIONS:
        raise JobDecisionError(f"Unsupported decision policy version: {policy_version}.")
    if context.duplicate_reason is not None:
        return _hard_skip(
            context,
            context.duplicate_reason,
            engine.cache_identity,
            rubric_version,
            policy_version=policy_version,
        )
    if context.deterministic.decision is PreFilterDecision.REJECT:
        return _hard_skip(
            context,
            "Deterministic prefilter rejected the offer; Jev was not called.",
            engine.cache_identity,
            rubric_version,
            policy_version=policy_version,
        )

    key = cache.key_for(context, engine.cache_identity, rubric_version) if cache else None
    if cache is not None and key is not None:
        cached_result = cache.get(key)
        if cached_result is not None:
            if cached_result.jev_answers is None:
                # A cached final recommendation without reusable evidence is
                # never authority to bypass today's explicit experience gate.
                experience = context.deterministic.signals.experience
                decision = cached_result.final_decision
                # Without replayable Jev evidence the accessibility gate cannot be
                # re-checked, so only a met requirement keeps APPLY here.
                if decision is FinalDecision.APPLY and experience.outcome is not ExperienceOutcome.MEETS:
                    decision = FinalDecision.REVIEW
                return cached_result.model_copy(
                    update={"cache_hit": True, "policy_version": policy_version,
                            "final_decision": decision}
                )
            cached_evidence = DecisionEvidence(
                answers=cached_result.jev_answers,
                model_version=cached_result.model_version or "unknown-cached-model",
                engine_configuration=cached_result.engine_configuration or engine.cache_identity,
                input_tokens=cached_result.input_tokens,
                output_tokens=cached_result.output_tokens,
            )
            return apply_versioned_decision_policy(
                context,
                cached_evidence,
                policy_version=policy_version,
                rubric_version=rubric_version,
            ).model_copy(update={"cache_hit": True})

    try:
        evidence = DecisionEvidence.model_validate(engine.evaluate(context))
        result = apply_versioned_decision_policy(
            context,
            evidence,
            policy_version=policy_version,
            rubric_version=rubric_version,
        )
    except JobDecisionError:
        raise
    except (ValidationError, TypeError, ValueError) as error:
        raise JobDecisionError(f"Decision engine returned malformed evidence: {error}") from error
    if cache is not None and key is not None:
        cache.set(key, result)
    return result


class DecisionCache:
    """Atomic private JSON cache keyed by the complete effective decision state."""

    def __init__(self, path: str | Path = DEFAULT_CACHE_PATH) -> None:
        self.path = Path(path)

    def key_for(
        self,
        context: JobDecisionContext,
        engine_identity: str,
        rubric_version: str = RUBRIC_VERSION,
    ) -> str:
        payload = {
            "engine": engine_identity,
            "rubric_version": rubric_version,
            "rubric": RUBRIC_SPEC,
            "candidate": context.candidate.model_dump(mode="json"),
            "job_identity": {
                "provider": context.offer.provider,
                "external_id": context.offer.external_id,
                "source_url": context.offer.source_url,
                "canonical_url": context.offer.canonical_url,
                "apply_url": context.offer.apply_url,
            },
            "job_state": _job_state_for_cache(context),
            "deterministic": {
                "decision": context.deterministic.decision.value,
                "reasons": context.deterministic.reasons,
            },
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def get(self, key: str) -> JobDecisionResult | None:
        entries = self._read_entries()
        payload = entries.get(key)
        if payload is None:
            return None
        try:
            return JobDecisionResult.model_validate(payload)
        except ValidationError as error:
            raise JobDecisionError(f"Decision cache '{self.path}' has an invalid entry: {error}") from error

    def contains(self, key: str) -> bool:
        return key in self._read_entries()

    def set(self, key: str, result: JobDecisionResult) -> None:
        entries = self._read_entries()
        entries[key] = result.model_dump(mode="json")
        payload = {
            "format": CACHE_FORMAT,
            "version": CACHE_VERSION,
            "entries": entries,
        }
        temporary_path: Path | None = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                json.dump(payload, temporary_file, ensure_ascii=False, indent=2)
                temporary_file.write("\n")
            temporary_path.replace(self.path)
        except (OSError, TypeError, ValueError) as error:
            raise JobDecisionError(f"Cannot write private decision cache '{self.path}': {error}") from error
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    def _read_entries(self) -> dict[str, Mapping[str, object]]:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return {}
        except (OSError, UnicodeDecodeError) as error:
            raise JobDecisionError(f"Cannot read private decision cache '{self.path}': {error}") from error
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as error:
            raise JobDecisionError(
                f"Decision cache '{self.path}' is not valid JSON at line {error.lineno}, column {error.colno}."
            ) from error
        if (
            not isinstance(payload, dict)
            or payload.get("format") != CACHE_FORMAT
            or payload.get("version") != CACHE_VERSION
            or not isinstance(payload.get("entries"), dict)
        ):
            raise JobDecisionError(f"Decision cache '{self.path}' has an unsupported format or version.")
        return payload["entries"]


def _hard_skip(
    context: JobDecisionContext,
    reason: str,
    engine_configuration: str,
    rubric_version: str,
    *,
    policy_version: str = POLICY_VERSION_V1,
) -> JobDecisionResult:
    reasons = (reason,) if context.duplicate_reason else context.deterministic.reasons
    if context.duplicate_reason:
        deterministic = DeterministicDecisionSummary(
            prefilter_decision=PreFilterDecision.REJECT,
            reasons=(reason,),
        )
    else:
        deterministic = _deterministic_summary(context)
    return JobDecisionResult(
        final_decision=FinalDecision.SKIP,
        reasons=reasons,
        jev_answers=None,
        deterministic_result=deterministic,
        model_version=None,
        engine_configuration=engine_configuration,
        rubric_version=rubric_version,
        policy_version=policy_version,
        evaluated_at=datetime.now(UTC),
    )


def _deterministic_summary(context: JobDecisionContext) -> DeterministicDecisionSummary:
    return DeterministicDecisionSummary(
        prefilter_decision=context.deterministic.decision,
        reasons=context.deterministic.reasons,
    )


def _value(signal: JevSignal | None) -> float:
    assert signal is not None and signal.value is not None
    return signal.value


def _value_or_none(signal: JevSignal | None) -> float | None:
    return signal.value if signal is not None else None


def _job_state_for_cache(context: JobDecisionContext) -> dict[str, object]:
    offer = context.offer
    return {
        "title": offer.title,
        "company": offer.company_name,
        "company_website": offer.company_website,
        "location": offer.location,
        "remote_policy": offer.remote_policy.value if offer.remote_policy else None,
        "remote_eligibility": offer.remote_eligibility.value,
        "employment_type": offer.employment_type.value if offer.employment_type else None,
        "description": offer.description,
        "salary_min": str(offer.salary_min) if offer.salary_min is not None else None,
        "salary_max": str(offer.salary_max) if offer.salary_max is not None else None,
        "currency": offer.currency,
        "salary_period": offer.salary_period.value if offer.salary_period else None,
        "facts": {
            "experience_policy_version": EXPERIENCE_POLICY_VERSION,
            "inferred_seniority": context.facts.inferred_seniority.value,
            "technologies": context.facts.technologies,
            "required_technologies": context.facts.required_technologies,
        },
    }
