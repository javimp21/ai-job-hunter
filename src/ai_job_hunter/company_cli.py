"""Inspect and refresh company facts without altering job decisions."""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from uuid import UUID

import httpx
from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError

from ai_job_hunter.candidates import (
    CandidateConfigError,
    JobFacts,
    PreFilterDecision,
    evaluate_job,
    load_candidate_config,
)
from ai_job_hunter.connectors import FakeJobConnector, build_job_connectors
from ai_job_hunter.connectors.ashby import AshbyConnectorError
from ai_job_hunter.connectors.greenhouse import GreenhouseConnectorError
from ai_job_hunter.connectors.lever import LeverConnectorError
from ai_job_hunter.connectors.smartrecruiters import SmartRecruitersConnectorError
from ai_job_hunter.connectors.teamtailor import TeamtailorConnectorError
from ai_job_hunter.connectors.personio import PersonioConnectorError
from ai_job_hunter.connectors.workable import WorkableConnectorError
from ai_job_hunter.company_sources import (
    DEFAULT_SNAPSHOT_DIR,
    CompanySourceError,
    refresh_company_source_snapshots,
)
from ai_job_hunter.db.base import Base
from ai_job_hunter.db.session import create_database_engine, create_session_factory
from ai_job_hunter.domain.company_intelligence import ATSProvider, CompanyFacts
from ai_job_hunter.domain.normalized_job import NormalizedJob
from ai_job_hunter.job_sources import JobSourceSpec, JobSourcesConfig
from ai_job_hunter.snapshots import JobSnapshotError, save_job_snapshot
from ai_job_hunter.services.company_intelligence import (
    CompanyIdentityAmbiguous,
    CompanyMonitorFilters,
    find_companies_to_monitor,
    get_company_facts,
    get_company_facts_for_job,
    build_company_monitor_targets,
    refresh_company_evidence,
    summarize_company_catalog,
    sync_ats_evidence_from_job_sources,
)
from ai_job_hunter.services.pipeline import PipelineSummary, run_ingestion_pipeline
from ai_job_hunter.config import get_settings


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh and inspect source-backed company facts.")
    parser.add_argument("--database-url", help="override DATABASE_URL for this invocation")
    subparsers = parser.add_subparsers(dest="command", required=True)

    refresh = subparsers.add_parser("refresh", help="fetch the supported company evidence sources")
    refresh.add_argument("--offline", action="store_true", help="replay saved source snapshots without network")
    refresh.add_argument("--snapshot-dir", type=Path, default=DEFAULT_SNAPSHOT_DIR)

    subparsers.add_parser("summary", help="show aggregate evidence counts")
    show = subparsers.add_parser("show", help="show source-backed facts for a company")
    show.add_argument("company_name")
    show_job = subparsers.add_parser("show-job", help="show company facts through a persisted job")
    show_job.add_argument("job_id", type=UUID)

    find = subparsers.add_parser("find", help="filter companies using structured facts")
    find.add_argument("--spanish-top-tech", action="store_true")
    find.add_argument("--remote-from-spain", action="store_true")
    find.add_argument("--has-career-page", action="store_true")
    find.add_argument("--supported-ats", action="store_true")
    find.add_argument("--public-salary", action="store_true")
    find.add_argument("--compensation-evidence", action="store_true")
    find.add_argument("--multiple-evidence-sources", action="store_true")
    monitor = subparsers.add_parser("monitor", help="fetch supported ATS boards from Company Intelligence")
    monitor.add_argument("--public-salary", action="store_true")
    monitor.add_argument("--compensation-evidence", action="store_true")
    monitor.add_argument("--multiple-evidence-sources", action="store_true")
    monitor.add_argument("--spanish-top-tech", action="store_true")
    monitor.add_argument("--remote-from-spain", action="store_true")
    monitor.add_argument("--supported-ats", action="store_true", help="explicitly select supported boards (always required)")
    monitor.add_argument("--company")
    monitor.add_argument("--provider", choices=("greenhouse", "lever", "ashby", "teamtailor", "smartrecruiters", "workable", "personio"))
    monitor.add_argument("--limit-companies", type=int, default=10)
    monitor.add_argument("--max-jobs-per-company", type=int, default=100)
    monitor.add_argument("--candidate-config", metavar="PATH", help="run the deterministic prefilter; no Jev calls")
    monitor.add_argument(
        "--save-snapshot",
        type=Path,
        default=Path("data/local/company-intelligence/monitor-jobs.local.json"),
    )

    # Accept the database override after the subcommand too, without resetting a global value.
    for command_parser in (refresh, subparsers.choices["summary"], show, show_job, find, monitor):
        command_parser.add_argument("--database-url", default=argparse.SUPPRESS)

    args = parser.parse_args(argv)
    if args.command == "find" and not any(
        (
            args.spanish_top_tech,
            args.remote_from_spain,
            args.has_career_page,
            args.supported_ats,
            args.public_salary,
            args.compensation_evidence,
            args.multiple_evidence_sources,
        )
    ):
        parser.error("find requires at least one structured filter.")
    if args.command == "monitor":
        if args.limit_companies < 1:
            parser.error("--limit-companies must be positive.")
        if not 1 <= args.max_jobs_per_company <= 10_000:
            parser.error("--max-jobs-per-company must be from 1 to 10000.")
        try:
            args.candidate = (
                load_candidate_config(args.candidate_config) if args.candidate_config else None
            )
        except CandidateConfigError as error:
            parser.error(str(error))

    settings = get_settings()
    if args.database_url:
        settings = settings.model_copy(update={"database_url": args.database_url})
    engine = create_database_engine(settings)
    try:
        with create_session_factory(engine)() as session:
            if args.command == "refresh":
                batches, skipped = refresh_company_source_snapshots(
                    snapshot_dir=args.snapshot_dir,
                    offline=args.offline,
                )
                result = refresh_company_evidence(session, batches, skipped_sources=skipped)
                _print_refresh(result, batches)
            elif args.command == "summary":
                _print_summary(summarize_company_catalog(session))
            elif args.command == "show":
                try:
                    facts = get_company_facts(session, args.company_name)
                except CompanyIdentityAmbiguous:
                    print(f"Company identity is ambiguous for: {args.company_name}")
                    return 2
                if facts is None:
                    _print_unknown_company(args.company_name)
                else:
                    _print_facts(facts)
            elif args.command == "show-job":
                facts = get_company_facts_for_job(session, args.job_id)
                if facts is None:
                    print(f"No company with intelligence is linked to job {args.job_id}.")
                else:
                    print(f"Job company lookup: {args.job_id}")
                    _print_facts(facts)
            elif args.command == "find":
                filters = CompanyMonitorFilters(
                    spanish_top_tech=args.spanish_top_tech,
                    remote_from_spain=args.remote_from_spain,
                    has_career_page=args.has_career_page,
                    supported_ats=args.supported_ats,
                    public_salary=args.public_salary,
                    compensation_evidence=args.compensation_evidence,
                    multiple_evidence_sources=args.multiple_evidence_sources,
                )
                facts = find_companies_to_monitor(session, filters)
                print(f"COMPANIES: {len(facts)}")
                for item in facts:
                    ats_values = {discovery.provider.value for discovery in item.ats_discoveries}
                    if not ats_values:
                        ats_values = {page.ats_provider.value for page in item.career_pages}
                    ats = ", ".join(sorted(ats_values)) or "UNKNOWN"
                    print(f"- {item.company_name} | ATS: {ats} | Sources: {item.source_count}")
            elif args.command == "monitor":
                _run_monitor(args, session)
        return 0
    except CompanySourceError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    except SQLAlchemyError as error:
        # Avoid echoing engine URLs, which can contain local database credentials.
        print(
            f"ERROR: database operation failed ({type(error).__name__}); run the Alembic migration first "
            "and verify the configured database is available.",
            file=sys.stderr,
        )
        return 1
    finally:
        engine.dispose()


def _print_refresh(result, batches) -> None:
    print("COMPANY INTELLIGENCE REFRESH")
    for batch in batches:
        print(f"SOURCE: {batch.provider}")
        print(f"  RECORDS: {result.source_record_counts.get(batch.provider, 0)}")
        print(f"  SNAPSHOT: {batch.snapshot_path}")
        print(f"  SHA256: {batch.body_sha256}")
    print(f"COMPANIES CREATED: {result.companies_created}")
    print(f"EVIDENCE CREATED: {result.evidence_created}")
    print(f"EVIDENCE UPDATED: {result.evidence_updated}")
    for skipped in result.skipped_sources:
        print(f"SKIPPED: {skipped.provider}: {skipped.reason}")
    for possible in result.companies_with_possible_matches:
        print(f"POSSIBLE MATCH, KEPT SEPARATE: {possible}")


def _print_summary(summary) -> None:
    print(f"COMPANIES: {summary.company_count}")
    print(f"EVIDENCE ITEMS: {summary.evidence_count}")
    print(f"REMOTE FROM SPAIN: {summary.companies_with_remote_from_spain}")
    print(f"PUBLIC SALARY: {summary.companies_with_public_salary}")
    print(f"COMPENSATION EVIDENCE: {summary.companies_with_compensation_evidence}")
    print(f"CAREER PAGE: {summary.companies_with_career_page}")
    print(f"SUPPORTED ATS: {summary.companies_with_supported_ats}")
    print("EVIDENCE BY SOURCE:")
    for provider, count in sorted(summary.evidence_by_provider.items()):
        print(f"  {provider}: {count}")


def _print_unknown_company(company_name: str) -> None:
    print(f"Company: {company_name}")
    print("Evidence: none in the imported sources")
    print("Career page: UNKNOWN")
    print("Remote from Spain: UNKNOWN")
    print("Public salary: UNKNOWN")
    print("High compensation evidence: UNKNOWN")
    print("Company type: UNKNOWN")


def _print_facts(facts: CompanyFacts) -> None:
    print(f"Company: {facts.company_name}")
    print(f"Normalized identity: {facts.normalized_identity}")
    print(f"Website domain: {facts.website_domain or 'UNKNOWN'}")
    print(f"Remote from Spain: {facts.remote_from_spain.value}")
    print(f"Public salary: {facts.public_salary.value}")
    print(f"High compensation evidence: {facts.high_compensation.value}")
    print(f"Company type: {facts.company_type or 'UNKNOWN'}")
    print(f"Source count: {facts.source_count}")
    print(f"Evidence freshness: {facts.evidence_freshness.isoformat() if facts.evidence_freshness else 'UNKNOWN'}")
    print("Career pages:")
    if not facts.career_pages:
        print("  - UNKNOWN")
    for page in facts.career_pages:
        print(
            f"  - {page.url} | ATS: {page.ats_provider.value} | identifier: {page.ats_identifier or 'UNKNOWN'} "
            f"| supported: {'YES' if page.is_supported else 'NO'}"
        )
    print("Compensation evidence:")
    if not facts.compensation_evidence:
        print("  - UNKNOWN")
    for item in facts.compensation_evidence:
        compensation = item.structured_data.get("compensation", {})
        print(f"  - source: {item.source_url or 'UNKNOWN'}")
        print(f"    metric: {compensation.get('metric', 'UNKNOWN')}")
        print(f"    base: {_annual_eur(compensation.get('base_annual_eur'))}")
        print(f"    total compensation: {_annual_eur(compensation.get('total_compensation_annual_eur'))}")
        print(f"    sample size: {compensation.get('sample_size') or 'UNKNOWN'}")
        print(f"    population: {compensation.get('population') or 'UNKNOWN'}")
        print(f"    observation period: {compensation.get('observation_period') or 'UNKNOWN'}")
        for url in compensation.get("source_evidence_urls", []):
            print(f"    evidence URL: {url}")
    print("Other evidence:")
    for item in facts.evidence:
        if item.evidence_type.value == "compensation":
            continue
        print(f"  - {item.evidence_type.value} via {item.provider}: {item.source_url or 'UNKNOWN'}")
        context = item.structured_data.get("public_salary_context")
        if context:
            print(f"    {context}")
    if not facts.evidence:
        print("  - none")


def _annual_eur(value) -> str:
    if value is None:
        return "UNKNOWN"
    return f"€{value:,.0f} gross/year"


def _run_monitor(args, session) -> None:
    observation = sync_ats_evidence_from_job_sources(session)
    # The source query above opens SQLAlchemy's implicit outer transaction;
    # sync_ats_evidence_from_job_sources commits a nested savepoint in that case.
    # Persist the observations so a later `ai-job-hunter refresh` can see targets.
    session.commit()
    filters = CompanyMonitorFilters(
        supported_ats=True,
        public_salary=args.public_salary,
        compensation_evidence=args.compensation_evidence,
        multiple_evidence_sources=args.multiple_evidence_sources,
        spanish_top_tech=args.spanish_top_tech,
        remote_from_spain=args.remote_from_spain,
    )
    provider = ATSProvider(args.provider.upper()) if args.provider else None
    targets = build_company_monitor_targets(
        session,
        filters,
        company_name=args.company,
        provider=provider,
        limit_companies=args.limit_companies,
    )
    print("ATS MONITOR TARGETS")
    print(f"OBSERVED JOB SOURCES: {observation.sources_examined}")
    print(f"ATS EVIDENCE CREATED: {observation.evidence_created}")
    print(f"ATS EVIDENCE UPDATED: {observation.evidence_updated}")
    print(f"TARGETS: {len(targets)}")
    if not targets:
        print("No company matched the structured filters and supported ATS requirements.")
        _save_and_report_empty_snapshot(args.save_snapshot)
        return

    specs: list[JobSourceSpec] = []
    targets_by_source: dict[tuple[str, str, str | None], object] = {}
    for target in targets:
        source_key = (target.provider.value.casefold(), target.identifier.casefold(), target.region)
        if source_key in targets_by_source:
            continue
        targets_by_source[source_key] = target
        specs.append(
            JobSourceSpec(
                provider=target.provider.value.casefold(),
                identifier=target.identifier,
                company_name=target.company_name,
                region=target.region,
                max_jobs=args.max_jobs_per_company,
            )
        )

    offers: list[NormalizedJob] = []
    jobs_by_company: dict[str, list[NormalizedJob]] = {target.company_name: [] for target in targets}
    failures: list[tuple[str, str]] = []
    config = JobSourcesConfig(sources=specs)
    timeout = httpx.Timeout(20.0)
    with httpx.Client(
        timeout=timeout,
        headers={"Accept": "application/json", "User-Agent": "AI-Job-Hunter/0.1 (personal job discovery)"},
    ) as client:
        connectors = build_job_connectors(config, client=client)
        for spec, connector in zip(config.sources, connectors, strict=True):
            target = targets_by_source[(spec.provider, spec.identifier.casefold(), spec.region)]
            try:
                fetched = connector.fetch_jobs()
                offers.extend(fetched)
                jobs_by_company.setdefault(target.company_name, []).extend(fetched)
                print(
                    f"COMPANY: {target.company_name} | ATS: {spec.provider.upper()} | "
                    f"IDENTIFIER: {spec.identifier} | JOBS FETCHED: {len(fetched)} | "
                    f"EVIDENCE: {target.evidence_source}"
                )
            except (
                AshbyConnectorError,
                GreenhouseConnectorError,
                LeverConnectorError,
                SmartRecruitersConnectorError,
                TeamtailorConnectorError,
                WorkableConnectorError,
                PersonioConnectorError,
            ) as error:
                failures.append((target.company_name, str(error)))
                print(f"COMPANY: {target.company_name} | FETCH ERROR: {error}", file=sys.stderr)

    try:
        snapshot_path = save_job_snapshot(args.save_snapshot, offers)
    except JobSnapshotError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return
    print(f"TOTAL JOBS FETCHED: {len(offers)}")
    print(f"SNAPSHOT: {snapshot_path}")

    prefilter_by_job: dict[int, tuple[PreFilterDecision, JobFacts]] = {}
    if args.candidate is None:
        for target in targets:
            print(f"JEV ELIGIBLE AFTER PREFILTER: {target.company_name} | NOT RUN (no candidate config)")
    else:
        for offer in offers:
            facts = JobFacts.from_normalized_job(offer)
            result = evaluate_job(facts, args.candidate)
            prefilter_by_job[id(offer)] = (result.decision, facts)
        for target in targets:
            company_jobs = jobs_by_company.get(target.company_name, [])
            eligible = [
                job
                for job in company_jobs
                if prefilter_by_job.get(id(job), (PreFilterDecision.REJECT, None))[0]
                is not PreFilterDecision.REJECT
            ]
            print(f"JEV ELIGIBLE AFTER PREFILTER: {target.company_name} | {len(eligible)} / {len(company_jobs)}")
            examples = [job.title for job in eligible if _is_technical_example(job)]
            if examples:
                print(f"TECHNICAL EXAMPLES: {target.company_name} | " + " | ".join(examples[:3]))

    dedup = _deduplicate_in_memory(offers)
    print(
        "IN-MEMORY EXISTING PIPELINE: "
        f"CREATED {dedup.created} | ALREADY KNOWN {dedup.already_known} | "
        f"MATCHED EXISTING {dedup.matched_existing} | POSSIBLE MATCH {dedup.possible_match} | "
        f"FAILED {dedup.failed}"
    )
    print("DEDUP SCOPE: fetched sample only; no persistent job database writes")
    if failures:
        print(f"FAILED COMPANIES: {len(failures)}")


def _save_and_report_empty_snapshot(path: Path) -> None:
    try:
        print(f"SNAPSHOT: {save_job_snapshot(path, [])}")
    except JobSnapshotError as error:
        print(f"ERROR: {error}", file=sys.stderr)


def _deduplicate_in_memory(offers: list[NormalizedJob]) -> PipelineSummary:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    try:
        Base.metadata.create_all(engine)
        with create_session_factory(engine)() as session:
            return run_ingestion_pipeline(FakeJobConnector(offers), session)
    finally:
        engine.dispose()


_TECHNICAL_TITLE = re.compile(
    r"\b(?:backend|software|platform|data|cloud|devops|security|machine learning|"
    r"frontend|full[- ]?stack|engineer|developer|qa|test automation)\b",
    re.IGNORECASE,
)


def _is_technical_example(job: NormalizedJob) -> bool:
    facts = JobFacts.from_normalized_job(job)
    return bool(facts.technologies or facts.required_technologies or _TECHNICAL_TITLE.search(job.title))


if __name__ == "__main__":
    raise SystemExit(main())
