"""Unified local workflow for refreshing and reviewing opportunities."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from ai_job_hunter.candidates import (
    CandidateConfigError,
    load_candidate_config,
)
from ai_job_hunter.config import get_settings
from ai_job_hunter.db.session import create_database_engine, create_session_factory
from ai_job_hunter.decision_engine import FinalDecision
from ai_job_hunter.services.company_intelligence import CompanyMonitorFilters
from ai_job_hunter.models import (
    Application,
    ApplicationEvent,
    ApplicationStatus,
    HumanReviewStatus,
    Job,
)
from ai_job_hunter.services.opportunities import (
    Opportunity,
    OpportunityServiceError,
    RefreshSummary,
    get_opportunity,
    list_opportunities,
    refresh_opportunities,
    set_review_state,
    transition_application,
)


DEFAULT_CANDIDATE_CONFIG = Path("candidate.local.json")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Refresh monitored ATS jobs, review opportunities, and track applications."
    )
    parser.add_argument("--database-url", help="override DATABASE_URL for this invocation")
    subparsers = parser.add_subparsers(dest="command", required=True)

    refresh = subparsers.add_parser("refresh", help="fetch ATS jobs and refresh the opportunity feed")
    refresh.add_argument("--candidate-config", type=Path, default=DEFAULT_CANDIDATE_CONFIG)
    refresh.add_argument("--limit-companies", type=int, default=10)
    refresh.add_argument("--max-jobs-per-company", type=int, default=100)
    refresh.add_argument("--max-jev-jobs", type=int, default=20)
    refresh.add_argument("--no-jev", action="store_true", help="use cache, persist misses as PENDING")
    refresh.add_argument(
        "--retry-pending",
        action="store_true",
        help="retry work deferred by an earlier Jev budget",
    )
    refresh.add_argument("--dry-run", action="store_true", help="fetch and prefilter without database or Jev writes")
    refresh.add_argument("--public-salary", action="store_true")
    refresh.add_argument("--compensation-evidence", action="store_true")
    refresh.add_argument("--multiple-evidence-sources", action="store_true")
    refresh.add_argument("--remote-from-spain", action="store_true")

    opportunities = subparsers.add_parser("opportunities", help="list current APPLY and REVIEW opportunities")
    opportunities.add_argument("--candidate-config", type=Path, default=DEFAULT_CANDIDATE_CONFIG)
    opportunities.add_argument("--decision", choices=("apply", "review", "skip"))
    opportunities.add_argument("--status", choices=tuple(item.value.casefold() for item in HumanReviewStatus))
    opportunities.add_argument("--remote", action="store_true", help="only remote-policy postings")
    opportunities.add_argument("--company")
    opportunities.add_argument("--technology")
    opportunities.add_argument("--limit", type=int, default=20)
    opportunities.add_argument("--include-applied", action="store_true")

    show = subparsers.add_parser("show", help="show one job and its latest saved state")
    show.add_argument("job_id", type=UUID)
    show.add_argument("--candidate-config", type=Path, default=DEFAULT_CANDIDATE_CONFIG)

    for name, help_text, state in (
        ("seen", "mark an opportunity SEEN", HumanReviewStatus.SEEN),
        ("save", "save an opportunity for later", HumanReviewStatus.SAVED),
        ("dismiss", "mark an opportunity DISMISSED", HumanReviewStatus.DISMISSED),
    ):
        command = subparsers.add_parser(name, help=help_text)
        command.add_argument("job_id", type=UUID)
        command.set_defaults(review_state=state)

    apply = subparsers.add_parser("apply", help="record that you applied; no application is sent")
    apply.add_argument("job_id", type=UUID)
    apply.add_argument("--source", help="application channel, such as company site or referral")
    apply.add_argument("--url", help="application URL")
    apply.add_argument("--cv-version")
    apply.add_argument("--note")

    application = subparsers.add_parser("application", help="record an application status update")
    application.add_argument("job_id", type=UUID)
    application.add_argument("--status", required=True, choices=tuple(item.value.casefold() for item in ApplicationStatus))
    application.add_argument("--source")
    application.add_argument("--url")
    application.add_argument("--cv-version")
    application.add_argument("--note")

    # Allow the database override before or after the subcommand.
    for command_parser in subparsers.choices.values():
        command_parser.add_argument("--database-url", default=argparse.SUPPRESS)

    args = parser.parse_args(argv)
    if args.command == "refresh":
        if args.limit_companies < 1:
            parser.error("--limit-companies must be positive")
        if args.max_jobs_per_company < 1:
            parser.error("--max-jobs-per-company must be positive")
        if args.max_jev_jobs < 0:
            parser.error("--max-jev-jobs cannot be negative")
    if args.command == "opportunities" and args.limit < 1:
        parser.error("--limit must be positive")

    candidate = None
    if args.command in {"refresh", "opportunities", "show"}:
        try:
            candidate = load_candidate_config(args.candidate_config)
        except CandidateConfigError as error:
            parser.error(str(error))

    settings = get_settings()
    if args.database_url:
        settings = settings.model_copy(update={"database_url": args.database_url})
    engine = create_database_engine(settings)
    try:
        with create_session_factory(engine)() as session:
            if args.command == "refresh":
                summary = refresh_opportunities(
                    session,
                    candidate,
                    max_companies=args.limit_companies,
                    max_jobs_per_company=args.max_jobs_per_company,
                    max_jev_jobs=args.max_jev_jobs,
                    no_jev=args.no_jev,
                    retry_pending=args.retry_pending,
                    dry_run=args.dry_run,
                    # The monitor always requires supported ATS; these are
                    # additional company facts, never policy inputs.
                    candidate_filters=_monitor_filters(args),
                )
                _print_refresh_summary(summary)
                return 1 if summary.failures else 0
            if args.command == "opportunities":
                decision = FinalDecision(args.decision.upper()) if args.decision else None
                state = HumanReviewStatus(args.status.upper()) if args.status else None
                rows = list_opportunities(
                    session,
                    candidate,
                    decision=decision,
                    status=state,
                    remote_only=args.remote,
                    company=args.company,
                    technology=args.technology,
                    limit=args.limit,
                    include_applied=args.include_applied,
                )
                print(f"OPPORTUNITIES: {len(rows)}")
                for row in rows:
                    _print_opportunity(row, show_company_facts=True)
                return 0
            if args.command == "show":
                item = get_opportunity(session, args.job_id, candidate)
                if item is None:
                    print(f"Job not found: {args.job_id}", file=sys.stderr)
                    return 2
                _print_opportunity(item, show_company_facts=True)
                _print_application_history(session, args.job_id)
                return 0
            if args.command in {"seen", "save", "dismiss"}:
                review = set_review_state(session, args.job_id, args.review_state)
                print(f"Review state: {review.state}")
                return 0
            if args.command == "apply":
                status = ApplicationStatus.APPLIED
                application_record = transition_application(
                    session,
                    args.job_id,
                    status,
                    note=args.note,
                    source=args.source,
                    application_url=args.url,
                    cv_version=args.cv_version,
                )
                print(f"Application recorded: {application_record.status}")
                print("No application was sent.")
                return 0
            if args.command == "application":
                application_record = transition_application(
                    session,
                    args.job_id,
                    ApplicationStatus(args.status.upper()),
                    note=args.note,
                    source=args.source,
                    application_url=args.url,
                    cv_version=args.cv_version,
                )
                print(f"Application status: {application_record.status}")
                return 0
    except OpportunityServiceError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1
    except SQLAlchemyError as error:
        # Keep connection details and DATABASE_URL out of terminal output.
        print(f"DATABASE ERROR: {type(error).__name__}. Confirm the local database is running and run `alembic upgrade head`.", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    return 0


def _monitor_filters(args) -> CompanyMonitorFilters:
    return CompanyMonitorFilters(
        supported_ats=True,
        public_salary=args.public_salary,
        compensation_evidence=args.compensation_evidence,
        multiple_evidence_sources=args.multiple_evidence_sources,
        remote_from_spain=args.remote_from_spain,
    )


def _print_refresh_summary(summary: RefreshSummary) -> None:
    mode = "DRY RUN" if summary.dry_run else "REFRESH"
    print(mode)
    for label, value in (
        ("Companies checked", summary.companies_checked),
        ("Jobs fetched", summary.jobs_fetched),
        ("New jobs", summary.new_jobs),
        ("Known jobs", summary.known_jobs),
        ("Changed jobs", summary.changed_jobs),
        ("Hard skips", summary.hard_skips),
        ("Jev calls attempted", summary.jev_calls),
        ("Jev evaluated", summary.jev_evaluated),
        ("Jev cache hits", summary.jev_cache_hits),
        ("Pending", summary.pending),
        ("Pending: Jev budget", summary.pending_budget),
        ("Pending: Jev disabled", summary.pending_no_jev),
        ("Pending: errors", summary.pending_errors),
        ("APPLY", summary.apply),
        ("REVIEW", summary.review),
        ("SKIP", summary.skip),
    ):
        print(f"{label}: {value}")
    for failure in summary.failures:
        print(f"Fetch/ingest failure: {failure.company} | {failure.provider} | {failure.error_type}")


def _print_opportunity(item: Opportunity, *, show_company_facts: bool = False) -> None:
    if item.evaluation_is_stale:
        decision = "STALE"
    elif item.decision is not None:
        decision = item.decision.value
    elif item.evaluation_status is not None:
        decision = item.evaluation_status.value
    else:
        decision = "UNEVALUATED"
    print(f"[{decision}] {item.title} — {item.company}")
    print(f"Job ID: {item.job_id}")
    print(f"Location: {item.location or 'UNKNOWN'} | Work mode: {item.remote_policy or 'UNKNOWN'}")
    print(f"Human status: {item.review_state.value}")
    if item.application_status is not None:
        print(f"Application: {item.application_status.value}")
    if item.priority is not None:
        print(f"Priority: {item.priority}/100 (deterministic ranking, not a hiring probability)")
    else:
        print("Priority: UNKNOWN")
    if item.technologies:
        print(f"Stack: {', '.join(item.technologies)}")
    if item.required_technologies:
        print(f"Required stack: {', '.join(item.required_technologies)}")
    salary = "UNKNOWN"
    if item.salary_min is not None or item.salary_max is not None:
        salary = f"{item.salary_min or '?'}–{item.salary_max or '?'} {item.currency or ''} / {item.salary_period or 'period unknown'}".strip()
    print(f"Salary: {salary}")
    if item.deterministic_result and not item.evaluation_is_stale:
        print(f"Prefilter: {item.deterministic_result.get('decision', 'UNKNOWN')}")
        _print_prefilter_signals(item.deterministic_result)
        for reason in item.deterministic_result.get("reasons", []):
            print(f"  - {reason}")
    if item.jev_signals and not item.evaluation_is_stale:
        values = [
            f"{name}={data.get('value')}" for name, data in item.jev_signals.items()
            if isinstance(data, dict) and data.get("value") is not None
        ]
        if values:
            print("Jev: " + ", ".join(values))
    if item.jev_reasons and not item.evaluation_is_stale:
        reason_values = item.jev_reasons.get("reasons", []) if isinstance(item.jev_reasons, dict) else item.jev_reasons
        for reason in reason_values:
            print(f"  - {reason}")
    if show_company_facts and item.company_facts is not None:
        facts = item.company_facts
        ats = ", ".join(sorted({entry.provider.value for entry in facts.ats_discoveries if entry.is_supported})) or "UNKNOWN"
        evidence_providers = ", ".join(sorted({entry.provider for entry in facts.evidence})) or "UNKNOWN"
        print(
            "Company context: "
            f"public salary={facts.public_salary.value}; "
            f"high compensation={facts.high_compensation.value}; supported ATS={ats}; "
            f"evidence sources={facts.source_count} ({evidence_providers}); "
            f"freshness={facts.evidence_freshness or 'UNKNOWN'}"
        )
        if facts.compensation_evidence:
            print(f"Company compensation evidence records: {len(facts.compensation_evidence)}")
    if item.url:
        print(f"URL: {item.url}")
    print()


def _print_prefilter_signals(result: dict) -> None:
    signals = result.get("signals")
    if not isinstance(signals, dict):
        return
    assessments = []
    for name in (
        "geography",
        "salary",
        "seniority",
        "employment_type",
        "remote_preference",
        "preferred_role",
        "preferred_location",
    ):
        item = signals.get(name)
        if isinstance(item, dict):
            value = item.get("status") or item.get("evaluation")
            if value is not None:
                assessments.append(f"{name}={value}")
    if assessments:
        print("Prefilter signals: " + ", ".join(assessments))
    technology = signals.get("technology")
    if isinstance(technology, dict):
        groups = (
            ("matched primary", "matching_primary_skills"),
            ("matched secondary", "matching_secondary_skills"),
            ("matched technologies", "matching_candidate_technologies"),
            ("preferred technologies", "matching_preferred_technologies"),
            ("missing", "missing_technologies"),
            ("learnable", "learnable_technologies"),
            ("transferable", "transferable_technologies"),
            ("critical mismatches", "critical_mismatches"),
        )
        technology_summary = [
            f"{label}: {', '.join(str(value) for value in technology[key])}"
            for label, key in groups
            if isinstance(technology.get(key), list) and technology[key]
        ]
        if technology_summary:
            print("Prefilter technology: " + "; ".join(technology_summary))


def _print_application_history(session, job_id: UUID) -> None:
    application = session.scalar(select(Application).where(Application.job_id == job_id))
    if application is None:
        print("Application: not tracked")
        return
    print(f"Application: {application.status}; applied_at={application.applied_at or 'UNKNOWN'}")
    if application.source:
        print(f"Channel: {application.source}")
    if application.application_url:
        print(f"Application URL: {application.application_url}")
    if application.cv_version:
        print(f"CV version: {application.cv_version}")
    if application.notes:
        print(f"Notes: {application.notes}")
    events = session.scalars(
        select(ApplicationEvent)
        .where(ApplicationEvent.application_id == application.id)
        .order_by(ApplicationEvent.occurred_at, ApplicationEvent.id)
    ).all()
    print("Application history:")
    for event in events:
        before = event.from_status or "START"
        print(f"  {event.occurred_at.isoformat()} {before} → {event.to_status}")
        if event.note:
            print(f"    {event.note}")


if __name__ == "__main__":
    raise SystemExit(main())
