"""Offline comparison of decision policies over already-cached Jev evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ai_job_hunter.candidates import CandidateConfigError, load_candidate_config
from ai_job_hunter.decision_engine import (
    POLICY_VERSION_V1,
    POLICY_VERSION_V2,
    DecisionCache,
    DecisionEvidence,
    FinalDecision,
    JobDecisionContext,
    JobDecisionError,
    JobDecisionResult,
    apply_versioned_decision_policy,
    build_decision_contexts,
)
from ai_job_hunter.snapshots import JobSnapshotError, load_job_snapshot

DEFAULT_BENCHMARK = Path("data/local/jev-benchmark-2026-09-24.local.json")
DEFAULT_SNAPSHOT = Path("data/local/greenhouse-lever-snapshot-2026-09-24.local.json")
DEFAULT_CANDIDATE_CONFIG = Path("candidate.local.json")
DEFAULT_CACHE = Path("data/local/job-decision-cache.local.json")
DEFAULT_REPORT = Path("data/local/job-decision-v1-v2-comparison.local.md")


@dataclass(frozen=True, slots=True)
class PolicyComparisonRow:
    context: JobDecisionContext
    v1: JobDecisionResult
    v2: JobDecisionResult

    @property
    def changed(self) -> bool:
        return self.v1.final_decision is not self.v2.final_decision


def compare_cached_policies(
    contexts: list[JobDecisionContext],
    cache: DecisionCache,
    *,
    engine_identity: str,
    rubric_version: str,
) -> list[PolicyComparisonRow]:
    """Apply both policies to Jev answers read from cache; this function has no engine input."""

    rows: list[PolicyComparisonRow] = []
    for context in contexts:
        key = cache.key_for(context, engine_identity, rubric_version)
        cached = cache.get(key)
        if cached is None or cached.jev_answers is None:
            identifier = _job_identifier(context)
            raise JobDecisionError(f"No cached Jev answers exist for benchmark offer '{identifier}'.")
        evidence = DecisionEvidence(
            answers=cached.jev_answers,
            model_version=cached.model_version or "unknown-cached-model",
            engine_configuration=cached.engine_configuration or engine_identity,
            input_tokens=cached.input_tokens,
            output_tokens=cached.output_tokens,
        )
        v1 = apply_versioned_decision_policy(
            context,
            evidence,
            policy_version=POLICY_VERSION_V1,
            rubric_version=rubric_version,
        ).model_copy(update={"cache_hit": True})
        v2 = apply_versioned_decision_policy(
            context,
            evidence,
            policy_version=POLICY_VERSION_V2,
            rubric_version=rubric_version,
        ).model_copy(update={"cache_hit": True})
        rows.append(PolicyComparisonRow(context=context, v1=v1, v2=v2))
    return rows


def render_comparison_report(
    rows: list[PolicyComparisonRow],
    *,
    benchmark_date: str,
    snapshot_sha256: str,
    model_version: str,
    rubric_version: str,
) -> str:
    v1_counts = _distribution(row.v1.final_decision for row in rows)
    v2_counts = _distribution(row.v2.final_decision for row in rows)
    lines = [
        "# job_decision_v1 vs job_decision_v2",
        "",
        "## Alcance y procedencia",
        "",
        f"- Benchmark: {benchmark_date}; ofertas comparadas: {len(rows)}.",
        f"- Jev model: {model_version}; rubric de preguntas conservado: {rubric_version}.",
        f"- Snapshot SHA-256: {snapshot_sha256}.",
            f"- Las {len(rows)} respuestas se leyeron de data/local/job-decision-cache.local.json. El comparador no importa ni instancia un motor Jev y falla si falta una entrada cacheada.",
        "- No se cambiaron preguntas, perfil, preferencias, job facts, muestra, snapshot ni política de hard rejects.",
        "- No hay etiquetas humanas definitivas cargadas; no se crearon ni rellenaron etiquetas locales.",
        "",
        "## Reglas v2",
        "",
        "- Los rechazos duros deterministas existentes siguen siendo SKIP, antes de aplicar cualquier señal Jev.",
        "- SKIP también si role relevance < 0.20 o experience accessibility < 0.15.",
        "- SKIP por discrepancia de familia si role < 0.45, backend normalizado < 0.60 y stack < 0.45; o por relevancia moderada (role < 0.75) junto con stack < 0.40 y flexibilidad < 0.35.",
        "- SKIP también si backend normalizado < 0.25 y role < 0.60.",
        "- APPLY estándar requiere role ≥ 0.75, backend normalizado ≥ 0.70, stack ≥ 0.60, flexibilidad ≥ 0.50 y experiencia ≥ 0.50.",
        "- Excepción de upside: experiencia ≥ 0.40, Career Value normalizado ≥ 0.90 con confianza ≥ 0.40, role ≥ 0.85, backend ≥ 0.90, stack ≥ 0.70 y flexibilidad ≥ 0.65.",
        "- La calidad observable no es un gate APPLY. Una descripción menor de 1.000 caracteres genera INSUFFICIENT_DESCRIPTION; con descripción suficiente, quality baja por sí sola no bloquea un encaje fuerte.",
        "- REVIEW se explica con códigos estructurados para incertidumbres materiales, entre ellos experiencia borderline, familia de rol, stack, descripción, compensación y ubicación.",
        "- Career Value solo relaja experiencia dentro de la excepción anterior; no anula hard rejects ni combinaciones de irrelevancia.",
        "",
        "## Distribución",
        "",
        "| Política | APPLY | REVIEW | SKIP |",
        "|---|---:|---:|---:|",
        f"| {POLICY_VERSION_V1} | {v1_counts['APPLY']} | {v1_counts['REVIEW']} | {v1_counts['SKIP']} |",
        f"| {POLICY_VERSION_V2} | {v2_counts['APPLY']} | {v2_counts['REVIEW']} | {v2_counts['SKIP']} |",
        "",
        "## Comparación de las 12 ofertas",
        "",
        "| Offer | V1 | V2 | Changed? | Why? |",
        "|---|---|---|---|---|",
    ]
    for row in rows:
        title = row.context.offer.title
        company = row.context.offer.company_name or "Company not supplied"
        offer = _escape_table(f"{title} — {company}")
        changed = "Sí" if row.changed else "No"
        why = _why_v2(row.v2).replace("\n", " ")
        lines.append(
            f"| {offer} | {row.v1.final_decision.value} | {row.v2.final_decision.value} | {changed} | {_escape_table(why)} |"
        )
    changed_rows = [row for row in rows if row.changed]
    lines.extend(["", "## Cambios", ""])
    if not changed_rows:
        lines.append("No hubo cambios de decisión.")
    else:
        for row in changed_rows:
            lines.append(
                f"- {_escape_inline(row.context.offer.title)} — {_escape_inline(row.context.offer.company_name or 'Company not supplied')}: "
                f"{row.v1.final_decision.value} → {row.v2.final_decision.value}. {_why_v2(row.v2)}"
            )
    lines.extend(
        [
            "",
            "## Códigos estructurados para REVIEW",
            "",
            "- LOCATION_UNCERTAIN: confirmar ubicación o modalidad de trabajo cuando el anuncio explicita hybrid/onsite fuera de ubicaciones configuradas, pero los hechos normalizados no lo clasifican.",
            "- COMPENSATION_UNKNOWN: hay un umbral salarial configurado y el anuncio no da un rango comparable; se usa como motivo de REVIEW cuando el encaje no basta para APPLY.",
            "- EXPERIENCE_BORDERLINE: experiencia por encima del corte SKIP, pero fuera de las rutas APPLY.",
            "- ROLE_FAMILY_UNCERTAIN: relevancia o encaje backend insuficientes para decidir la familia del rol.",
            "- INSUFFICIENT_DESCRIPTION: anuncio demasiado corto o con quality baja cuando todavía deja dudas sobre responsabilidades/requisitos.",
            "- STACK_UNCERTAIN: transferencia de tecnologías o flexibilidad insuficientes para APPLY y sin evidencia suficiente para SKIP.",
            "- SENIORITY_UNCERTAIN: la preferencia tiene límites y la oferta no permite verificar seniority.",
            "- OTHER: incertidumbre material no cubierta por los códigos anteriores.",
            "",
            "## Límites",
            "",
            "- Comparación descriptiva sobre n=12; no es ground truth ni estimación de desempeño en producción.",
            "- Las etiquetas y notas humanas siguen vacías hasta que el usuario aporte ground truth.",
            "",
        ]
    )
    return "\n".join(lines)


def run_cached_comparison(
    *,
    benchmark_path: str | Path = DEFAULT_BENCHMARK,
    snapshot_path: str | Path = DEFAULT_SNAPSHOT,
    candidate_config_path: str | Path = DEFAULT_CANDIDATE_CONFIG,
    cache_path: str | Path = DEFAULT_CACHE,
    output_path: str | Path = DEFAULT_REPORT,
) -> list[PolicyComparisonRow]:
    benchmark_file = Path(benchmark_path)
    try:
        benchmark: dict[str, Any] = json.loads(benchmark_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise JobDecisionError(f"Could not read benchmark file '{benchmark_file}': {error}") from error
    if benchmark.get("status") != "completed":
        raise JobDecisionError("The preregistered Jev benchmark is not complete.")
    inputs = benchmark.get("inputs", {})
    rubric_version = inputs.get("rubric_version")
    expected_hash = inputs.get("snapshot_sha256")
    if not isinstance(rubric_version, str) or not isinstance(expected_hash, str):
        raise JobDecisionError("The benchmark is missing its rubric version or snapshot hash.")

    snapshot_file = Path(snapshot_path)
    try:
        actual_hash = hashlib.sha256(snapshot_file.read_bytes()).hexdigest()
    except OSError as error:
        raise JobDecisionError(f"Could not read snapshot '{snapshot_file}': {error}") from error
    if actual_hash != expected_hash:
        raise JobDecisionError("The supplied snapshot hash does not match the preregistered benchmark.")

    try:
        offers = load_job_snapshot(snapshot_file)
        candidate = load_candidate_config(candidate_config_path)
    except (JobSnapshotError, CandidateConfigError) as error:
        raise JobDecisionError(str(error)) from error
    contexts_by_identity = {
        (context.offer.provider, context.offer.external_id): context
        for context in build_decision_contexts(offers, candidate)
    }

    sample = benchmark.get("sample")
    if not isinstance(sample, list) or len(sample) != benchmark.get("preflight", {}).get("sample_size"):
        raise JobDecisionError("The benchmark sample does not match its preregistered size.")
    contexts: list[JobDecisionContext] = []
    for item in sample:
        identity = (item.get("provider"), item.get("external_id"))
        context = contexts_by_identity.get(identity)
        if context is None:
            raise JobDecisionError(f"The preregistered offer '{identity[0]}:{identity[1]}' is missing from the snapshot.")
        contexts.append(context)

    first_run_results = benchmark.get("first_run", {}).get("results", [])
    if len(first_run_results) != len(sample):
        raise JobDecisionError("The benchmark is missing first-run Jev results for the full sample.")
    expected_v1 = {
        result["external_id"]: result["final_decision"]
        for result in first_run_results
    }
    engine_identity = sample[0].get("jev", {}).get("engine_configuration")
    if not isinstance(engine_identity, str):
        raise JobDecisionError("The benchmark is missing the Jev cache identity.")

    cache = DecisionCache(cache_path)
    rows = compare_cached_policies(
        contexts,
        cache,
        engine_identity=engine_identity,
        rubric_version=rubric_version,
    )
    if any(row.v1.final_decision.value != expected_v1[row.context.offer.external_id] for row in rows):
        raise JobDecisionError("Replaying cached signals did not reproduce the stored v1 decisions.")
    for item, row in zip(sample, rows, strict=True):
        actual_answers = row.v1.jev_answers.model_dump(mode="json") if row.v1.jev_answers else None
        if actual_answers != item.get("jev", {}).get("answers"):
            raise JobDecisionError(
                f"Cached Jev signals no longer match the benchmark record for '{item.get('external_id')}'."
            )

    model_version = sample[0].get("jev", {}).get("model_returned", "unknown")
    report = render_comparison_report(
        rows,
        benchmark_date=str(benchmark.get("benchmark_date", "unknown")),
        snapshot_sha256=expected_hash,
        model_version=str(model_version),
        rubric_version=rubric_version,
    )
    report_path = Path(output_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare job decision policies using only existing cached Jev answers."
    )
    parser.add_argument("--benchmark", default=str(DEFAULT_BENCHMARK))
    parser.add_argument("--snapshot", default=str(DEFAULT_SNAPSHOT))
    parser.add_argument("--candidate-config", default=str(DEFAULT_CANDIDATE_CONFIG))
    parser.add_argument("--decision-cache", default=str(DEFAULT_CACHE))
    parser.add_argument("--output", default=str(DEFAULT_REPORT))
    args = parser.parse_args(argv)
    try:
        rows = run_cached_comparison(
            benchmark_path=args.benchmark,
            snapshot_path=args.snapshot,
            candidate_config_path=args.candidate_config,
            cache_path=args.decision_cache,
            output_path=args.output,
        )
    except JobDecisionError as error:
        print(f"Policy comparison failed: {error}", file=sys.stderr)
        return 1
    changes = sum(row.changed for row in rows)
    print(f"Compared {len(rows)} cached Jev results; {changes} decisions changed.")
    print(f"Report: {args.output}")
    print("No Jev engine was instantiated; no network requests were made.")
    return 0


def _job_identifier(context: JobDecisionContext) -> str:
    return f"{context.offer.provider}:{context.offer.external_id or context.offer.source_url or 'unknown'}"


def _distribution(decisions: Any) -> dict[str, int]:
    counts = Counter(decision.value for decision in decisions)
    return {decision.value: counts[decision.value] for decision in FinalDecision}


def _why_v2(result: JobDecisionResult) -> str:
    if result.review_reasons:
        codes = ", ".join(reason.code.value for reason in result.review_reasons)
        return f"{codes}: " + " ".join(reason.message for reason in result.review_reasons)
    return " ".join(result.reasons)


def _escape_table(value: str) -> str:
    return value.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def _escape_inline(value: str) -> str:
    return value.replace("`", "'").replace("\n", " ").replace("\r", " ")


if __name__ == "__main__":
    raise SystemExit(main())
