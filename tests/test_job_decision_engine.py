from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from ai_job_hunter.candidates import CandidateConfig, PreFilterDecision, load_candidate_config
from ai_job_hunter.decision_engine import (
    POLICY_VERSION_V1,
    POLICY_VERSION_V2,
    RUBRIC_VERSION,
    DecisionCache,
    DecisionEvidence,
    FinalDecision,
    JobDecisionContext,
    JobDecisionError,
    JevAnswers,
    JevSignal,
    MIN_APPLY_DESCRIPTION_CHARS,
    ReviewReasonCode,
    apply_decision_policy,
    apply_decision_policy_v2,
    build_decision_contexts,
    evaluate_job_decision,
)
from ai_job_hunter.domain.normalized_job import NormalizedJob
from ai_job_hunter.jev import (
    BACKEND_RELEVANCE_QUESTION,
    CAREER_VALUE_QUESTION,
    EXPERIENCE_ACCESSIBILITY_QUESTION,
    OBSERVABLE_ROLE_QUALITY_QUESTION,
    REQUIREMENTS_FLEXIBILITY_QUESTION,
    ROLE_RELEVANCE_QUESTION,
    STACK_TRANSFERABILITY_QUESTION,
    JevJobDecisionEngine,
    _parse_answers,
    build_jev_questions,
    build_jev_state,
)

EXAMPLE_CONFIG = Path(__file__).parents[1] / "config" / "examples" / "candidate.example.json"


def sample_offer(**overrides: object) -> NormalizedJob:
    values: dict[str, object] = {
        "provider": "remotive",
        "external_id": "decision-1",
        "source_url": "https://remotive.com/remote-jobs/software/decision-1",
        "title": "Backend Engineer",
        "company_name": "Example Systems",
        "description": "Build and operate backend APIs with Python and PostgreSQL.",
        "location": "Worldwide",
        "remote_policy": "REMOTE",
        "remote_eligibility": "WORLDWIDE",
        "employment_type": "FULL_TIME",
        "salary_min": 60000,
        "salary_max": 80000,
        "currency": "EUR",
        "salary_period": "YEAR",
    }
    values.update(overrides)
    # These fixtures isolate semantic-policy thresholds; explicit numeric fit
    # is tested independently in test_experience.py.
    if values.get("description"):
        values["description"] = "Minimum 0 years of professional experience required.\n" + str(values["description"])
        # Real postings are long; APPLY needs a description of at least MIN_APPLY_DESCRIPTION_CHARS.
        values["description"] = str(values["description"]).ljust(MIN_APPLY_DESCRIPTION_CHARS + 20, ".")
    return NormalizedJob.model_validate(values)


def sample_candidate(**changes: object) -> CandidateConfig:
    candidate = load_candidate_config(EXAMPLE_CONFIG)
    profile_changes = changes.pop("profile", {}) if "profile" in changes else {}
    preference_changes = changes.pop("preferences", {}) if "preferences" in changes else {}
    profile = candidate.profile.model_copy(update=profile_changes)
    preferences = candidate.preferences.model_copy(update=preference_changes)
    return CandidateConfig(profile=profile, preferences=preferences)


def context_for(
    offer: NormalizedJob | None = None,
    candidate: CandidateConfig | None = None,
) -> JobDecisionContext:
    return build_decision_contexts([offer or sample_offer()], candidate or sample_candidate())[0]


def signal(
    value: float,
    *,
    question_type: str = "noul",
    confidence: float | None = None,
) -> JevSignal:
    return JevSignal(
        question_type=question_type,
        value=value,
        confidence=confidence,
        raw_value=value if question_type == "noul" else value * 4,
    )


def good_answers(**overrides: JevSignal | None) -> JevAnswers:
    values: dict[str, JevSignal | None] = {
        "role_relevance": signal(0.90),
        "experience_accessibility": signal(0.82),
        "backend_relevance": signal(0.85, question_type="score", confidence=0.88),
        "stack_transferability": signal(0.80),
        "requirements_flexibility": signal(0.76),
        "career_value": signal(0.82, question_type="score", confidence=0.80),
        "observable_role_quality": signal(0.75, question_type="score", confidence=0.80),
    }
    values.update(overrides)
    return JevAnswers(**values)


class FakeJobDecisionEngine:
    cache_identity = "fake-engine/1;model=offline"

    def __init__(self, answers: JevAnswers | None = None) -> None:
        self.answers = answers or good_answers()
        self.calls: list[JobDecisionContext] = []

    def evaluate(self, context: JobDecisionContext) -> DecisionEvidence:
        self.calls.append(context)
        return DecisionEvidence(
            answers=self.answers,
            model_version="fake-model-1",
            engine_configuration=self.cache_identity,
            input_tokens=123,
            output_tokens=25,
        )


def test_engine_protocol_is_small_and_returns_only_structured_evidence() -> None:
    engine = FakeJobDecisionEngine()

    assert engine.cache_identity == "fake-engine/1;model=offline"
    evidence = engine.evaluate(context_for())
    assert isinstance(evidence, DecisionEvidence)
    assert not hasattr(evidence, "final_decision")


def test_deterministic_hard_reject_bypasses_engine() -> None:
    context = context_for(
        sample_offer(
            title="Backend Engineer",
            location="United States",
            remote_eligibility="COUNTRY_RESTRICTED",
        )
    )
    engine = FakeJobDecisionEngine()

    result = evaluate_job_decision(context, engine)

    assert context.deterministic.decision.value == "REJECT"
    assert result.final_decision is FinalDecision.SKIP
    assert result.jev_answers is None
    assert engine.calls == []


def test_staff_seniority_hard_reject_bypasses_engine() -> None:
    context = context_for(sample_offer(title="Staff Backend Engineer"))
    engine = FakeJobDecisionEngine()

    result = evaluate_job_decision(context, engine)

    assert context.deterministic.decision.value == "REJECT"
    assert result.final_decision is FinalDecision.SKIP
    assert engine.calls == []


@pytest.mark.parametrize(
    "title",
    [
        "Sales Engineer",
        "Customer Support Engineer",
        "Freelance Copywriter",
        "Office Assistant",
        "🇩🇪 Kundenservice Mobilfunk Inbound",
        "Inside Sales Contractor",
    ],
)
def test_clear_unrelated_titles_are_rejected_without_jev(title: str) -> None:
    context = context_for(sample_offer(title=title))
    engine = FakeJobDecisionEngine()

    result = evaluate_job_decision(context, engine)

    assert context.deterministic.decision.value == "REJECT"
    assert result.final_decision is FinalDecision.SKIP
    assert engine.calls == []


def test_unrelated_keyword_in_technical_title_is_not_a_safe_hard_reject() -> None:
    context = context_for(sample_offer(title="Software Engineer - Sales Platform"))
    engine = FakeJobDecisionEngine()

    evaluate_job_decision(context, engine)

    assert context.deterministic.decision is not PreFilterDecision.REJECT
    assert len(engine.calls) == 1


def test_duplicate_source_identity_bypasses_engine() -> None:
    offer = sample_offer()
    contexts = build_decision_contexts(
        [offer, offer.model_copy(update={"discovered_at": offer.discovered_at})],
        sample_candidate(),
    )
    engine = FakeJobDecisionEngine()

    results = [evaluate_job_decision(context, engine) for context in contexts]

    assert results[0].final_decision is FinalDecision.APPLY
    assert results[1].final_decision is FinalDecision.SKIP
    assert "Duplicate" in results[1].reasons[0]
    assert len(engine.calls) == 1


def test_duplicate_job_url_ignores_tracking_parameters() -> None:
    first = sample_offer(
        external_id="url-first",
        source_url="https://jobs.example.com/jobs/backend/1234?utm_source=feed",
    )
    second = sample_offer(
        external_id="url-second",
        source_url="https://jobs.example.com/jobs/backend/1234",
    )
    contexts = build_decision_contexts([first, second], sample_candidate())
    engine = FakeJobDecisionEngine()

    results = [evaluate_job_decision(context, engine) for context in contexts]

    assert results[1].final_decision is FinalDecision.SKIP
    assert len(engine.calls) == 1


def test_eligible_review_invokes_engine_even_when_preferred_role_is_unknown() -> None:
    context = context_for(sample_offer(title="AI Engineer", description="Build models and APIs."))
    engine = FakeJobDecisionEngine()

    result = evaluate_job_decision(context, engine)

    assert context.deterministic.decision.value == "REVIEW"
    assert len(engine.calls) == 1
    assert result.final_decision is FinalDecision.APPLY


def test_irrelevant_role_is_skipped_by_policy() -> None:
    answers = good_answers(role_relevance=signal(0.05))
    result = evaluate_job_decision(context_for(), FakeJobDecisionEngine(answers))

    assert result.final_decision is FinalDecision.SKIP
    assert "very low" in result.reasons[0]


def test_accessible_backend_role_is_recommended_apply() -> None:
    result = evaluate_job_decision(context_for(), FakeJobDecisionEngine(good_answers()))

    assert result.final_decision is FinalDecision.APPLY
    assert result.model_version == "fake-model-1"
    assert result.input_tokens == 123
    assert result.rubric_version == RUBRIC_VERSION
    assert result.deterministic_result.prefilter_decision.value in {"PASS", "REVIEW"}


def test_apply_needs_a_description_to_check_the_experience_requirement() -> None:
    # A portal detail request failed: only the title arrived, so no years could be stated.
    result = evaluate_job_decision(
        context_for(sample_offer(description=None)), FakeJobDecisionEngine(good_answers())
    )

    assert result.final_decision is FinalDecision.REVIEW
    assert result.review_reasons[0].code is ReviewReasonCode.EXPERIENCE_UNKNOWN
    assert "No job description" in result.reasons[0]


def test_conflicting_role_and_experience_signals_require_review() -> None:
    answers = good_answers(
        experience_accessibility=signal(0.25),
        career_value=signal(0.90, question_type="score", confidence=0.90),
    )
    result = evaluate_job_decision(context_for(), FakeJobDecisionEngine(answers))

    assert result.final_decision is FinalDecision.REVIEW
    assert any("conflict" in reason for reason in result.reasons)


@pytest.mark.parametrize(
    "offer",
    [
        sample_offer(location="United States", remote_eligibility="COUNTRY_RESTRICTED"),
        sample_offer(title="Principal Backend Engineer"),
        sample_offer(salary_min=10000, salary_max=20000, currency="EUR", salary_period="YEAR"),
    ],
)
def test_hard_deterministic_rejections_cannot_be_overridden(offer: NormalizedJob) -> None:
    engine = FakeJobDecisionEngine(good_answers())
    result = evaluate_job_decision(context_for(offer), engine)

    assert result.final_decision is FinalDecision.SKIP
    assert result.jev_answers is None
    assert engine.calls == []


def test_stack_transferability_is_an_independent_apply_gate() -> None:
    answers = good_answers(
        stack_transferability=signal(0.30),
        career_value=signal(0.82, question_type="score", confidence=0.85),
    )
    result = evaluate_job_decision(context_for(), FakeJobDecisionEngine(answers))

    assert result.final_decision is FinalDecision.REVIEW
    assert any("Stack transferability" in reason for reason in result.reasons)


def test_rubric_version_is_recorded_in_result() -> None:
    result = evaluate_job_decision(
        context_for(), FakeJobDecisionEngine(), rubric_version="job_decision_test_v2"
    )

    assert result.rubric_version == "job_decision_test_v2"


def test_cache_hit_avoids_a_second_engine_evaluation(tmp_path: Path) -> None:
    cache = DecisionCache(tmp_path / "decisions.local.json")
    context = context_for()
    engine = FakeJobDecisionEngine()

    first = evaluate_job_decision(context, engine, cache=cache)
    second = evaluate_job_decision(context, engine, cache=cache)

    assert first.final_decision is FinalDecision.APPLY
    assert second.cache_hit is True
    assert len(engine.calls) == 1


def test_candidate_profile_change_invalidates_cache(tmp_path: Path) -> None:
    cache = DecisionCache(tmp_path / "decisions.local.json")
    offer = sample_offer()
    first_context = context_for(offer)
    changed_candidate = sample_candidate(profile={"years_of_experience": Decimal("3")})
    second_context = context_for(offer, changed_candidate)
    engine = FakeJobDecisionEngine()

    evaluate_job_decision(first_context, engine, cache=cache)
    evaluate_job_decision(second_context, engine, cache=cache)

    assert len(engine.calls) == 2


def test_candidate_preference_change_invalidates_cache(tmp_path: Path) -> None:
    cache = DecisionCache(tmp_path / "decisions.local.json")
    offer = sample_offer()
    first_context = context_for(offer)
    changed_candidate = sample_candidate(
        preferences={"willing_to_learn_technologies": ["Go", "Kotlin"]}
    )
    second_context = context_for(offer, changed_candidate)
    engine = FakeJobDecisionEngine()

    evaluate_job_decision(first_context, engine, cache=cache)
    evaluate_job_decision(second_context, engine, cache=cache)

    assert len(engine.calls) == 2


def test_job_change_invalidates_cache(tmp_path: Path) -> None:
    cache = DecisionCache(tmp_path / "decisions.local.json")
    first_context = context_for(sample_offer())
    second_context = context_for(sample_offer(description="Build distributed data services."))
    engine = FakeJobDecisionEngine()

    evaluate_job_decision(first_context, engine, cache=cache)
    evaluate_job_decision(second_context, engine, cache=cache)

    assert len(engine.calls) == 2


def test_rubric_change_invalidates_cache(tmp_path: Path) -> None:
    cache = DecisionCache(tmp_path / "decisions.local.json")
    context = context_for()
    engine = FakeJobDecisionEngine()

    evaluate_job_decision(context, engine, cache=cache, rubric_version="rubric-v1")
    evaluate_job_decision(context, engine, cache=cache, rubric_version="rubric-v2")

    assert len(engine.calls) == 2


def test_engine_model_configuration_change_invalidates_cache(tmp_path: Path) -> None:
    cache = DecisionCache(tmp_path / "decisions.local.json")
    context = context_for()
    first_engine = FakeJobDecisionEngine()
    second_engine = FakeJobDecisionEngine()
    second_engine.cache_identity = "fake-engine/1;model=offline-v2"

    evaluate_job_decision(context, first_engine, cache=cache)
    evaluate_job_decision(context, second_engine, cache=cache)

    assert len(first_engine.calls) == 1
    assert len(second_engine.calls) == 1


def test_malformed_engine_response_fails_clearly() -> None:
    class MalformedEngine(FakeJobDecisionEngine):
        def evaluate(self, context: JobDecisionContext):
            return {"final_decision": "APPLY"}

    with pytest.raises(JobDecisionError, match="malformed evidence"):
        evaluate_job_decision(context_for(), MalformedEngine())


@pytest.mark.parametrize(
    ("answers", "reason_text"),
    [
        (good_answers(observable_role_quality=None), "Missing Jev signals"),
        (
            good_answers(backend_relevance=signal(0.8, question_type="score", confidence=0.2)),
            "Insufficient confidence",
        ),
    ],
)
def test_missing_or_low_confidence_signal_requires_review(
    answers: JevAnswers,
    reason_text: str,
) -> None:
    result = evaluate_job_decision(context_for(), FakeJobDecisionEngine(answers))

    assert result.final_decision is FinalDecision.REVIEW
    assert any(reason_text in reason for reason in result.reasons)


def test_policy_uses_versioned_structured_answers_only() -> None:
    evidence = DecisionEvidence(
        answers=good_answers(),
        model_version="jev-version-test",
        engine_configuration="test-config",
    )
    result = apply_decision_policy(context_for(), evidence)

    assert result.final_decision is FinalDecision.APPLY
    assert result.rubric_version == "job_decision_v1"
    assert result.jev_answers is evidence.answers


def test_v1_policy_keeps_its_borderline_experience_review() -> None:
    answers = good_answers(experience_accessibility=signal(0.52))
    evidence = DecisionEvidence(
        answers=answers,
        model_version="offline-model",
        engine_configuration="offline-cache-identity",
    )

    result = apply_decision_policy(context_for(), evidence)

    assert result.final_decision is FinalDecision.REVIEW
    assert result.policy_version == POLICY_VERSION_V1


def test_v2_strong_backend_fit_can_apply_with_borderline_experience() -> None:
    context = context_for(sample_offer(description="Detailed role scope. " * 80))
    answers = good_answers(experience_accessibility=signal(0.52))
    evidence = DecisionEvidence(
        answers=answers,
        model_version="offline-model",
        engine_configuration="offline-cache-identity",
    )

    result = apply_decision_policy_v2(context, evidence)

    assert result.final_decision is FinalDecision.APPLY
    assert result.policy_version == POLICY_VERSION_V2


def test_v2_high_career_value_can_support_a_lower_experience_apply() -> None:
    context = context_for(sample_offer(description="Detailed role scope. " * 80))
    answers = good_answers(
        role_relevance=signal(0.90),
        experience_accessibility=signal(0.42),
        backend_relevance=signal(0.90, question_type="score", confidence=0.90),
        stack_transferability=signal(0.75),
        requirements_flexibility=signal(0.66),
        career_value=signal(0.95, question_type="score", confidence=0.95),
    )
    evidence = DecisionEvidence(
        answers=answers,
        model_version="offline-model",
        engine_configuration="offline-cache-identity",
    )

    result = apply_decision_policy_v2(context, evidence)

    assert result.final_decision is FinalDecision.APPLY
    assert "exceptionally strong" in " ".join(result.reasons)


def test_v2_very_low_experience_still_skips() -> None:
    answers = good_answers(experience_accessibility=signal(0.10))
    evidence = DecisionEvidence(
        answers=answers,
        model_version="offline-model",
        engine_configuration="offline-cache-identity",
    )

    result = apply_decision_policy_v2(context_for(), evidence)

    assert result.final_decision is FinalDecision.SKIP
    assert result.policy_version == POLICY_VERSION_V2


def test_v2_career_value_does_not_rescue_irrelevant_role() -> None:
    answers = good_answers(
        role_relevance=signal(0.10),
        career_value=signal(1.0, question_type="score", confidence=1.0),
    )
    evidence = DecisionEvidence(
        answers=answers,
        model_version="offline-model",
        engine_configuration="offline-cache-identity",
    )

    result = apply_decision_policy_v2(context_for(), evidence)

    assert result.final_decision is FinalDecision.SKIP
    assert result.reasons[0].startswith("Role relevance is extremely low")


def test_v2_does_not_override_hard_geography_reject() -> None:
    context = context_for(
        sample_offer(location="United States", remote_eligibility="COUNTRY_RESTRICTED")
    )
    engine = FakeJobDecisionEngine(good_answers())

    result = evaluate_job_decision(context, engine, policy_version=POLICY_VERSION_V2)

    assert result.final_decision is FinalDecision.SKIP
    assert result.policy_version == POLICY_VERSION_V2
    assert result.jev_answers is None
    assert engine.calls == []


def test_v2_incompatible_san_francisco_geography_hard_skips_strong_signals() -> None:
    context = context_for(
        sample_offer(
            location="San Francisco",
            remote_policy=None,
            remote_eligibility="UNKNOWN",
            description="Detailed backend role scope. " * 80,
        )
    )
    evidence = DecisionEvidence(
        answers=good_answers(),
        model_version="offline-model",
        engine_configuration="offline-cache-identity",
    )

    result = apply_decision_policy_v2(context, evidence)

    assert result.final_decision is FinalDecision.SKIP
    assert any("location excludes" in reason for reason in result.reasons)


def test_v2_explicit_eu_remote_geography_can_apply() -> None:
    context = context_for(
        sample_offer(
            location="European Union",
            remote_policy="REMOTE",
            remote_eligibility="EU_REMOTE",
            description="Detailed backend role scope. " * 80,
        )
    )
    evidence = DecisionEvidence(
        answers=good_answers(),
        model_version="offline-model",
        engine_configuration="offline-cache-identity",
    )

    result = apply_decision_policy_v2(context, evidence)

    assert context.deterministic.signals.geography.status.value == "COMPATIBLE"
    assert result.final_decision is FinalDecision.APPLY


def test_v2_low_observable_quality_alone_does_not_block_strong_fit() -> None:
    context = context_for(sample_offer(description="Detailed verifiable role scope. " * 70))
    answers = good_answers(
        observable_role_quality=signal(0.10, question_type="score", confidence=0.90)
    )
    evidence = DecisionEvidence(
        answers=answers,
        model_version="offline-model",
        engine_configuration="offline-cache-identity",
    )

    result = apply_decision_policy_v2(context, evidence)

    assert result.final_decision is FinalDecision.APPLY
    assert result.review_reasons == ()


def test_v2_contradictory_role_and_backend_signals_require_structured_review() -> None:
    context = context_for(sample_offer(description="Detailed backend role scope. " * 80))
    answers = good_answers(
        role_relevance=signal(0.95),
        backend_relevance=signal(0.20, question_type="score", confidence=0.90),
    )
    evidence = DecisionEvidence(
        answers=answers,
        model_version="offline-model",
        engine_configuration="offline-cache-identity",
    )

    result = apply_decision_policy_v2(context, evidence)

    assert result.final_decision is FinalDecision.REVIEW
    assert ReviewReasonCode.ROLE_FAMILY_UNCERTAIN in {reason.code for reason in result.review_reasons}


def test_v2_review_reasons_identify_experience_and_stack_uncertainty() -> None:
    answers = good_answers(
        experience_accessibility=signal(0.35),
        stack_transferability=signal(0.48),
        requirements_flexibility=signal(0.46),
    )
    evidence = DecisionEvidence(
        answers=answers,
        model_version="offline-model",
        engine_configuration="offline-cache-identity",
    )

    result = apply_decision_policy_v2(context_for(sample_offer(description="Detailed job scope. " * 80)), evidence)

    assert result.final_decision is FinalDecision.REVIEW
    codes = {reason.code for reason in result.review_reasons}
    assert ReviewReasonCode.EXPERIENCE_BORDERLINE in codes
    assert ReviewReasonCode.STACK_UNCERTAIN in codes


def test_v2_cross_border_hybrid_uncertainty_is_structured_review() -> None:
    candidate = sample_candidate(
        profile={"current_country": "Spain"},
        preferences={
            "remote_preference": "HYBRID_OR_REMOTE",
            "acceptable_locations": ["Barcelona, Spain"],
        },
    )
    context = context_for(
        sample_offer(
            location="Wroclaw, Poland (Hybrid)",
            remote_policy=None,
            description="Detailed role responsibilities. " * 80,
        ),
        candidate,
    )
    evidence = DecisionEvidence(
        answers=good_answers(experience_accessibility=signal(0.58)),
        model_version="offline-model",
        engine_configuration="offline-cache-identity",
    )

    result = apply_decision_policy_v2(context, evidence)

    assert result.final_decision is FinalDecision.REVIEW
    assert ReviewReasonCode.LOCATION_UNCERTAIN in {reason.code for reason in result.review_reasons}


def test_policy_version_switch_replays_cached_jev_answers_without_engine_call(tmp_path: Path) -> None:
    cache = DecisionCache(tmp_path / "decisions.local.json")
    context = context_for(sample_offer(description="Detailed backend role. " * 80))
    engine = FakeJobDecisionEngine(
        good_answers(experience_accessibility=signal(0.52))
    )

    first = evaluate_job_decision(context, engine, cache=cache)
    second = evaluate_job_decision(context, engine, cache=cache, policy_version=POLICY_VERSION_V2)
    third = evaluate_job_decision(context, engine, cache=cache, policy_version=POLICY_VERSION_V1)

    assert first.final_decision is FinalDecision.REVIEW
    assert second.final_decision is FinalDecision.APPLY
    assert third.final_decision is FinalDecision.REVIEW
    assert second.cache_hit is True and third.cache_hit is True
    assert second.policy_version == POLICY_VERSION_V2
    assert third.policy_version == POLICY_VERSION_V1
    assert len(engine.calls) == 1


def test_stack_context_contains_only_relevant_candidate_and_offer_fields() -> None:
    candidate = sample_candidate(
        profile={"technologies": ["Java", "Spring Boot"], "primary_skills": ["Backend"]}
    )
    context = context_for(
        sample_offer(description="Build Go services and deploy on AWS."),
        candidate,
    )

    state = build_jev_state(context)

    assert state["candidate"]["technologies"] == ["Java", "Spring Boot"]
    assert "willing_to_learn_technologies" in state["candidate"]
    assert state["job"]["detected_technologies"] == ["aws", "go"]
    assert "source_url" not in state["job"]
    assert "current_salary" not in state["candidate"]
    assert "Kotlin, Scala, Go, Python, Node.js" in STACK_TRANSFERABILITY_QUESTION


def test_seven_typed_questions_include_exact_independent_prompts() -> None:
    questions = build_jev_questions()

    assert set(questions) == {
        "role_relevance",
        "experience_accessibility",
        "backend_relevance",
        "stack_transferability",
        "requirements_flexibility",
        "career_value",
        "observable_role_quality",
    }
    assert questions["role_relevance"].instructions == ROLE_RELEVANCE_QUESTION
    assert questions["experience_accessibility"].instructions == EXPERIENCE_ACCESSIBILITY_QUESTION
    assert questions["backend_relevance"].instructions == BACKEND_RELEVANCE_QUESTION
    assert questions["stack_transferability"].instructions == STACK_TRANSFERABILITY_QUESTION
    assert questions["requirements_flexibility"].instructions == REQUIREMENTS_FLEXIBILITY_QUESTION
    assert questions["career_value"].instructions == CAREER_VALUE_QUESTION
    assert questions["observable_role_quality"].instructions == OBSERVABLE_ROLE_QUALITY_QUESTION
    assert len(questions["backend_relevance"].criteria) == 5


def _synthetic_response(*, wrong_role_type: bool = False) -> SimpleNamespace:
    answers: dict[str, SimpleNamespace] = {}
    for name in ("role_relevance", "experience_accessibility", "stack_transferability", "requirements_flexibility"):
        question_type = "score" if wrong_role_type and name == "role_relevance" else "noul"
        answers[name] = SimpleNamespace(type=question_type, noul=0.9, score=4, confidence=0.9, probabilities={})
    for name in ("backend_relevance", "career_value", "observable_role_quality"):
        answers[name] = SimpleNamespace(
            type="score",
            score=3.5,
            confidence=0.85,
            probabilities={0: 0.0, 1: 0.0, 2: 0.1, 3: 0.3, 4: 0.6},
        )
    return SimpleNamespace(
        answers=answers,
        model="jev-1.13.0",
        usage=SimpleNamespace(input_tokens=400, output_tokens=80),
    )


def test_official_sdk_adapter_maps_typed_answers_without_network() -> None:
    response = _synthetic_response()

    answers = _parse_answers(response)

    assert answers.role_relevance is not None
    assert answers.role_relevance.value == 0.9
    assert answers.backend_relevance is not None
    assert answers.backend_relevance.raw_value == 3.5
    assert answers.backend_relevance.value == 0.875
    assert answers.backend_relevance.confidence == 0.85
    assert answers.backend_relevance.probabilities["4"] == 0.6


def test_official_sdk_adapter_rejects_wrong_typed_response() -> None:
    with pytest.raises(JobDecisionError, match="malformed decision response"):
        JevJobDecisionEngine(client_factory=lambda: FakeSdkClient(_synthetic_response(wrong_role_type=True))).evaluate(
            context_for()
        )


class FakeSdkClient:
    def __init__(self, response: SimpleNamespace) -> None:
        self.response = response
        self.state = None
        self.questions = None

    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def system_one(self, *, state: dict[str, object], questions: dict[str, object]):
        self.state = state
        self.questions = questions
        return self.response


def test_jev_engine_uses_official_typed_sdk_client_factory() -> None:
    client = FakeSdkClient(_synthetic_response())
    engine = JevJobDecisionEngine(client_factory=lambda: client)

    evidence = engine.evaluate(context_for())

    assert evidence.model_version == "jev-1.13.0"
    assert evidence.input_tokens == 400
    assert evidence.output_tokens == 80
    assert client.state["job"]["title"] == "Backend Engineer"
    assert client.questions["stack_transferability"].type == "noul"


def test_jev_engine_passes_dotenv_key_to_official_sdk_without_logging(
    monkeypatch,
    tmp_path: Path,
) -> None:
    import sys

    from ai_job_hunter import jev
    from ai_job_hunter.config import Settings

    env_file = tmp_path / ".env"
    env_file.write_text("TYPESAFE_API_KEY=fake-test-key\n", encoding="utf-8")
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setattr(jev, "get_settings", lambda: Settings(_env_file=env_file))
    client = FakeSdkClient(_synthetic_response())
    client_options: dict[str, object] = {}

    class FakeSdkModule:
        Noul = staticmethod(lambda **kwargs: SimpleNamespace(type="noul", **kwargs))
        Score = staticmethod(lambda **kwargs: SimpleNamespace(type="score", **kwargs))

        @staticmethod
        def TypeSafeClient(**kwargs):
            client_options.update(kwargs)
            return client

    monkeypatch.setitem(sys.modules, "typesafe_sdk", FakeSdkModule)

    evidence = JevJobDecisionEngine().evaluate(context_for())

    assert evidence.model_version == "jev-1.13.0"
    assert client_options == {"model": "jev-latest", "api_key": "fake-test-key"}


def test_cli_dry_run_uses_snapshot_only_and_applies_limit(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    from ai_job_hunter import remotive_cli
    from ai_job_hunter.snapshots import save_remotive_snapshot

    snapshot = tmp_path / "offers.local.json"
    offers = [
        sample_offer(external_id=f"eligible-{index}", source_url=f"https://remotive.com/remote-jobs/software/eligible-{index}")
        for index in range(3)
    ]
    offers.append(
        sample_offer(
            external_id="us-only",
            source_url="https://remotive.com/remote-jobs/software/us-only",
            title="Senior Backend Engineer",
            location="United States",
            remote_eligibility="COUNTRY_RESTRICTED",
        )
    )
    save_remotive_snapshot(snapshot, offers)

    def no_network(_self):
        pytest.fail("dry-run must not call Remotive")

    monkeypatch.setattr(remotive_cli.RemotiveConnector, "fetch_jobs", no_network)
    exit_code = remotive_cli.main(
        [
            "--candidate-config",
            str(EXAMPLE_CONFIG),
            "--snapshot",
            str(snapshot),
            "--dry-run-jev",
            "--max-jev-jobs",
            "2",
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "TOTAL: 4" in output
    assert "HARD SKIP: 1" in output
    assert "JEV ELIGIBLE: 3" in output
    assert "WOULD CALL: 2" in output
    assert "DEFERRED BY LIMIT: 1" in output
    assert "Backend Engineer — Example Systems" in output


def test_cli_live_mode_fails_without_key_before_loading_remotive(
    monkeypatch,
    tmp_path: Path,
    caplog,
) -> None:
    from ai_job_hunter import remotive_cli

    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    monkeypatch.setattr(
        remotive_cli,
        "get_settings",
        lambda: SimpleNamespace(typesafe_api_key=None),
    )
    monkeypatch.setattr(
        remotive_cli.RemotiveConnector,
        "fetch_jobs",
        lambda _self: pytest.fail("missing-key check must happen before Remotive"),
    )

    exit_code = remotive_cli.main(
        [
            "--candidate-config",
            str(EXAMPLE_CONFIG),
            "--decision-engine",
            "jev",
            "--snapshot",
            str(tmp_path / "missing.local.json"),
        ]
    )

    assert exit_code == 1
    assert "TYPESAFE_API_KEY" in caplog.text


def test_cli_max_jobs_limit_caps_new_jev_calls(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    from ai_job_hunter import remotive_cli
    from ai_job_hunter.snapshots import save_remotive_snapshot

    snapshot = tmp_path / "offers.local.json"
    offers = [
        sample_offer(external_id=f"limited-{index}", source_url=f"https://remotive.com/remote-jobs/software/limited-{index}")
        for index in range(3)
    ]
    save_remotive_snapshot(snapshot, offers)
    fake_engine = FakeJobDecisionEngine()
    monkeypatch.setenv("TYPESAFE_API_KEY", "fake-not-a-secret")
    monkeypatch.setattr(remotive_cli, "JevJobDecisionEngine", lambda *, model: fake_engine)

    exit_code = remotive_cli.main(
        [
            "--candidate-config",
            str(EXAMPLE_CONFIG),
            "--snapshot",
            str(snapshot),
            "--decision-engine",
            "jev",
            "--max-jev-jobs",
            "1",
            "--decision-cache",
            str(tmp_path / "decisions.local.json"),
        ]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert len(fake_engine.calls) == 1
    assert "JEV ELIGIBLE: 3" in output
    assert "EVALUATED WITH JEV: 1 (1 new, 0 cache hits)" in output
    assert "DEFERRED BY LIMIT: 2" in output
