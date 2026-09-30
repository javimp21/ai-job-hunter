"""Import and resolve locally curated company leads."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError

from ai_job_hunter.company_leads import (
    CompanyLeadsConfigError,
    get_company_lead,
    import_company_leads,
    list_company_leads,
    load_company_leads,
    resolve_company_leads,
)
from ai_job_hunter.config import get_settings
from ai_job_hunter.db.session import create_database_engine, create_session_factory
from ai_job_hunter.models import CompanyLeadStatus


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Import and resolve company discovery leads.")
    parser.add_argument("--database-url", help="override DATABASE_URL for this invocation")
    subparsers = parser.add_subparsers(dest="command", required=True)

    import_parser = subparsers.add_parser("import", help="validate and import a JSON lead list")
    import_parser.add_argument("--file", required=True, type=Path)
    list_parser = subparsers.add_parser("list", help="list imported company leads")
    list_parser.add_argument("--status", choices=tuple(item.value for item in CompanyLeadStatus))
    list_parser.add_argument("--limit", type=int, default=20)
    resolve_parser = subparsers.add_parser("resolve", help="find careers pages and supported ATS boards")
    resolve_parser.add_argument("--limit", type=int, default=20)
    resolve_parser.add_argument("--retry-failed", action="store_true")
    show_parser = subparsers.add_parser("show", help="show one lead and its discovery provenance")
    show_parser.add_argument("lead_id", type=UUID)

    for command_parser in (import_parser, list_parser, resolve_parser, show_parser):
        command_parser.add_argument("--database-url", default=argparse.SUPPRESS)

    args = parser.parse_args(argv)
    if args.command == "import":
        try:
            config = load_company_leads(args.file)
        except CompanyLeadsConfigError as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 2
    else:
        config = None
    if args.command in {"list", "resolve"}:
        maximum = 100 if args.command == "resolve" else 1000
        if not 1 <= args.limit <= maximum:
            parser.error(f"--limit must be from 1 to {maximum}")

    settings = get_settings()
    if args.database_url:
        settings = settings.model_copy(update={"database_url": args.database_url})
    engine = create_database_engine(settings)
    try:
        with create_session_factory(engine)() as session:
            if args.command == "import":
                summary = import_company_leads(session, config)
                session.commit()
                print(
                    "COMPANY LEADS IMPORT: "
                    f"CREATED {summary.created} | DUPLICATES {summary.duplicates} | "
                    f"UPDATED {summary.updated} | UNCHANGED {summary.unchanged} | INVALID 0"
                )
                return 0
            if args.command == "list":
                rows = list_company_leads(
                    session,
                    status=CompanyLeadStatus(args.status) if args.status else None,
                    limit=args.limit,
                )
                print(f"COMPANY LEADS: {len(rows)}")
                for lead in rows:
                    ats = (
                        f"{lead.ats_provider}:{lead.ats_identifier}"
                        if lead.ats_provider and lead.ats_identifier
                        else "UNKNOWN"
                    )
                    print(
                        f"{lead.status} | {lead.company_name} | ATS: {ats} | "
                        f"location hint: {lead.location_hint or 'UNKNOWN'} | "
                        f"hiring hint: {lead.hiring_hint or 'UNKNOWN'} | id={lead.id}"
                    )
                return 0
            if args.command == "resolve":
                summary = resolve_company_leads(
                    session,
                    limit=args.limit,
                    retry_failed=args.retry_failed,
                )
                session.commit()
                print(f"LEADS PROCESSED: {summary.selected}")
                for status in CompanyLeadStatus:
                    print(f"{status.value}: {summary.count(status)}")
                for result in summary.results:
                    ats = (
                        f"{result.ats_provider.value}:{result.ats_identifier}"
                        if result.ats_provider and result.ats_identifier
                        else "UNKNOWN"
                    )
                    print(
                        f"{result.status.value} | {result.company_name} | "
                        f"careers={result.careers_url or 'NOT FOUND'} | ATS={ats} | {result.note}"
                    )
                return 0
            if args.command == "show":
                lead = get_company_lead(session, args.lead_id)
                if lead is None:
                    print(f"Company lead not found: {args.lead_id}", file=sys.stderr)
                    return 2
                _print_lead(lead)
                return 0
    except SQLAlchemyError as error:
        print(
            f"ERROR: database operation failed ({type(error).__name__}); "
            "run the Alembic migration first and verify the configured database is available.",
            file=sys.stderr,
        )
        return 1
    finally:
        engine.dispose()
    return 2


def _print_lead(lead) -> None:
    print(f"Company lead: {lead.id}")
    print(f"Company: {lead.company_name} | normalized: {lead.normalized_name}")
    print(f"Status: {lead.status}")
    print(f"Website: {lead.website_url or 'UNKNOWN'}")
    print(f"Careers: {lead.careers_url or 'UNKNOWN'}")
    print(
        f"ATS: {lead.ats_provider or 'UNKNOWN'} | "
        f"identifier: {lead.ats_identifier or 'UNKNOWN'} | region: {lead.ats_region or 'UNKNOWN'}"
    )
    print(f"Source: {lead.source_type} | {lead.source_label}")
    print(f"Source URL: {lead.source_url or 'UNKNOWN'}")
    print(f"Location hint: {lead.location_hint or 'UNKNOWN'}")
    print(f"Hiring hint: {lead.hiring_hint or 'UNKNOWN'}")
    print(f"Resolution: {lead.resolution_note or 'NOT RESOLVED'}")
    print(f"Company Intelligence ID: {lead.company_id or 'NOT LINKED'}")
    print(f"Provenance records: {len(lead.source_provenance or [])}")


if __name__ == "__main__":
    raise SystemExit(main())
