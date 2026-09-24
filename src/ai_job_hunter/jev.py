"""Official TypeSafe System One adapter for ambiguous job-fit signals."""

from __future__ import annotations

import html
import importlib.metadata
import re
from collections.abc import Callable
from typing import Any

from ai_job_hunter.config import get_settings
from ai_job_hunter.decision_engine import (
    DecisionEvidence,
    JobDecisionContext,
    JobDecisionError,
    JevAnswers,
    JevSignal,
)
from ai_job_hunter.rubric import (
    BACKEND_RELEVANCE_QUESTION,
    BACKEND_SCORE_CRITERIA,
    CAREER_VALUE_QUESTION,
    CAREER_VALUE_SCORE_CRITERIA,
    EXPERIENCE_ACCESSIBILITY_QUESTION,
    OBSERVABLE_ROLE_QUALITY_QUESTION,
    REQUIREMENTS_FLEXIBILITY_QUESTION,
    ROLE_QUALITY_SCORE_CRITERIA,
    ROLE_RELEVANCE_QUESTION,
    STACK_TRANSFERABILITY_QUESTION,
    RUBRIC_VERSION,
)

JEV_MODEL = "jev-latest"
DESCRIPTION_LIMIT = 8_000


def build_jev_questions(sdk: Any | None = None) -> dict[str, Any]:
    """Build one typed System One request with seven independent, versioned questions."""

    if sdk is None:
        try:
            from typesafe_sdk import Noul, Score
        except ImportError as error:
            raise JobDecisionError(
                "The Jev decision engine requires the official `typesafe-sdk` package; "
                "install the project with `pip install -e '.[jev]'`."
            ) from error
    else:
        Noul = sdk.Noul
        Score = sdk.Score

    return {
        "role_relevance": Noul(instructions=ROLE_RELEVANCE_QUESTION),
        "experience_accessibility": Noul(instructions=EXPERIENCE_ACCESSIBILITY_QUESTION),
        "backend_relevance": Score(
            instructions=BACKEND_RELEVANCE_QUESTION,
            criteria=BACKEND_SCORE_CRITERIA,
        ),
        "stack_transferability": Noul(instructions=STACK_TRANSFERABILITY_QUESTION),
        "requirements_flexibility": Noul(instructions=REQUIREMENTS_FLEXIBILITY_QUESTION),
        "career_value": Score(
            instructions=CAREER_VALUE_QUESTION,
            criteria=CAREER_VALUE_SCORE_CRITERIA,
        ),
        "observable_role_quality": Score(
            instructions=OBSERVABLE_ROLE_QUALITY_QUESTION,
            criteria=ROLE_QUALITY_SCORE_CRITERIA,
        ),
    }


def build_jev_state(context: JobDecisionContext) -> dict[str, Any]:
    """Build a compact, privacy-conscious state; identity URLs and personal IDs are omitted."""

    candidate = context.candidate
    profile = candidate.profile
    preferences = candidate.preferences
    facts = context.facts
    offer = context.offer
    state: dict[str, Any] = {
        "candidate": {
            "years_of_experience": str(profile.years_of_experience)
            if profile.years_of_experience is not None
            else None,
            "current_role": profile.current_role,
            "preferred_roles": preferences.preferred_roles,
            "primary_skills": profile.primary_skills,
            "secondary_skills": profile.secondary_skills,
            "technologies": profile.technologies,
            "preferred_technologies": preferences.preferred_technologies,
            "willing_to_learn_technologies": preferences.willing_to_learn_technologies,
            "current_country": profile.current_country,
        },
        "job": {
            "title": facts.title,
            "company": offer.company_name,
            "location": facts.location,
            "remote_policy": facts.remote_policy.value if facts.remote_policy else None,
            "remote_eligibility": facts.remote_eligibility.value,
            "employment_type": facts.employment_type.value if facts.employment_type else None,
            "description": _clean_description(offer.description),
            "structured_salary": {
                "minimum": str(facts.salary_min) if facts.salary_min is not None else None,
                "maximum": str(facts.salary_max) if facts.salary_max is not None else None,
                "currency": facts.currency,
                "period": facts.salary_period.value if facts.salary_period else None,
            },
            "detected_technologies": list(facts.technologies),
            "required_technologies": list(facts.required_technologies),
            "inferred_seniority": facts.inferred_seniority.value,
        },
        "deterministic_signals": {
            "prefilter_decision": context.deterministic.decision.value,
            "reasons": list(context.deterministic.reasons),
            "job_facts": {
                "normalized_title": facts.normalized_title,
                "remote_policy": facts.remote_policy.value if facts.remote_policy else None,
                "remote_eligibility": facts.remote_eligibility.value,
                "location": facts.location,
                "technologies": list(facts.technologies),
                "required_technologies": list(facts.required_technologies),
                "salary_min": str(facts.salary_min) if facts.salary_min is not None else None,
                "salary_max": str(facts.salary_max) if facts.salary_max is not None else None,
                "currency": facts.currency,
                "salary_period": facts.salary_period.value if facts.salary_period else None,
                "employment_type": facts.employment_type.value if facts.employment_type else None,
            },
            "geography": {
                "status": context.deterministic.signals.geography.status.value,
                "reason": context.deterministic.signals.geography.reason,
            },
            "salary": {
                "evaluation": context.deterministic.signals.salary.evaluation.value,
                "reason": context.deterministic.signals.salary.reason,
            },
            "seniority": {
                "status": context.deterministic.signals.seniority.status.value,
                "reason": context.deterministic.signals.seniority.reason,
            },
        },
    }
    if _salary_preferences_are_relevant(context):
        state["candidate"]["salary_preferences"] = {
            "minimum": str(preferences.minimum_salary) if preferences.minimum_salary is not None else None,
            "target": str(preferences.target_salary) if preferences.target_salary is not None else None,
            "currency": preferences.salary_currency,
            "period": preferences.salary_period.value if preferences.salary_period else None,
        }
    return state


class JevJobDecisionEngine:
    """Official SDK implementation of the provider-independent decision contract."""

    def __init__(
        self,
        *,
        model: str = JEV_MODEL,
        client_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.model = model
        self._client_factory = client_factory

    @property
    def cache_identity(self) -> str:
        try:
            package_version = importlib.metadata.version("typesafe-sdk")
        except importlib.metadata.PackageNotFoundError:
            package_version = "not-installed"
        return f"typesafe-sdk/{package_version};model={self.model};rubric={RUBRIC_VERSION}"

    def evaluate(self, context: JobDecisionContext) -> DecisionEvidence:
        try:
            import typesafe_sdk
        except ImportError as error:
            raise JobDecisionError(
                "The Jev decision engine requires the official `typesafe-sdk` package; "
                "install the project with `pip install -e '.[jev]'`."
            ) from error

        factory = self._client_factory
        if factory is None:
            configured_key = get_settings().typesafe_api_key
            api_key = (
                configured_key.get_secret_value().strip()
                if configured_key is not None
                else ""
            )
            factory = lambda: typesafe_sdk.TypeSafeClient(
                model=self.model,
                api_key=api_key or None,
            )
        try:
            with factory() as client:
                response = client.system_one(
                    state=build_jev_state(context),
                    questions=build_jev_questions(typesafe_sdk),
                )
        except JobDecisionError:
            raise
        except Exception as error:
            # Avoid forwarding SDK/provider exception bodies that can contain request data.
            raise JobDecisionError(
                f"TypeSafe Jev request failed ({type(error).__name__}); no decision was cached."
            ) from error

        try:
            answers = _parse_answers(response)
            model_version = response.model
            usage = response.usage
            return DecisionEvidence(
                answers=answers,
                model_version=model_version,
                engine_configuration=self.cache_identity,
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
            )
        except (AttributeError, KeyError, TypeError, ValueError) as error:
            raise JobDecisionError(
                f"TypeSafe Jev returned a malformed decision response ({type(error).__name__})."
            ) from error


def _parse_answers(response: Any) -> JevAnswers:
    """Convert the SDK's typed answers without trusting absent or wrong-type values."""

    if not hasattr(response, "answers") or not hasattr(response, "model") or not hasattr(response, "usage"):
        raise TypeError("expected SystemOneResponse fields")
    raw_answers = response.answers
    if not isinstance(raw_answers, dict):
        raise TypeError("answers must be a mapping")
    kinds = {
        "role_relevance": "noul",
        "experience_accessibility": "noul",
        "backend_relevance": "score",
        "stack_transferability": "noul",
        "requirements_flexibility": "noul",
        "career_value": "score",
        "observable_role_quality": "score",
    }
    values: dict[str, JevSignal | None] = {}
    for name, expected_type in kinds.items():
        answer = raw_answers.get(name)
        if answer is None:
            values[name] = None
            continue
        if getattr(answer, "type", None) != expected_type:
            raise TypeError(f"{name} must have type {expected_type}")
        if expected_type == "noul":
            value = _as_finite_float(answer.noul)
            values[name] = JevSignal(
                question_type="noul",
                value=value,
                raw_value=value,
            )
        else:
            score = _as_finite_float(answer.score)
            if not 0 <= score <= 4:
                raise ValueError(f"{name} score must be between 0 and 4")
            confidence_raw = getattr(answer, "confidence", None)
            confidence = _as_finite_float(confidence_raw) if confidence_raw is not None else None
            probabilities_raw = getattr(answer, "probabilities", {}) or {}
            if not isinstance(probabilities_raw, dict):
                raise TypeError(f"{name} probabilities must be a mapping")
            probabilities = {
                str(key): _as_finite_float(value)
                for key, value in probabilities_raw.items()
            }
            values[name] = JevSignal(
                question_type="score",
                value=score / 4,
                confidence=confidence,
                raw_value=score,
                probabilities=probabilities,
            )
    return JevAnswers.model_validate(values)


def _as_finite_float(value: Any) -> float:
    converted = float(value)
    if converted != converted or converted in {float("inf"), float("-inf")}:
        raise ValueError("answer values must be finite")
    return converted


def _clean_description(description: str | None) -> str | None:
    if not description:
        return None
    text = html.unescape(re.sub(r"<[^>]*>", " ", description))
    text = " ".join(text.split())
    return text[:DESCRIPTION_LIMIT]


def _salary_preferences_are_relevant(context: JobDecisionContext) -> bool:
    preferences = context.candidate.preferences
    facts = context.facts
    return bool(
        (preferences.minimum_salary is not None or preferences.target_salary is not None)
        and facts.salary_min is not None
        and facts.currency == preferences.salary_currency
        and facts.salary_period == preferences.salary_period
        and context.deterministic.signals.salary.evaluation.value != "BELOW_MINIMUM"
    )
