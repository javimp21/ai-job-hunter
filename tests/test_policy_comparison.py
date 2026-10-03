from __future__ import annotations

from pathlib import Path

from ai_job_hunter.candidates import load_candidate_config
from ai_job_hunter.decision_engine import (
    POLICY_VERSION_V1,
    POLICY_VERSION_V2,
    RUBRIC_VERSION,
    DecisionCache,
    DecisionEvidence,
    FinalDecision,
    JevAnswers,
    JevSignal,
    JobDecisionContext,
    build_decision_contexts,
    evaluate_job_decision,
)
from ai_job_hunter.domain.normalized_job import NormalizedJob
from ai_job_hunter.policy_comparison import (
    compare_cached_policies,
    render_comparison_report,
)
EXAMPLE_CONFIG = Path(__file__).parents[1] / "config" / "examples" / "candidate.example.json"


def _signal(value: float, *, question_type: str = "noul", confidence: float | None = None) -> JevSignal:
    return JevSignal(
        question_type=question_type,
        value=value,
        confidence=confidence,
        raw_value=value if question_type == "noul" else value * 4,
    )


def _answers(*, experience: float = 0.82) -> JevAnswers:
    return JevAnswers(
        role_relevance=_signal(0.90),
        experience_accessibility=_signal(experience),
        backend_relevance=_signal(0.85, question_type="score", confidence=0.88),
        stack_transferability=_signal(0.80),
        requirements_flexibility=_signal(0.76),
        career_value=_signal(0.82, question_type="score", confidence=0.80),
        observable_role_quality=_signal(0.75, question_type="score", confidence=0.80),
    )


def _context() -> JobDecisionContext:
    offer = NormalizedJob.model_validate(
        {
            "provider": "remotive",
            "external_id": "comparison-1",
            "source_url": "https://remotive.com/remote-jobs/software/comparison-1",
            "title": "Backend Engineer",
            "company_name": "Example Systems",
            "description": "Minimum 0 years of professional experience required.\n" + "A detailed backend role with responsibilities and requirements. " * 50,
            "location": "Worldwide",
            "remote_policy": "REMOTE",
            "remote_eligibility": "WORLDWIDE",
            "employment_type": "FULL_TIME",
        }
    )
    candidate = load_candidate_config(EXAMPLE_CONFIG)
    return build_decision_contexts([offer], candidate)[0]


class _OfflineEngine:
    cache_identity = "offline-engine"

    def __init__(self, answers: JevAnswers) -> None:
        self.answers = answers
        self.calls = 0

    def evaluate(self, context: JobDecisionContext) -> DecisionEvidence:
        self.calls += 1
        return DecisionEvidence(
            answers=self.answers,
            model_version="offline-model",
            engine_configuration=self.cache_identity,
        )


def test_comparison_reuses_cached_answers_and_never_calls_engine(tmp_path: Path) -> None:
    cache = DecisionCache(tmp_path / "decisions.local.json")
    context = _context()
    engine = _OfflineEngine(_answers(experience=0.52))
    evaluate_job_decision(context, engine, cache=cache)
    before_calls = engine.calls

    rows = compare_cached_policies(
        [context],
        cache,
        engine_identity=engine.cache_identity,
        rubric_version=RUBRIC_VERSION,
    )

    assert len(rows) == 1
    assert rows[0].v1.final_decision is FinalDecision.REVIEW
    assert rows[0].v2.final_decision is FinalDecision.APPLY
    assert rows[0].v1.cache_hit is True
    assert rows[0].v2.cache_hit is True
    assert engine.calls == before_calls == 1


def test_comparison_fails_closed_if_a_cached_answer_is_missing(tmp_path: Path) -> None:
    cache = DecisionCache(tmp_path / "empty.local.json")
    context = _context()

    try:
        compare_cached_policies(
            [context],
            cache,
            engine_identity="offline-engine",
            rubric_version=RUBRIC_VERSION,
        )
    except ValueError as error:
        assert "No cached Jev answers" in str(error)
    else:
        raise AssertionError("comparison must not generate replacement evidence")


def test_rendered_report_records_both_policy_distributions(tmp_path: Path) -> None:
    cache = DecisionCache(tmp_path / "unused.local.json")
    context = _context()
    engine = _OfflineEngine(_answers(experience=0.52))
    evaluate_job_decision(context, engine, cache=cache)
    rows = compare_cached_policies(
        [context], cache, engine_identity=engine.cache_identity, rubric_version=RUBRIC_VERSION
    )

    report = render_comparison_report(
        rows,
        benchmark_date="offline-test",
        snapshot_sha256="test-hash",
        model_version="offline-model",
        rubric_version=RUBRIC_VERSION,
    )

    assert f"| {POLICY_VERSION_V1} | 0 | 1 | 0 |" in report
    assert f"| {POLICY_VERSION_V2} | 1 | 0 | 0 |" in report
    assert "| Backend Engineer — Example Systems | REVIEW | APPLY | Sí | Role relevance" in report
    assert "backend normalizado < 0.25 y role < 0.60" in report
    assert "cache" in report.lower()
