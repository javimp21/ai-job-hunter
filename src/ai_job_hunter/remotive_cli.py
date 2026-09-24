"""Manual preview and ingestion commands for Remotive."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from ai_job_hunter.candidates import (
    CandidateConfig,
    CandidateConfigError,
    JobFacts,
    PreFilterDecision,
    evaluate_job,
    load_candidate_config,
)
from ai_job_hunter.connectors.remotive import RemotiveConnector, RemotiveConnectorError
from ai_job_hunter.db.session import create_database_engine, create_session_factory
from ai_job_hunter.domain.normalized_job import NormalizedJob
from ai_job_hunter.services.pipeline import PipelineSummary, run_ingestion_pipeline
from ai_job_hunter.snapshots import (
    RemotiveSnapshotError,
    load_remotive_snapshot,
    save_remotive_snapshot,
)

LOGGER = logging.getLogger("ai_job_hunter.remotive")


def main(argv: Sequence[str] | None = None) -> int:
    _configure_unicode_output()
    parser = argparse.ArgumentParser(
        description="Preview, snapshot, replay, or ingest jobs from Remotive."
    )
    parser.add_argument("--limit", type=int, help="maximum API results (default: 5)")
    parser.add_argument("--all", action="store_true", help="request all active API results")
    parser.add_argument(
        "--show",
        type=int,
        help="maximum offers to display per result group (default: 5 PASS, 8 REVIEW/REJECT)",
    )
    parser.add_argument("--search", help="Remotive's title/description search filter")
    parser.add_argument("--category", help="Remotive category name or slug")
    parser.add_argument("--company-name", help="Remotive company-name filter")
    parser.add_argument(
        "--save-snapshot",
        metavar="PATH",
        help="save the fetched, normalized Remotive offers to a local snapshot",
    )
    parser.add_argument(
        "--snapshot",
        metavar="PATH",
        help="load offers from a local snapshot without accessing the network",
    )
    parser.add_argument(
        "--ingest",
        action="store_true",
        help="persist offers through the existing pipeline using DATABASE_URL",
    )
    parser.add_argument(
        "--candidate-config",
        metavar="PATH",
        help="evaluate fetched or snapshot offers with a local candidate JSON config",
    )
    args = parser.parse_args(argv)

    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be a positive integer")
    if args.show is not None and args.show < 0:
        parser.error("--show cannot be negative")
    if args.ingest and args.candidate_config:
        parser.error("--candidate-config is preview-only and cannot be combined with --ingest")
    if args.ingest and (args.snapshot or args.save_snapshot):
        parser.error("snapshot options cannot be combined with --ingest")
    if args.snapshot and args.save_snapshot:
        parser.error("--snapshot and --save-snapshot cannot be used together")
    if args.snapshot and (
        args.limit is not None or args.all or args.search or args.category or args.company_name
    ):
        parser.error("API filters cannot be used when replaying a snapshot")

    candidate_config = None
    if args.candidate_config:
        try:
            candidate_config = load_candidate_config(args.candidate_config)
        except CandidateConfigError as error:
            parser.error(str(error))

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if args.snapshot:
        try:
            offers = load_remotive_snapshot(args.snapshot)
        except RemotiveSnapshotError as error:
            LOGGER.error("%s", error)
            return 1
        LOGGER.info("Loaded %d Remotive jobs from snapshot", len(offers))
    else:
        connector = RemotiveConnector(
            limit=None if args.all else (args.limit if args.limit is not None else 5),
            search=args.search,
            category=args.category,
            company_name=args.company_name,
        )
        try:
            with connector:
                if args.ingest:
                    summary = _ingest(connector)
                    _log_summary(summary)
                    return 1 if summary.failed else 0

                offers = connector.fetch_jobs()
        except RemotiveConnectorError as error:
            LOGGER.error("Remotive request failed: %s", error)
            return 1

        LOGGER.info("Fetched %d jobs from Remotive", len(offers))
        if args.save_snapshot:
            try:
                snapshot_path = save_remotive_snapshot(args.save_snapshot, offers)
            except RemotiveSnapshotError as error:
                LOGGER.error("%s", error)
                return 1
            LOGGER.info("Saved normalized Remotive snapshot to %s", snapshot_path)

    if args.candidate_config:
        report = _build_evaluation_report(offers, candidate_config)
        _print_evaluation_report(report, show=args.show)
        return 0

    show = 3 if args.show is None else args.show
    for offer in offers[:show]:
        company = offer.company_name or "Company not supplied"
        print(f"- {offer.title} | {company}")
        print(f"  Source: Remotive ({offer.source_url})")
    return 0


def _build_evaluation_report(
    offers: list[NormalizedJob],
    candidate_config: CandidateConfig,
) -> list[dict[str, Any]]:
    """Create complete structured decision records for every normalized offer."""

    report: list[dict[str, Any]] = []
    for offer in offers:
        facts = JobFacts.from_normalized_job(offer)
        result = evaluate_job(facts, candidate_config)
        report.append(
            {
                "title": facts.title,
                "company": offer.company_name,
                "source_url": offer.source_url,
                "location": facts.location,
                "remote_policy": facts.remote_policy.value if facts.remote_policy else None,
                "remote_eligibility": facts.remote_eligibility.value,
                "salary": {
                    "minimum": _decimal_text(facts.salary_min),
                    "maximum": _decimal_text(facts.salary_max),
                    "currency": facts.currency,
                    "period": facts.salary_period.value if facts.salary_period else None,
                },
                "inferred_seniority": facts.inferred_seniority.value,
                "technologies": list(facts.technologies),
                "role_match": {
                    "status": result.signals.preferred_role.status.value,
                    "reason": result.signals.preferred_role.reason,
                },
                "geographic_result": {
                    "status": result.signals.geography.status.value,
                    "reason": result.signals.geography.reason,
                },
                "salary_result": {
                    "evaluation": result.signals.salary.evaluation.value,
                    "reason": result.signals.salary.reason,
                },
                "decision": result.decision.value,
                "reasons": list(result.reasons),
            }
        )
    return report


def _decimal_text(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None


def _print_evaluation_report(report: list[dict[str, Any]], *, show: int | None) -> None:
    counts = {
        decision: sum(item["decision"] == decision.value for item in report)
        for decision in PreFilterDecision
    }
    print(f"Fetched: {len(report)}")
    print(f"TOTAL: {len(report)}")
    print(f"PASS: {counts[PreFilterDecision.PASS]}")
    print(f"REVIEW: {counts[PreFilterDecision.REVIEW]}")
    print(f"REJECT: {counts[PreFilterDecision.REJECT]}")

    default_limits = {
        PreFilterDecision.PASS: 5,
        PreFilterDecision.REVIEW: 8,
        PreFilterDecision.REJECT: 8,
    }
    for decision, default_limit in default_limits.items():
        group = [item for item in report if item["decision"] == decision.value]
        limit = default_limit if show is None else show
        print(f"\n=== {decision.value}: showing {min(limit, len(group))} of {len(group)} ===")
        for item in group[:limit]:
            salary = item["salary"]
            salary_text = "unknown"
            if any(salary[key] is not None for key in ("minimum", "maximum")):
                low = salary["minimum"] if salary["minimum"] is not None else "?"
                high = salary["maximum"] if salary["maximum"] is not None else "?"
                currency = salary["currency"] or "?"
                period = salary["period"] or "?"
                salary_text = f"{low}-{high} {currency} / {period}"
            technologies = ", ".join(item["technologies"]) or "none detected"
            company = item["company"] or "Company not supplied"
            print(f"TITLE: {item['title']} | COMPANY: {company}")
            print(f"LOCATION: {item['location'] or 'unknown'}")
            print(f"REMOTE: policy={item['remote_policy'] or 'unknown'}; eligibility={item['remote_eligibility']}")
            print(f"SALARY: {salary_text}")
            print(f"SENIORITY: {item['inferred_seniority']}")
            print(f"TECHNOLOGIES: {technologies}")
            print(
                "ROLE MATCH: "
                f"{item['role_match']['status']} | {item['role_match']['reason']}"
            )
            print(
                "GEOGRAPHY: "
                f"{item['geographic_result']['status']} | {item['geographic_result']['reason']}"
            )
            print(
                "SALARY RESULT: "
                f"{item['salary_result']['evaluation']} | {item['salary_result']['reason']}"
            )
            print(f"DECISION: {item['decision']}")
            print("REASONS:")
            for reason in item["reasons"]:
                print(f"  - {reason}")
            print(f"URL: {item['source_url'] or 'none'}")


def _configure_unicode_output() -> None:
    """Keep Unicode console output from aborting a report on Windows."""

    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(errors="backslashreplace")
            except (OSError, ValueError):
                # Some wrapped streams do not support changing their error mode.
                pass


def _ingest(connector: RemotiveConnector) -> PipelineSummary:
    engine = create_database_engine()
    try:
        session_factory = create_session_factory(engine)
        with session_factory() as session:
            return run_ingestion_pipeline(connector, session)
    finally:
        engine.dispose()


def _log_summary(summary: PipelineSummary) -> None:
    LOGGER.info("Fetched %d jobs from Remotive", summary.fetched)
    LOGGER.info("Created: %d", summary.created)
    LOGGER.info("Already known: %d", summary.already_known)
    LOGGER.info("Matched existing: %d", summary.matched_existing)
    LOGGER.info("Possible matches: %d", summary.possible_match)
    LOGGER.info("Failed: %d", summary.failed)
    for failure in summary.failures:
        LOGGER.error("%s: %s", failure.provider, failure.message)


if __name__ == "__main__":
    raise SystemExit(main())
