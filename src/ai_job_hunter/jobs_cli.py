"""Fetch, snapshot, replay, pre-filter, and optionally ingest configured ATS jobs."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from decimal import Decimal

import httpx

from ai_job_hunter.candidates import (
    CandidateConfigError,
    PreFilterDecision,
    evaluate_job,
    load_candidate_config,
)
from ai_job_hunter.candidates.facts import JobFacts
from ai_job_hunter.connectors import FakeJobConnector, build_job_connectors
from ai_job_hunter.connectors.ashby import AshbyConnectorError
from ai_job_hunter.connectors.greenhouse import GreenhouseConnectorError
from ai_job_hunter.connectors.lever import LeverConnectorError
from ai_job_hunter.connectors.smartrecruiters import SmartRecruitersConnectorError
from ai_job_hunter.connectors.teamtailor import TeamtailorConnectorError
from ai_job_hunter.db.session import create_database_engine, create_session_factory
from ai_job_hunter.domain.normalized_job import NormalizedJob, SalaryPeriod
from ai_job_hunter.job_sources import JobSourcesConfigError, load_job_sources
from ai_job_hunter.services.pipeline import PipelineSummary, run_ingestion_pipeline
from ai_job_hunter.snapshots import JobSnapshotError, load_job_snapshot, save_job_snapshot

LOGGER = logging.getLogger("ai_job_hunter.jobs")
ATS_USER_AGENT = "AI-Job-Hunter/0.1 (personal job discovery)"


def main(argv: Sequence[str] | None = None) -> int:
    _configure_unicode_output()
    parser = argparse.ArgumentParser(
        description="Fetch or replay public job board listings and run the deterministic pre-filter."
    )
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--sources", metavar="PATH", help="local JSON list of Greenhouse/Lever/Ashby/Teamtailor/SmartRecruiters boards")
    inputs.add_argument("--snapshot", metavar="PATH", help="offline normalized snapshot to replay")
    parser.add_argument("--candidate-config", metavar="PATH", help="local candidate config for pre-filtering")
    parser.add_argument("--save-snapshot", metavar="PATH", help="save fetched normalized offers")
    parser.add_argument("--ingest", action="store_true", help="persist offers through the existing pipeline")
    parser.add_argument("--show", type=int, help="maximum JEV-eligible offers to print; default: all")
    parser.add_argument("--timeout", type=float, default=20.0, help="HTTP timeout in seconds (default: 20)")
    args = parser.parse_args(argv)

    if args.show is not None and args.show < 0:
        parser.error("--show cannot be negative")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    if args.snapshot and args.save_snapshot:
        parser.error("--save-snapshot cannot be used while replaying a snapshot")

    candidate = None
    if args.candidate_config:
        try:
            candidate = load_candidate_config(args.candidate_config)
        except CandidateConfigError as error:
            parser.error(str(error))

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    source_errors = 0
    if args.snapshot:
        try:
            offers = load_job_snapshot(args.snapshot)
        except JobSnapshotError as error:
            LOGGER.error("%s", error)
            return 1
        LOGGER.info("Loaded %d normalized jobs from snapshot", len(offers))
    else:
        try:
            config = load_job_sources(args.sources)
        except JobSourcesConfigError as error:
            parser.error(str(error))
        offers = []
        with httpx.Client(
            timeout=args.timeout,
            headers={"Accept": "application/json", "User-Agent": ATS_USER_AGENT},
        ) as client:
            connectors = build_job_connectors(config, client=client, timeout=args.timeout)
            for source, connector in zip(config.sources, connectors, strict=True):
                try:
                    jobs = connector.fetch_jobs()
                    offers.extend(jobs)
                    LOGGER.info(
                        "Fetched %d jobs from %s (%s)",
                        len(jobs),
                        source.provider,
                        source.identifier,
                    )
                except (
                    GreenhouseConnectorError,
                    LeverConnectorError,
                    AshbyConnectorError,
                    SmartRecruitersConnectorError,
                    TeamtailorConnectorError,
                ) as error:
                    source_errors += 1
                    LOGGER.error("Failed source %s (%s): %s", source.provider, source.identifier, error)
                except Exception as error:
                    source_errors += 1
                    LOGGER.exception(
                        "Unexpected failure for source %s (%s): %s",
                        source.provider,
                        source.identifier,
                        error,
                    )
        LOGGER.info("Fetched %d jobs across configured sources", len(offers))
        if args.save_snapshot:
            try:
                saved_path = save_job_snapshot(args.save_snapshot, offers)
            except JobSnapshotError as error:
                LOGGER.error("%s", error)
                return 1
            LOGGER.info("Saved normalized multi-source snapshot to %s", saved_path)

    if candidate is not None:
        _print_prefilter(offers, candidate, show=args.show)
    else:
        print(f"TOTAL: {len(offers)}")

    if args.ingest:
        _log_ingestion(_ingest(offers))
    return 1 if source_errors else 0


def _print_prefilter(offers: list[NormalizedJob], candidate, *, show: int | None) -> None:
    evaluations = []
    for offer in offers:
        facts = JobFacts.from_normalized_job(offer)
        evaluations.append((offer, facts, evaluate_job(facts, candidate)))
    hard_skips = sum(result.decision is PreFilterDecision.REJECT for _, _, result in evaluations)
    eligible = [
        item for item in evaluations if item[2].decision is not PreFilterDecision.REJECT
    ]
    display_limit = len(eligible) if show is None else min(show, len(eligible))
    print(f"TOTAL: {len(offers)}")
    print(f"HARD SKIP: {hard_skips}")
    print(f"JEV ELIGIBLE: {len(eligible)}")
    print(f"JEV ELIGIBLE OFFERS: showing {display_limit} of {len(eligible)}")
    for offer, facts, result in eligible[:display_limit]:
        company = offer.company_name or "Company not supplied"
        salary = _salary_text(
            facts.salary_min,
            facts.salary_max,
            facts.currency,
            facts.salary_period,
        )
        technologies = ", ".join(facts.technologies) or "unknown"
        print(f"\nTITLE: {facts.title}")
        print(f"COMPANY: {company}")
        print(f"PROVIDER: {offer.provider}")
        print(f"LOCATION: {facts.location or 'unknown'}")
        print(f"SALARY: {salary}")
        print(f"SENIORITY: {facts.inferred_seniority.value}")
        print(f"TECHNOLOGIES: {technologies}")
        print(f"DETERMINISTIC DECISION: {result.decision.value}")
        print("DETERMINISTIC REASONS:")
        for reason in result.reasons:
            print(f"  - {reason}")
        print(f"URL: {offer.source_url or offer.canonical_url or 'unknown'}")


def _salary_text(
    minimum: Decimal | None,
    maximum: Decimal | None,
    currency: str | None,
    period: SalaryPeriod | None,
) -> str:
    if minimum is None and maximum is None:
        return "unknown"
    low = format(minimum, "f") if minimum is not None else "?"
    high = format(maximum, "f") if maximum is not None else "?"
    return f"{low}-{high} {currency or '?'} / {period.value if period else '?'}"


def _ingest(offers: list[NormalizedJob]) -> PipelineSummary:
    engine = create_database_engine()
    try:
        with create_session_factory(engine)() as session:
            # The fetched batch is passed through the same ingestion and deduplication pipeline.
            return run_ingestion_pipeline(FakeJobConnector(offers), session)
    finally:
        engine.dispose()


def _log_ingestion(summary: PipelineSummary) -> None:
    print("\nINGESTION:")
    print(f"CREATED: {summary.created}")
    print(f"ALREADY KNOWN: {summary.already_known}")
    print(f"MATCHED EXISTING: {summary.matched_existing}")
    print(f"POSSIBLE MATCH: {summary.possible_match}")
    print(f"FAILED: {summary.failed}")
    for failure in summary.failures:
        print(f"  - {failure.provider}: {failure.message}")


def _configure_unicode_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(errors="backslashreplace")
            except (OSError, ValueError):
                pass


if __name__ == "__main__":
    raise SystemExit(main())
