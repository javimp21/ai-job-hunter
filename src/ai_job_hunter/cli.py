"""Unified local workflow for refreshing and reviewing opportunities."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import selectinload

from ai_job_hunter.candidates import (
    CandidateConfigError,
    load_candidate_config,
)
from ai_job_hunter.config import get_settings
from ai_job_hunter.db.session import create_database_engine, create_session_factory
from ai_job_hunter.decision_engine import FinalDecision
from ai_job_hunter.application_prep.configuration import (
    ApplicationPreparationConfigError,
    DEFAULT_APPLICATION_FACTS_PATH,
    load_candidate_application_facts,
    load_candidate_documents,
    load_candidate_writing_style,
)
from ai_job_hunter.application_prep.extraction import extract_application_questions
from ai_job_hunter.application_prep.models import (
    QuestionSchemaStatus,
)
from ai_job_hunter.application_prep.service import (
    ApplicationJobInput,
    ApplicationPreparationError,
    answer_application_question,
    build_application_package,
    cancel_application_package,
    mark_ready_to_submit,
)
from ai_job_hunter.application_prep.store import (
    ApplicationPackageStore,
    ApplicationPackageStoreError,
)
from ai_job_hunter.services.company_intelligence import CompanyMonitorFilters
from ai_job_hunter.models import (
    Application,
    ApplicationEvent,
    ApplicationStatus,
    HumanReviewStatus,
    Job,
)
from ai_job_hunter.models.company import Company
from ai_job_hunter.models.outreach import Outreach, OutreachStatus
from ai_job_hunter.contact_discovery import (
    ContactCandidate,
    ContactLookupStrategy,
    ManualContactProvider,
)
from ai_job_hunter.outreach import (
    DraftChannel,
    OutreachRecommendation,
)
from ai_job_hunter.outreach.projects import CandidateProjectsConfigError
from ai_job_hunter.outreach.projects import load_candidate_projects
from ai_job_hunter.services.cover_letters import CoverLetterError, generate_cover_letter
from ai_job_hunter.services.opportunities import (
    Opportunity,
    OpportunityServiceError,
    ReevaluationSummary,
    RefreshSummary,
    get_opportunity,
    list_opportunities,
    reevaluate_jobs,
    refresh_opportunities,
    set_review_state,
    transition_application,
)
from ai_job_hunter.services.notifications import (
    NotificationBatchResult,
    NotificationPreview,
    TelegramProvider,
    list_notification_history,
    list_pending_notifications,
    preview_notifications,
    retry_failed_notifications,
    send_notifications,
)
from ai_job_hunter.services.outreach_persistence import (
    OutreachPersistenceError,
    get_outreach_history,
    list_contacts_for_company,
    transition_outreach,
)
from ai_job_hunter.services.outreach_workflow import (
    create_initial_outreach_drafts,
    plan_outreach_for_job,
)


DEFAULT_CANDIDATE_CONFIG = Path("candidate.local.json")
DEFAULT_CANDIDATE_PROJECTS_CONFIG = Path("candidate_projects.local.json")


def _add_notification_and_run_parsers(subparsers) -> None:
    """Declare the bounded notification and scheduled-run CLI surface."""

    notify = subparsers.add_parser(
        "notify",
        help="inspect or deliver policy-eligible opportunity notifications",
        description="Telegram delivery is explicit; `send --dry-run` never contacts Telegram.",
    )
    notification_commands = notify.add_subparsers(dest="notification_command", required=True)
    pending = notification_commands.add_parser("pending", help="list queued notifications")
    pending.add_argument("--limit", type=int, default=20)

    send = notification_commands.add_parser("send", help="queue eligible opportunities and deliver notifications")
    send.add_argument("--limit", type=int, default=20)
    send.add_argument(
        "--dry-run",
        action="store_true",
        help="show policy-eligible opportunities without saving notifications or contacting Telegram",
    )

    history = notification_commands.add_parser("history", help="show recent notification delivery history")
    history.add_argument("--limit", type=int, default=20)

    retry = notification_commands.add_parser(
        "retry-failed", help="retry notifications whose delivery is safe to retry"
    )
    retry.add_argument("--limit", type=int, default=20)
    for command_parser in notification_commands.choices.values():
        command_parser.add_argument("--candidate-config", type=Path, default=DEFAULT_CANDIDATE_CONFIG)
        command_parser.add_argument("--database-url", default=argparse.SUPPRESS)

    run = subparsers.add_parser(
        "run",
        help="run the existing monitored-source refresh, then optionally notify",
        description=(
            "Refresh already monitored supported ATS sources using the normal opportunity pipeline, "
            "then optionally deliver eligible notifications. It does not resolve Company Leads."
        ),
    )
    run.add_argument("--candidate-config", type=Path, default=DEFAULT_CANDIDATE_CONFIG)
    run.add_argument("--limit-companies", type=int, default=10)
    run.add_argument("--max-jobs-per-company", type=int, default=100)
    run.add_argument("--max-jev-jobs", type=int, default=20)
    run.add_argument("--max-notifications", type=int, default=20)
    run.add_argument("--no-notifications", action="store_true", help="refresh opportunities without Telegram delivery")
    run.add_argument("--no-jev", action="store_true", help="use cached evaluations and leave misses pending")
    run.add_argument("--retry-pending", action="store_true", help="retry work deferred by an earlier Jev budget")
    run.add_argument(
        "--dry-run",
        action="store_true",
        help="fetch and prefilter only; do not persist refresh/evaluation/notification changes or send messages",
    )
    run.add_argument("--public-salary", action="store_true")
    run.add_argument("--compensation-evidence", action="store_true")
    run.add_argument("--multiple-evidence-sources", action="store_true")
    run.add_argument("--remote-from-spain", action="store_true")


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

    reevaluate = subparsers.add_parser(
        "reevaluate",
        help="re-evaluate selected stored jobs without fetching ATS boards",
        description=(
            "Evaluate only the given persisted jobs. Current evaluations are reused, deterministic "
            "SKIPs never call Jev, and --dry-run writes nothing and calls nothing."
        ),
    )
    reevaluate.add_argument("--job-id", type=UUID, action="append", required=True, dest="job_ids")
    reevaluate.add_argument(
        "--max-jev-jobs",
        type=int,
        required=True,
        help="maximum new Jev calls attempted in this run (required)",
    )
    reevaluate.add_argument("--dry-run", action="store_true", help="show the plan without database, cache or Jev writes")
    reevaluate.add_argument("--candidate-config", type=Path, default=DEFAULT_CANDIDATE_CONFIG)

    cover_letter = subparsers.add_parser(
        "cover-letter",
        help="draft a cover letter for one stored job with Claude (saved locally; never sent)",
    )
    cover_letter.add_argument("job_id", type=UUID)
    cover_letter.add_argument("--candidate-config", type=Path, default=DEFAULT_CANDIDATE_CONFIG)

    _add_notification_and_run_parsers(subparsers)

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

    apply = subparsers.add_parser(
        "apply",
        help="prepare a local application package; legacy `apply JOB_ID` still records application status",
        description=(
            "Prepare and inspect application materials in assisted browser mode. "
            "This command has no application submission or document-upload operation. "
            "For application tracking, the legacy `apply JOB_ID` form remains available."
        ),
        epilog=(
            "Commands: prepare, show, questions, answer, ready, cancel, browser, inspect, fill-safe, pending, review.\n"
            "Examples: apply browser JOB_ID; apply fill-safe JOB_ID; apply review JOB_ID"
        ),
    )
    apply.add_argument("apply_args", nargs=argparse.REMAINDER)

    application = subparsers.add_parser("application", help="record an application status update")
    application.add_argument("job_id", type=UUID)
    application.add_argument("--status", required=True, choices=tuple(item.value.casefold() for item in ApplicationStatus))
    application.add_argument("--source")
    application.add_argument("--url")
    application.add_argument("--cv-version")
    application.add_argument("--note")

    outreach = subparsers.add_parser("outreach", help="prepare and track local outreach drafts; no sending")
    outreach_commands = outreach.add_subparsers(dest="outreach_command", required=True)

    outreach_candidates = outreach_commands.add_parser(
        "candidates", help="list opportunities eligible for initial outreach"
    )
    outreach_candidates.add_argument("--candidate-config", type=Path, default=DEFAULT_CANDIDATE_CONFIG)
    outreach_candidates.add_argument("--limit", type=int, default=20)

    outreach_strategy = outreach_commands.add_parser(
        "strategy", help="show the outreach recommendation and contextual contact roles"
    )
    outreach_strategy.add_argument("job_id", type=UUID)
    outreach_strategy.add_argument("--candidate-config", type=Path, default=DEFAULT_CANDIDATE_CONFIG)

    outreach_contacts = outreach_commands.add_parser(
        "contacts", help="list locally saved contacts for a job's company; no external lookup"
    )
    outreach_contacts.add_argument("job_id", type=UUID)

    outreach_draft = outreach_commands.add_parser("draft", help="create local DRAFT records only")
    outreach_draft.add_argument("job_id", type=UUID)
    outreach_draft.add_argument("--candidate-config", type=Path, default=DEFAULT_CANDIDATE_CONFIG)
    outreach_draft.add_argument("--projects-config", type=Path, default=DEFAULT_CANDIDATE_PROJECTS_CONFIG)
    outreach_draft.add_argument(
        "--channel", choices=tuple(item.value.casefold() for item in DraftChannel), default="linkedin"
    )

    outreach_show = outreach_commands.add_parser("show", help="show one saved outreach and its history")
    outreach_show.add_argument("outreach_id", type=UUID)

    outreach_approve = outreach_commands.add_parser(
        "approve", help="record human approval of a DRAFT; does not send it"
    )
    outreach_approve.add_argument("outreach_id", type=UUID)
    outreach_approve.add_argument("--note")

    for command_parser in outreach_commands.choices.values():
        command_parser.add_argument("--database-url", default=argparse.SUPPRESS)

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
    if args.command == "run":
        if args.limit_companies < 1:
            parser.error("--limit-companies must be positive")
        if args.max_jobs_per_company < 1:
            parser.error("--max-jobs-per-company must be positive")
        if args.max_jev_jobs < 0:
            parser.error("--max-jev-jobs cannot be negative")
        if args.max_notifications < 1:
            parser.error("--max-notifications must be positive")
    if args.command == "reevaluate" and args.max_jev_jobs < 0:
        parser.error("--max-jev-jobs cannot be negative")
    if args.command == "opportunities" and args.limit < 1:
        parser.error("--limit must be positive")
    if args.command == "notify" and args.limit < 1:
        parser.error("--limit must be positive")
    if (
        args.command == "outreach"
        and args.outreach_command == "candidates"
        and args.limit < 1
    ):
        parser.error("--limit must be positive")

    if args.command == "apply":
        try:
            apply_args = _parse_apply_command(args.apply_args)
        except SystemExit:
            raise
        args.apply_command = apply_args
        nested_database_url = getattr(apply_args, "database_url", None)
        if nested_database_url:
            args.database_url = nested_database_url
        if apply_args.action not in {"prepare", "record"}:
            return _run_local_apply_command(apply_args)

    candidate = None
    if args.command in {"refresh", "reevaluate", "cover-letter", "opportunities", "show", "run"} or (
        args.command == "notify"
        and args.notification_command in {"send", "retry-failed"}
    ) or (
        args.command == "outreach"
        and args.outreach_command in {"candidates", "strategy", "draft"}
    ) or (args.command == "apply" and args.apply_command.action == "prepare"):
        try:
            candidate_path = (
                args.apply_command.candidate_config
                if args.command == "apply"
                else args.candidate_config
            )
            candidate = load_candidate_config(candidate_path)
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
            if args.command == "cover-letter":
                try:
                    draft = generate_cover_letter(
                        session,
                        candidate,
                        args.job_id,
                        application_facts=load_candidate_application_facts(DEFAULT_APPLICATION_FACTS_PATH),
                        documents=tuple(load_candidate_documents(Path("candidate_documents.local.json")).documents),
                    )
                except CoverLetterError as error:
                    print(f"ERROR: {error}", file=sys.stderr)
                    return 1
                print(f"COVER LETTER DRAFT — {draft.company} — {draft.title}")
                print(f"Saved: {draft.path}")
                print(f"Model: {draft.model} | tokens in/out: {draft.input_tokens}/{draft.output_tokens}")
                print()
                print(draft.text)
                return 0
            if args.command == "reevaluate":
                summary = reevaluate_jobs(
                    session,
                    candidate,
                    args.job_ids,
                    max_jev_jobs=args.max_jev_jobs,
                    dry_run=args.dry_run,
                )
                _print_reevaluation_summary(summary)
                return 1 if summary.pending_errors else 0
            if args.command == "notify":
                return _run_notification_command(args, session, candidate, settings)
            if args.command == "run":
                summary = refresh_opportunities(
                    session,
                    candidate,
                    max_companies=args.limit_companies,
                    max_jobs_per_company=args.max_jobs_per_company,
                    max_jev_jobs=args.max_jev_jobs,
                    no_jev=args.no_jev,
                    retry_pending=args.retry_pending,
                    dry_run=args.dry_run,
                    candidate_filters=_monitor_filters(args),
                )
                _print_refresh_summary(summary)
                if args.no_notifications:
                    print("Notifications: disabled")
                    return 1 if summary.failures else 0
                if args.dry_run:
                    print("Notification preview uses the currently stored feed; dry-run refresh did not persist fetched offers.")
                    previews = preview_notifications(
                        session,
                        candidate,
                        review_threshold=settings.notify_review_min_priority,
                        limit=args.max_notifications,
                    )
                    _print_notification_previews(previews)
                    return 1 if summary.failures else 0
                provider = _configured_telegram_provider(settings)
                if provider is None:
                    print(
                        "Notifications skipped: configure TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in the local environment.",
                        file=sys.stderr,
                    )
                    return 1
                result = send_notifications(
                    session,
                    candidate,
                    provider,
                    review_threshold=settings.notify_review_min_priority,
                    limit=args.max_notifications,
                )
                _print_notification_batch(result)
                return 1 if summary.failures or result.failed else 0
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
            if args.command == "outreach":
                return _run_outreach_command(args, session, candidate)
            if args.command in {"seen", "save", "dismiss"}:
                review = set_review_state(session, args.job_id, args.review_state)
                print(f"Review state: {review.state}")
                return 0
            if args.command == "apply" and args.apply_command.action == "record":
                apply_args = args.apply_command
                status = ApplicationStatus.APPLIED
                application_record = transition_application(
                    session,
                    apply_args.job_id,
                    status,
                    note=apply_args.note,
                    source=apply_args.source,
                    application_url=apply_args.url,
                    cv_version=apply_args.cv_version,
                )
                print(f"Application recorded: {application_record.status}")
                print("No application was sent.")
                return 0
            if args.command == "apply" and args.apply_command.action == "prepare":
                return _prepare_application_from_database(args.apply_command, session, candidate)
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
    except (OutreachPersistenceError, CandidateProjectsConfigError) as error:
        print(f"OUTREACH ERROR: {error}", file=sys.stderr)
        return 1
    except (
        ApplicationPreparationError,
        ApplicationPreparationConfigError,
        ApplicationPackageStoreError,
    ) as error:
        print(f"APPLICATION PREPARATION ERROR: {error}", file=sys.stderr)
        return 1
    except SQLAlchemyError as error:
        # Keep connection details and DATABASE_URL out of terminal output.
        print(f"DATABASE ERROR: {type(error).__name__}. Confirm the local database is running and run `alembic upgrade head`.", file=sys.stderr)
        return 1
    finally:
        engine.dispose()
    return 0


def _parse_apply_command(values: Sequence[str]):
    """Parse nested preparation commands while preserving legacy `apply UUID`."""

    if not values:
        return argparse.Namespace(action="help")
    first = values[0]
    if first not in {"prepare", "show", "questions", "answer", "ready", "cancel", "record", "inspect", "browser", "fill-safe", "pending", "review", "-h", "--help"}:
        try:
            UUID(first)
        except ValueError:
            pass
        else:
            first = "record"
            values = (first, *values)

    nested = argparse.ArgumentParser(prog="ai-job-hunter apply")
    commands = nested.add_subparsers(dest="action", required=True)
    record = commands.add_parser("record", help="record a manually submitted application (legacy behavior)")
    record.add_argument("job_id", type=UUID)
    record.add_argument("--source", help="application channel, such as company site or referral")
    record.add_argument("--url", help="application URL")
    record.add_argument("--cv-version")
    record.add_argument("--note")
    record.add_argument("--database-url", default=argparse.SUPPRESS)

    prepare = commands.add_parser("prepare", help="prepare a local package for an existing APPLY opportunity")
    prepare.add_argument("job_id", type=UUID)
    prepare.add_argument("--candidate-config", type=Path, default=DEFAULT_CANDIDATE_CONFIG)
    prepare.add_argument("--projects-config", type=Path, default=DEFAULT_CANDIDATE_PROJECTS_CONFIG)
    prepare.add_argument("--documents-config", type=Path, default=Path("candidate_documents.local.json"))
    prepare.add_argument("--writing-style-config", type=Path, default=Path("candidate_writing.local.json"))
    prepare.add_argument("--packages-path", type=Path)
    prepare.add_argument("--cover-letter", action="store_true", help="draft a cover letter for human review")
    prepare.add_argument("--database-url", default=argparse.SUPPRESS)

    for name, help_text in (
        ("show", "show one saved local application package"),
        ("questions", "list detected questions and answer status"),
        ("ready", "record explicit human review when all readiness checks pass"),
        ("cancel", "cancel a saved local package"),
        ("inspect", "show the last redacted browser form snapshot"),
        ("pending", "list browser form fields waiting for review or input"),
        ("review", "review the last inspected browser form and drafts"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("job_id", type=UUID)
        command.add_argument("--packages-path", type=Path)
        if name in {"inspect", "pending", "review"}:
            command.add_argument("--sessions-path", type=Path)
    for name, help_text in (
        ("browser", "open and inspect the hosted form in an isolated browser"),
        ("fill-safe", "inspect the form and fill only explicit factual fields"),
    ):
        command = commands.add_parser(name, help=help_text)
        command.add_argument("job_id", type=UUID)
        command.add_argument("--packages-path", type=Path)
        command.add_argument("--sessions-path", type=Path)
        command.add_argument("--candidate-config", type=Path, default=DEFAULT_CANDIDATE_CONFIG)
        command.add_argument("--facts-config", type=Path, default=DEFAULT_APPLICATION_FACTS_PATH)
        command.add_argument("--projects-config", type=Path, default=DEFAULT_CANDIDATE_PROJECTS_CONFIG)
        command.add_argument("--documents-config", type=Path, default=Path("candidate_documents.local.json"))
        if name == "fill-safe":
            command.add_argument("--dry-run", action="store_true", help="plan safe fills without changing any form fields or advancing")
    answer = commands.add_parser("answer", help="save a human-entered answer locally")
    answer.add_argument("job_id", type=UUID)
    answer.add_argument("question_id")
    answer.add_argument("--value", help="answer text; omit to enter interactively")
    answer.add_argument("--confirm-sensitive", action="store_true")
    answer.add_argument("--packages-path", type=Path)
    ready = commands.choices["ready"]
    ready.add_argument("--confirm-reviewed", action="store_true", help="confirm you reviewed the package")
    return nested.parse_args(values)


def _run_local_apply_command(args) -> int:
    if args.action == "help":
        print("Use `ai-job-hunter apply prepare JOB_ID` to create a local package.")
        print("Commands: prepare, show, questions, answer, ready, cancel, browser, inspect, fill-safe, pending, review.")
        print("Browser mode has no application submission or document-upload operation.")
        return 0
    if args.action in {"inspect", "pending", "review"}:
        return _run_browser_session_report(args)
    if args.action in {"browser", "fill-safe"}:
        return _run_browser_apply_command(args)
    store = ApplicationPackageStore(args.packages_path)
    package = store.get_by_job(args.job_id)
    if package is None:
        print(f"No local application package found for job {args.job_id}.", file=sys.stderr)
        return 2
    if args.action == "show":
        _print_application_package(package)
        return 0
    if args.action == "questions":
        print(f"QUESTIONS: {len(package.questions)}")
        for item in package.questions:
            required = "required" if item.required else "optional"
            print(
                f"{item.id} | {item.normalized_type.value} | {required} | "
                f"{item.handling.value} | {item.answer_status.value} | {item.label}"
            )
            if item.answer is not None:
                print(f"  draft answer: {item.answer}")
        return 0
    if args.action == "answer":
        question = next((item for item in package.questions if item.id == args.question_id), None)
        if question is None:
            print("Application question was not found.", file=sys.stderr)
            return 2
        value = args.value if args.value is not None else input("Enter your answer: ")
        package = answer_application_question(
            package,
            args.question_id,
            value,
            confirm_sensitive=args.confirm_sensitive,
        )
        store.save(package)
        print(f"Answer saved locally; status={package.readiness.status.value}. No data was sent.")
        return 0
    if args.action == "ready":
        if not args.confirm_reviewed:
            print("Pass --confirm-reviewed after reviewing the package.", file=sys.stderr)
            return 2
        package = mark_ready_to_submit(package)
        store.save(package)
        print("Package marked READY_TO_SUBMIT after human review. Nothing was submitted.")
        return 0
    if args.action == "cancel":
        package = cancel_application_package(package)
        store.save(package)
        print("Local application package cancelled.")
        return 0
    return 2


def _safe_terminal_text(value: str) -> str:
    """Render arbitrary ATS labels on legacy Windows console encodings safely."""

    encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
    normalized = str(value).replace("\ufffd", "'").replace("’", "'").replace("‘", "'")
    return normalized.encode(encoding, errors="replace").decode(encoding, errors="replace")


def _run_browser_apply_command(args) -> int:
    from ai_job_hunter.application_prep.browser.service import inspect_application_package
    from ai_job_hunter.application_prep.browser.safety import BrowserSafetyError
    from ai_job_hunter.application_prep.browser.store import (
        ApplicationSessionStore,
        ApplicationSessionStoreError,
    )

    package_store = ApplicationPackageStore(args.packages_path)
    package = package_store.get_by_job(args.job_id)
    if package is None:
        print(f"No local application package found for job {args.job_id}.", file=sys.stderr)
        return 2
    try:
        candidate = load_candidate_config(args.candidate_config)
        facts = load_candidate_application_facts(args.facts_config)
        projects = tuple(load_candidate_projects(args.projects_config))
        documents = tuple(load_candidate_documents(args.documents_config).documents)
        session = inspect_application_package(
            package,
            candidate=candidate,
            facts=facts,
            projects=projects,
            documents=documents,
            fill_safe=args.action == "fill-safe",
            dry_run=bool(getattr(args, "dry_run", False)),
        )
        ApplicationSessionStore(args.sessions_path).save(session)
    except (
        ApplicationPreparationConfigError,
        CandidateConfigError,
        CandidateProjectsConfigError,
        ApplicationPackageStoreError,
        ApplicationSessionStoreError,
        BrowserSafetyError,
    ) as error:
        print(f"BROWSER APPLY STOPPED: {error}", file=sys.stderr)
        return 1
    print(f"Session: {session.id}")
    print(f"ATS: {session.ats.value}")
    print(f"Redirects observed: {len(session.redirects_observed)}")
    for redirect_url in session.redirects_observed:
        print(f"  {redirect_url}")
    print(f"Steps inspected: {len(session.snapshots)}")
    print(f"Fields extracted: {sum(len(item.fields) for item in session.snapshots)}")
    print(f"Safe fields filled: {len(session.filled_safe_field_ids)}")
    if session.dry_run:
        print("DRY RUN: no fields were filled and no form buttons were clicked.")
        for label, field_ids in (
            ("WOULD_FILL", session.would_fill_field_ids),
            ("WOULD_SKIP", session.would_skip_field_ids),
            ("NEEDS_INPUT", session.needs_input_field_ids),
        ):
            print(f"{label}: {len(field_ids)}")
            for field_id in field_ids:
                form_field = next((field for snap in session.snapshots for field in snap.fields if field.id == field_id), None)
                if form_field is not None:
                    print(f"  {field_id} | {_safe_terminal_text(form_field.label)}")
    print(f"Fields pending review/input: {len(session.pending_field_ids)}")
    if session.snapshot and session.snapshot.manual_intervention_required:
        print(f"Manual intervention: {session.snapshot.manual_intervention_reason.value}")
    print(f"Session status: {session.status.value}")
    print(f"Required fields: {len(session.required_field_ids)}")
    print(f"Legal review fields: {len(session.legal_field_ids)}")
    print(f"Sensitive review fields: {len(session.sensitive_field_ids)}")
    print(f"Required document fields: {len(session.required_document_field_ids)}")
    for mapping in session.mappings:
        if mapping.canonical_field.value == "CV" and (mapping.recommendation or "").startswith("NO_CV_CONFIGURED"):
            print("DOCUMENT: NO_CV_CONFIGURED; add local metadata in candidate_documents.local.json. No upload was performed.")
    for reason in session.readiness_reasons:
        print(f"Readiness: {reason}")
    print("No application was submitted and no document was uploaded.")
    return 0


def _run_browser_session_report(args) -> int:
    from ai_job_hunter.application_prep.browser.models import AnswerPolicy
    from ai_job_hunter.application_prep.browser.store import (
        ApplicationSessionStore,
        ApplicationSessionStoreError,
    )

    try:
        session = ApplicationSessionStore(args.sessions_path).get_by_job(args.job_id)
    except ApplicationSessionStoreError as error:
        print(f"BROWSER SESSION ERROR: {error}", file=sys.stderr)
        return 1
    if session is None:
        print("No saved browser session for this job; run `apply browser JOB_ID` first.", file=sys.stderr)
        return 2
    mappings = {item.field_id: item for item in session.mappings}
    if args.action == "pending":
        pending = [mappings[item] for item in session.pending_field_ids if item in mappings]
        print(f"PENDING FORM FIELDS: {len(pending)}")
        for item in pending:
            print(f"{item.answer_policy.value} | {_safe_terminal_text(item.source_label)}")
        return 0
    if args.action == "inspect":
        print(f"ATS: {session.ats.value} | status={session.status.value} | steps={len(session.snapshots)}")
        print(f"Readiness reasons: {len(session.readiness_reasons)}")
        for reason in session.readiness_reasons:
            print(f"READINESS | {reason}")
        for redirect_url in session.redirects_observed:
            print(f"REDIRECT | {redirect_url}")
        snapshots = session.snapshots or ((session.snapshot,) if session.snapshot else ())
        for index, snapshot in enumerate(snapshots, start=1):
            print(f"STEP {snapshot.step or index}: {len(snapshot.fields)} fields")
            for field in snapshot.fields:
                mapping = mappings.get(field.id)
                policy = mapping.answer_policy.value if mapping else AnswerPolicy.NEEDS_USER_INPUT.value
                required = "required" if field.required else "optional"
                present = "value present" if field.current_value_present else "empty"
                print(f"{field.field_type.value} | {required} | {policy} | {present} | {_safe_terminal_text(field.label)}")
            for action in snapshot.actions:
                intent = "SUBMISSION BLOCKED" if action.submission_intent else "action"
                print(f"{intent} | {_safe_terminal_text(action.label)}")
        if session.snapshot and session.snapshot.manual_intervention_reason:
            print(f"Manual intervention required: {session.snapshot.manual_intervention_reason.value}")
        return 0
    print(f"ATS: {session.ats.value}")
    print(f"Status: {session.status.value}")
    print(f"Steps: {len(session.snapshots)}")
    print(f"Filled factual fields: {len(session.filled_safe_field_ids)}")
    print(f"Pending fields: {len(session.pending_field_ids)}")
    for item in session.mappings:
        if item.answer_policy is AnswerPolicy.SAFE_AUTO_FILL:
            continue
        print(f"[{item.answer_policy.value}] {_safe_terminal_text(item.source_label)}")
        if item.recommendation:
            print(f"  document recommendation: {_safe_terminal_text(item.recommendation)}")
        if item.suggested_answer:
            print(f"  suggested answer for review: {_safe_terminal_text(item.suggested_answer)}")
    print("Review the form and every suggested answer in the original ATS flow before proceeding manually.")
    return 0


def _prepare_application_from_database(args, session, candidate) -> int:
    from ai_job_hunter.application_prep.service import build_application_package
    from ai_job_hunter.services.opportunities import get_opportunity

    opportunity = get_opportunity(session, args.job_id, candidate)
    if opportunity is None:
        raise ApplicationPreparationError("Job was not found in the local opportunity feed.")
    if opportunity.evaluation_is_stale or opportunity.decision is not FinalDecision.APPLY:
        raise ApplicationPreparationError("Only a current APPLY opportunity can be prepared.")
    existing_store = ApplicationPackageStore(args.packages_path)
    existing = existing_store.get_by_job(args.job_id)
    if existing is not None:
        print("A local package already exists; it was preserved. Use `apply show` to review it.")
        return 0

    job = session.scalar(
        select(Job).options(selectinload(Job.sources), selectinload(Job.company)).where(Job.id == args.job_id)
    )
    if job is None:
        raise ApplicationPreparationError("Job was not found in the local database.")
    sources = list(job.sources)
    if not sources:
        raise ApplicationPreparationError("Job has no saved source metadata for preparation.")
    source = sorted(
        sources,
        key=lambda item: (
            0 if opportunity.url and opportunity.url in {item.apply_url, item.canonical_url, item.original_url} else 1,
            0 if item.apply_url else 1,
            item.provider.casefold(),
        ),
    )[0]
    application = session.scalar(select(Application).where(Application.job_id == args.job_id))
    projects = load_candidate_projects(args.projects_config)
    documents = load_candidate_documents(args.documents_config).documents
    style = load_candidate_writing_style(args.writing_style_config)
    question_schema_status, schema_evidence = _question_schema_state(source.provider, source.raw_metadata, source.external_id)
    package = build_application_package(
        ApplicationJobInput(
            job_id=job.id,
            application_id=application.id if application else None,
            title=job.title,
            company=job.company.name if job.company else opportunity.company,
            description=source.source_description or job.description,
            provider=source.provider,
            canonical_job_url=source.canonical_url or source.original_url,
            application_url=source.apply_url,
            raw_metadata=source.raw_metadata or {},
            source_snapshot_at=source.discovered_at,
            technologies=opportunity.technologies,
            salary_min=source.salary_min,
            salary_max=source.salary_max,
            salary_currency=source.salary_currency,
            salary_period=source.salary_period,
            location=source.source_location or job.location,
        ),
        candidate,
        projects=projects,
        documents=documents,
        writing_style=style,
        question_schema_status=question_schema_status,
        question_schema_evidence=schema_evidence,
        request_cover_letter=args.cover_letter,
    )
    package.notes.append("Local preparation only. No browser automation, submission, or document upload was performed.")
    existing_store.save(package)
    print(f"Package prepared: {opportunity.company} — {opportunity.title}")
    print(f"Package status: {package.status.value}; readiness: {package.readiness.status.value}")
    print(f"Questions detected: {len(package.questions)}; requirements extracted: {len(package.requirements)}")
    print("No application was sent and no application status was changed.")
    return 0


def _question_schema_state(provider: str, metadata: dict | None, external_id: str | None):
    if extract_application_questions(metadata or {}, provider=provider):
        return QuestionSchemaStatus.AVAILABLE, "Structured application fields exist in saved ATS metadata."
    provider_name = (provider or "").casefold()
    if provider_name == "lever":
        return (
            QuestionSchemaStatus.UNAVAILABLE,
            "Lever's public postings API does not expose custom application questions; the hosted form must be reviewed manually.",
        )
    if provider_name == "ashby":
        return (
            QuestionSchemaStatus.UNAVAILABLE,
            "Ashby's unauthenticated public job-board response has no form schema; its employer integration requires customer authorization.",
        )
    if provider_name == "greenhouse" and external_id == "5356493008":
        return (
            QuestionSchemaStatus.UNAVAILABLE,
            "The documented public Greenhouse questions=true request returned HTTP 404 on 2026-09-28.",
        )
    return QuestionSchemaStatus.NOT_CHECKED, "No structured application-form questions were present in the saved posting metadata."


def _print_application_package(package) -> None:
    print(f"Package: {package.id}")
    print(f"Job ID: {package.job_id}")
    if package.company_name or package.job_title:
        print(f"Opportunity: {package.company_name or 'Unknown company'} — {package.job_title or 'Untitled role'}")
    if package.location:
        print(f"Location: {package.location}")
    if package.salary_min is not None or package.salary_max is not None:
        low = format(package.salary_min, "f") if package.salary_min is not None else "unspecified"
        high = format(package.salary_max, "f") if package.salary_max is not None else "unspecified"
        currency = f" {package.salary_currency}" if package.salary_currency else ""
        period = f" per {package.salary_period.casefold()}" if package.salary_period else ""
        print(f"Published salary: {low}–{high}{currency}{period}")
    print(f"ATS: {package.source_ats or 'unknown'}")
    print(f"Package status: {package.status.value}")
    print(f"Readiness: {package.readiness.status.value}")
    print(f"Canonical job URL: {package.canonical_job_url or 'unavailable'}")
    print(f"Application URL: {package.application_url or 'unavailable in saved source data'}")
    print(f"Requirements: {package.requirements_summary}")
    print(f"Candidate fit: {package.candidate_fit_summary}")
    print(f"Suggested CV: {package.suggested_cv_variant or 'not configured'}")
    print(f"Questions: {len(package.questions)}")
    for item in package.questions:
        print(f"- {item.label} [{item.normalized_type.value}, {item.answer_status.value}]")
        if item.answer is not None:
            print(f"  answer: {item.answer}")
    for item in package.missing_information:
        print(f"Needs attention: {item}")


def _monitor_filters(args) -> CompanyMonitorFilters:
    return CompanyMonitorFilters(
        supported_ats=True,
        public_salary=args.public_salary,
        compensation_evidence=args.compensation_evidence,
        multiple_evidence_sources=args.multiple_evidence_sources,
        remote_from_spain=args.remote_from_spain,
    )


def _configured_telegram_provider(settings):
    """Build the Telegram adapter only when both local settings are present."""

    if settings.telegram_bot_token is None or not settings.telegram_chat_id:
        return None
    try:
        return TelegramProvider(settings.telegram_bot_token, settings.telegram_chat_id)
    except ValueError:
        # Configuration failures must never echo the secret or provider URL.
        return None


def _run_notification_command(args, session, candidate, settings) -> int:
    command = args.notification_command
    if command == "pending":
        rows = list_pending_notifications(session, limit=args.limit)
        print(f"PENDING NOTIFICATIONS: {len(rows)}")
        _print_notification_rows(rows)
        return 0
    if command == "history":
        rows = list_notification_history(session, limit=args.limit)
        print(f"NOTIFICATION HISTORY: {len(rows)}")
        _print_notification_rows(rows)
        return 0
    if command == "send" and args.dry_run:
        previews = preview_notifications(
            session,
            candidate,
            review_threshold=settings.notify_review_min_priority,
            limit=args.limit,
        )
        print(
            "NOTIFICATION DRY RUN: "
            f"{len(previews)} eligible alert(s); REVIEW threshold={settings.notify_review_min_priority}. "
            "Priority is a ranking score, not a probability."
        )
        _print_notification_previews(previews)
        return 0

    provider = _configured_telegram_provider(settings)
    if provider is None:
        missing = []
        if settings.telegram_bot_token is None or not settings.telegram_bot_token.get_secret_value().strip():
            missing.append("TELEGRAM_BOT_TOKEN")
        if not settings.telegram_chat_id or not settings.telegram_chat_id.strip():
            missing.append("TELEGRAM_CHAT_ID")
        print(
            "Telegram delivery not started; missing local setting(s): " + ", ".join(missing),
            file=sys.stderr,
        )
        return 1

    if command == "send":
        result = send_notifications(
            session,
            candidate,
            provider,
            review_threshold=settings.notify_review_min_priority,
            limit=args.limit,
        )
    elif command == "retry-failed":
        result = retry_failed_notifications(
            session,
            candidate,
            provider,
            review_threshold=settings.notify_review_min_priority,
            limit=args.limit,
        )
    else:
        print(f"Unsupported notification command: {command}", file=sys.stderr)
        return 2
    _print_notification_batch(result)
    return 1 if result.failed else 0


def _print_notification_previews(previews: list[NotificationPreview]) -> None:
    for item in previews:
        priority = f"{item.priority}/100" if item.priority is not None else "UNKNOWN"
        location = item.location or "UNKNOWN"
        print(
            f"{item.decision} | priority={priority} | {item.company} — {item.title} | location={location}"
        )


def _print_notification_batch(result: NotificationBatchResult) -> None:
    print(
        "NOTIFICATION RESULTS: "
        f"created={result.created} sent={result.sent} failed={result.failed} "
        f"suppressed={result.suppressed} reused={result.reused}"
    )
    for item in result.items:
        suffix = f" | reason={item.failure_reason}" if item.failure_reason else ""
        print(f"{item.status} | {item.company} — {item.title}{suffix}")


def _print_notification_rows(rows) -> None:
    for row in rows:
        job = row.job
        company = job.company.name if job.company is not None else "Unknown company"
        priority = f"{row.priority}/100" if row.priority is not None else "UNKNOWN"
        sent = f" | sent_at={row.sent_at.isoformat()}" if row.sent_at else ""
        reason = row.failure_reason or row.suppression_reason
        failure = f" | reason={reason}" if reason else ""
        retryable = " | retryable=yes" if row.retryable else ""
        print(
            f"{row.status} | {row.decision} | priority={priority} | "
            f"{company} — {job.title}{sent}{failure}{retryable}"
        )


def _run_outreach_command(args, session, candidate) -> int:
    command = args.outreach_command
    if command == "candidates":
        rows = list_opportunities(
            session,
            candidate,
            limit=10000,
            include_applied=False,
            include_skip=False,
        )
        eligible = [
            row
            for row in rows
            if row.outreach_recommendation is not OutreachRecommendation.NO_OUTREACH
        ][: args.limit]
        print(f"OUTREACH CANDIDATES: {len(eligible)}")
        for row in eligible:
            label = _outreach_label(row.outreach_recommendation)
            priority = row.priority if row.priority is not None else "UNKNOWN"
            print(f"[{label}] {row.title} — {row.company} | priority={priority} | job={row.job_id}")
        return 0

    if command == "strategy":
        plan = plan_outreach_for_job(session, args.job_id, candidate)
        if plan is None:
            print(f"Job not found in the current opportunity feed: {args.job_id}", file=sys.stderr)
            return 2
        item = plan.opportunity
        print(f"[{_outreach_label(item.outreach_recommendation)}] {item.title} — {item.company}")
        print("Contact types: " + ", ".join(plan.preferred_contact_types))
        print("Recommendation reasons:")
        for reason in plan.recommendation_reasons:
            print(f"  - {reason}")
        print("Contact strategy reasons:")
        for reason in plan.contact_strategy_reasons:
            print(f"  - {reason}")
        return 0

    if command == "contacts":
        job = session.get(Job, args.job_id)
        if job is None:
            print(f"Job not found: {args.job_id}", file=sys.stderr)
            return 2
        if job.company_id is None:
            print("Job has no linked company; no local contacts can be listed.")
            return 0
        company = session.get(Company, job.company_id)
        if company is None:
            print("Job company was not found.", file=sys.stderr)
            return 2
        records = list_contacts_for_company(session, company.id)
        candidates = tuple(
            ContactCandidate(
                provider=record.source_provider or "manual",
                external_id=record.external_id,
                full_name=record.name,
                company=company.name,
                job_title=record.title,
                email=record.email,
                linkedin_url=record.linkedin_url,
            )
            for record in records
        )
        lookup = ContactLookupStrategy([ManualContactProvider(candidates)]).search_company(company.name)
        print(f"LOCAL CONTACTS: {len(lookup.contacts)} | {company.name}")
        if not lookup.contacts:
            print("No local contacts are saved. No external provider was queried.")
        for contact in lookup.contacts:
            print(
                f"{contact.full_name or 'UNKNOWN'} | {contact.job_title or 'UNKNOWN ROLE'} | "
                f"email={contact.email or 'UNKNOWN'} | LinkedIn={contact.linkedin_url or 'UNKNOWN'}"
            )
        print(f"Strong duplicates suppressed: {len(lookup.strong_duplicates)}")
        print(f"Possible matches requiring review: {len(lookup.possible_matches)}")
        return 0

    if command == "draft":
        results = create_initial_outreach_drafts(
            session,
            args.job_id,
            candidate,
            projects_path=args.projects_config,
            channel=DraftChannel(args.channel.upper()),
        )
        session.commit()
        print(f"DRAFT RECORDS: {len(results)}")
        for result in results:
            item = result.outreach
            company = item.company.name if item.company is not None else "UNKNOWN COMPANY"
            print(
                f"{'Created' if result.created else 'Existing'} {item.status}: {item.purpose} "
                f"| {company} | job={item.job_id} | recipient type={item.recipient_contact_type or 'UNKNOWN'} "
                "| contact=not identified"
            )
            if item.subject:
                print(f"Subject: {item.subject}")
            if item.body:
                print(item.body)
                print()
        print("No message was sent or approved.")
        return 0

    if command == "show":
        item = session.get(Outreach, args.outreach_id)
        if item is None:
            print(f"Outreach not found: {args.outreach_id}", file=sys.stderr)
            return 2
        print(f"Outreach: {item.id} | {item.status} | {item.purpose} | {item.channel}")
        if item.company is not None:
            print(f"Company: {item.company.name}")
        if item.job is not None:
            print(f"Job: {item.job.title}")
        if item.contact is not None:
            print(f"Contact: {item.contact.name} | {item.contact.title or 'UNKNOWN ROLE'}")
        elif item.recipient_contact_type:
            print(f"Recipient type: {item.recipient_contact_type} | identity not provided")
        if item.subject:
            print(f"Subject: {item.subject}")
        if item.body:
            print(item.body)
        print("History:")
        for event in get_outreach_history(session, item.id):
            before = event.from_status or "START"
            print(f"  {event.occurred_at.isoformat()} {before} → {event.to_status}")
            if event.note:
                print(f"    {event.note}")
        return 0

    if command == "approve":
        item = transition_outreach(
            session,
            args.outreach_id,
            OutreachStatus.APPROVED,
            note=args.note,
        )
        session.commit()
        print(f"Outreach approved: {item.id}")
        print("Approval only changes local state. No message was sent.")
        return 0

    raise OutreachPersistenceError("Unknown outreach command.")


def _outreach_label(value: OutreachRecommendation) -> str:
    return {
        OutreachRecommendation.OUTREACH_RECOMMENDED: "RECOMMENDED",
        OutreachRecommendation.OUTREACH_OPTIONAL: "OPTIONAL",
        OutreachRecommendation.NO_OUTREACH: "NO",
    }[value]


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


def _print_reevaluation_summary(summary: ReevaluationSummary) -> None:
    print("REEVALUATE DRY RUN (no writes, no Jev calls)" if summary.dry_run else "REEVALUATE")
    print(f"Jobs selected: {summary.jobs_selected}")
    planned_calls = sum(1 for item in summary.items if item.outcome == "JEV_CALL")
    if summary.dry_run:
        print(f"Jev calls planned: {planned_calls}")
    for label, value in (
        ("Jev calls attempted", summary.jev_calls),
        ("Jev evaluated", summary.jev_evaluated),
        ("Jev cache hits", summary.jev_cache_hits),
        ("Hard skips", summary.hard_skips),
        ("Pending: Jev budget", summary.pending_budget),
        ("Pending: errors", summary.pending_errors),
    ):
        print(f"{label}: {value}")
    for item in summary.items:
        decision = f" -> {item.decision}" if item.decision else ""
        print(f"{item.job_id} | {item.company or 'Unknown company'} | {item.title} | {item.outcome}{decision}")
    for job_id in summary.jobs_without_snapshot:
        print(f"{job_id} | no evaluable stored source snapshot; not evaluated")


def _print_opportunity(item: Opportunity, *, show_company_facts: bool = False) -> None:
    if item.evaluation_is_stale and item.decision is not FinalDecision.SKIP:
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
    print(f"Outreach: {_outreach_label(item.outreach_recommendation)}")
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
    if item.experience is not None:
        print(f"Experience: {item.experience.requirement_display} | {item.experience.outcome.value}")
        if item.experience.shortfall_years is not None:
            print(f"Experience shortfall: {item.experience.shortfall_years} years (local profile comparison)")
        for evidence in item.experience.evidence:
            print(f"  - Experience evidence: {evidence}")
    if item.deterministic_result:
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
