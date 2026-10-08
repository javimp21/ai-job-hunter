"""Compare another decision engine with Jev on offers Jev already answered (read-only on the database).

It takes evaluations that Jev stored under the current profile, rebuilds each offer's decision context, asks the other
engine the same questions, applies the same deterministic policy to both sets of answers, and prints how often the final
decision agrees, how close each question is, and what the other engine cost and how fast it was.

Usage (from the shared directory so .env is read):
  python scripts/compare_engines.py candidate.local.json out.json --engine claude --model claude-haiku-5-5 --per-class 40
The Jev side is whatever is stored; no Jev call is made. The other engine is called once per offer.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import joinedload, selectinload

from ai_job_hunter.candidates.profile import load_candidate_config
from ai_job_hunter.claude_engine import QUESTION_KEYS, ClaudeJobDecisionEngine
from ai_job_hunter.db.session import create_database_engine, create_session_factory
from ai_job_hunter.decision_engine import (
    POLICY_VERSION_V2,
    DecisionEvidence,
    JevAnswers,
    JevSignal,
    apply_versioned_decision_policy,
)
from ai_job_hunter.models import Company, Job, JobEvaluation
from ai_job_hunter.models.job_evaluation import EvaluationStatus
from ai_job_hunter.services.opportunities import _config_fingerprint, _engine_identity, _prepare_from_source, _source_order

# USD per million tokens (platform.claude.com/docs/en/about-claude/pricing, 2026-10-08), prompts up to 100k tokens.
PRICES = {"claude-haiku-5-5": (0.10, 0.50), "claude-sonnet-5-5": (2.0, 10.0), "claude-opus-5-5": (4.0, 20.0)}


def stored_answers(evaluation: JobEvaluation) -> JevAnswers | None:
    raw = evaluation.jev_signals
    if not isinstance(raw, dict):
        return None
    try:
        return JevAnswers.model_validate(raw)
    except ValueError:
        return None


def pick(session, candidate, per_class: int):
    identity = _engine_identity(None)
    config_fp = _config_fingerprint(candidate, identity)
    rows = session.scalars(
        select(JobEvaluation).where(
            JobEvaluation.status == EvaluationStatus.EVALUATED.value,
            JobEvaluation.config_fingerprint == config_fp,
            JobEvaluation.jev_signals.is_not(None),
        )
    ).all()
    by_class: dict[str, list[JobEvaluation]] = {"APPLY": [], "REVIEW": [], "SKIP": []}
    for row in rows:
        if row.decision in by_class:
            by_class[row.decision].append(row)
    chosen: list[JobEvaluation] = []
    for label, items in by_class.items():
        items.sort(key=lambda row: str(row.job_id))  # stable, not cherry-picked
        step = max(1, len(items) // per_class)
        chosen += items[::step][:per_class]
    return chosen, identity


def context_for(session, evaluation: JobEvaluation, candidate, identity):
    job = session.scalar(
        select(Job).options(joinedload(Job.company), selectinload(Job.sources)).where(Job.id == evaluation.job_id)
    )
    for source in sorted(job.sources, key=_source_order):
        prepared = _prepare_from_source(job, source, candidate, identity)
        if prepared is not None and prepared.fingerprint == evaluation.evaluation_fingerprint:
            return prepared.context
    return None


def decide(context, answers: JevAnswers, model: str) -> str:
    evidence = DecisionEvidence(answers=answers, model_version=model, engine_configuration="compare")
    return apply_versioned_decision_policy(context, evidence, policy_version=POLICY_VERSION_V2).final_decision.value


def rank_correlation(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 5 or len(set(xs)) < 2 or len(set(ys)) < 2:
        return None

    def ranks(values):
        order = sorted(range(len(values)), key=lambda i: values[i])
        out = [0.0] * len(values)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
                j += 1
            for k in range(i, j + 1):
                out[order[k]] = (i + j) / 2 + 1
            i = j + 1
        return out

    rx, ry = ranks(xs), ranks(ys)
    return statistics.correlation(rx, ry)


SCORE_KEYS = ("backend_relevance", "career_value", "observable_role_quality")


def _fit(pairs: list[tuple[float, float]]) -> tuple[float, float]:
    xs, ys = [p[0] for p in pairs], [p[1] for p in pairs]
    if len(set(xs)) < 2:
        return 0.0, statistics.mean(ys)
    slope, intercept = statistics.linear_regression(xs, ys)
    return slope, intercept


def _apply(fit: tuple[float, float], value: float) -> float:
    return min(1.0, max(0.0, fit[0] * value + fit[1]))


def report_calibration(work, good, answers_by_job, model: str) -> None:
    """Two-fold cross-fit: learn a straight-line map from the other engine's answers to Jev's on one half, apply it to the
    other half, and count how often the final decision then matches Jev. Fitting and testing never share an offer."""

    by_job = {str(evaluation.job_id): (context, jev) for evaluation, context, jev in work}
    ids = [r["job_id"] for r in good]
    agree = total = 0
    matrix: Counter = Counter()
    for fold in (0, 1):
        train = [i for n, i in enumerate(ids) if n % 2 != fold]
        test = [i for n, i in enumerate(ids) if n % 2 == fold]
        fits: dict[str, tuple[float, float]] = {}
        conf_fits: dict[str, tuple[float, float]] = {}
        for key in QUESTION_KEYS:
            fits[key] = _fit([(getattr(answers_by_job[i], key).value, getattr(by_job[i][1], key).value) for i in train
                              if getattr(by_job[i][1], key) is not None])
            if key in SCORE_KEYS:
                conf_fits[key] = _fit([(getattr(answers_by_job[i], key).confidence, getattr(by_job[i][1], key).confidence)
                                       for i in train if getattr(by_job[i][1], key).confidence is not None])
        for i in test:
            context, jev = by_job[i]
            raw = answers_by_job[i]
            values = {}
            for key in QUESTION_KEYS:
                signal = getattr(raw, key)
                if key in SCORE_KEYS:
                    values[key] = JevSignal(
                        question_type="score", value=_apply(fits[key], signal.value),
                        confidence=_apply(conf_fits[key], signal.confidence), raw_value=_apply(fits[key], signal.value) * 4,
                    )
                else:
                    value = _apply(fits[key], signal.value)
                    values[key] = JevSignal(question_type="noul", value=value, raw_value=value)
            calibrated = decide(context, JevAnswers.model_validate(values), model + "+calibrated")
            jev_decision = decide(context, jev, "jev")
            matrix[(jev_decision, calibrated)] += 1
            total += 1
            agree += calibrated == jev_decision
    print(f"after a straight-line calibration (cross-fitted): same final decision {agree}/{total} = {agree / max(1, total):.0%}")
    print("Jev -> calibrated:", {f"{a}->{b}": n for (a, b), n in sorted(matrix.items())})
    apply_jev = sum(1 for (a, _), n in matrix.items() if a == "APPLY" for _ in range(n))
    both_apply = matrix.get(("APPLY", "APPLY"), 0)
    print(f"Jev APPLY found by the other engine: {both_apply}/{apply_jev}; "
          f"extra APPLY it adds: {sum(n for (a, b), n in matrix.items() if b == 'APPLY' and a != 'APPLY')}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("candidate", type=Path)
    parser.add_argument("out", type=Path)
    parser.add_argument("--engine", default="claude", choices=("claude",))
    parser.add_argument("--model", default="claude-haiku-5-5")
    parser.add_argument("--per-class", type=int, default=40)
    parser.add_argument("--workers", type=int, default=6)
    args = parser.parse_args()
    candidate = load_candidate_config(args.candidate)
    engine = ClaudeJobDecisionEngine(model=args.model)
    factory = create_session_factory(create_database_engine())

    with factory() as session:
        chosen, identity = pick(session, candidate, args.per_class)
        work = []
        for evaluation in chosen:
            context = context_for(session, evaluation, candidate, identity)
            jev = stored_answers(evaluation)
            if context is not None and jev is not None:
                work.append((evaluation, context, jev))
    print(f"offers: {len(work)} (of {len(chosen)} picked)", flush=True)

    answers_by_job: dict[str, JevAnswers] = {}

    def run(item):
        evaluation, context, jev = item
        started = time.monotonic()
        try:
            evidence = engine.evaluate(context)
        except Exception as error:  # noqa: BLE001 - one failure must not stop the comparison
            return {"job_id": str(evaluation.job_id), "error": type(error).__name__}
        seconds = time.monotonic() - started
        answers_by_job[str(evaluation.job_id)] = evidence.answers
        return {
            "job_id": str(evaluation.job_id),
            "jev_decision": decide(context, jev, "jev"),
            "other_decision": decide(context, evidence.answers, args.model),
            "stored_decision": evaluation.decision,
            "seconds": seconds,
            "input_tokens": evidence.input_tokens,
            "output_tokens": evidence.output_tokens,
            "jev": {k: getattr(jev, k).value if getattr(jev, k) else None for k in QUESTION_KEYS},
            "jev_conf": {k: getattr(jev, k).confidence if getattr(jev, k) else None for k in QUESTION_KEYS},
            "other": {k: getattr(evidence.answers, k).value for k in QUESTION_KEYS},
            "other_conf": {k: getattr(evidence.answers, k).confidence for k in QUESTION_KEYS},
        }

    with ThreadPoolExecutor(args.workers) as pool:
        results = list(pool.map(run, work))
    args.out.write_text(json.dumps(results, indent=1) + "\n", encoding="utf-8")

    good = [r for r in results if "error" not in r]
    print(f"answered: {len(good)}  errors: {len(results) - len(good)}")
    agree = sum(1 for r in good if r["jev_decision"] == r["other_decision"])
    print(f"same final decision: {agree}/{len(good)} = {agree / max(1, len(good)):.0%}")
    matrix = Counter((r["jev_decision"], r["other_decision"]) for r in good)
    print("Jev -> other:", {f"{a}->{b}": n for (a, b), n in sorted(matrix.items())})
    for key in QUESTION_KEYS:
        pairs = [(r["jev"][key], r["other"][key]) for r in good if r["jev"][key] is not None]
        mae = statistics.mean(abs(a - b) for a, b in pairs)
        rho = rank_correlation([a for a, _ in pairs], [b for _, b in pairs])
        print(f"  {key:26} mean abs diff {mae:.2f}  rank correlation {rho if rho is None else round(rho, 2)}")
    report_calibration(work, good, answers_by_job, args.model)
    tin, tout = sum(r["input_tokens"] or 0 for r in good), sum(r["output_tokens"] or 0 for r in good)
    price_in, price_out = PRICES.get(args.model, (0.0, 0.0))
    cost = (tin * price_in + tout * price_out) / 1_000_000
    print(f"tokens: {tin} in, {tout} out -> ${cost:.4f} total, ${cost / max(1, len(good)):.5f} per offer")
    print(f"seconds per call: median {statistics.median(r['seconds'] for r in good):.1f}, max {max(r['seconds'] for r in good):.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
