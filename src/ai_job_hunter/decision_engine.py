"""Provider-independent job decision contracts, policy, and private cache."""

from __future__ import annotations

import hashlib
import json
import tempfile
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
from ai_job_hunter.deduplication.normalization import is_job_specific_url, normalize_job_url
from ai_job_hunter.domain.normalized_job import NormalizedJob
from ai_job_hunter.rubric import RUBRIC_SPEC, RUBRIC_VERSION

DEFAULT_CACHE_PATH = Path("data/local/job-decision-cache.local.json")
CACHE_FORMAT = "ai-job-hunter.job-decision-cache"
CACHE_VERSION = 1


class FinalDecision(StrEnum):
    APPLY = "APPLY"
    REVIEW = "REVIEW"
    SKIP = "SKIP"


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


def _decision_result(
    context: JobDecisionContext,
    evidence: DecisionEvidence,
    decision: FinalDecision,
    reasons: tuple[str, ...],
    rubric_version: str,
) -> JobDecisionResult:
    return JobDecisionResult(
        final_decision=decision,
        reasons=reasons,
        jev_answers=evidence.answers,
        deterministic_result=_deterministic_summary(context),
        model_version=evidence.model_version,
        engine_configuration=evidence.engine_configuration,
        rubric_version=rubric_version,
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
) -> JobDecisionResult:
    """Apply deterministic hard gates, consult cache, then call the engine once."""

    if context.duplicate_reason is not None:
        return _hard_skip(context, context.duplicate_reason, engine.cache_identity, rubric_version)
    if context.deterministic.decision is PreFilterDecision.REJECT:
        return _hard_skip(
            context,
            "Deterministic prefilter rejected the offer; Jev was not called.",
            engine.cache_identity,
            rubric_version,
        )

    key = cache.key_for(context, engine.cache_identity, rubric_version) if cache else None
    if cache is not None and key is not None:
        cached_result = cache.get(key)
        if cached_result is not None:
            return cached_result.model_copy(update={"cache_hit": True})

    try:
        evidence = DecisionEvidence.model_validate(engine.evaluate(context))
        result = apply_decision_policy(context, evidence, rubric_version=rubric_version)
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
            "inferred_seniority": context.facts.inferred_seniority.value,
            "technologies": context.facts.technologies,
            "required_technologies": context.facts.required_technologies,
        },
    }
