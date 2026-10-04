"""`ai-job-hunter outreach ...` commands for Company Hunter.

Every command only reads/writes the local database. The two that talk to the
network are explicit: ``find-contacts`` reads a company's own public pages
politely, and ``weekly --send`` / ``connections --send`` post to the
candidate's own Telegram chat. Nothing is ever sent to a company or LinkedIn.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_job_hunter.company_hunter.contacts import discover_contacts, prune_contacts
from ai_job_hunter.company_hunter.fetching import PoliteFetcher
from ai_job_hunter.company_hunter.notify import (
    format_drafts,
    send_connections,
    send_weekly,
    weekly_message,
)
from ai_job_hunter.company_hunter.queue import (
    ConnectionQueueError,
    build_follow_up,
    local_day,
    mark_accepted,
    mark_sent,
    mark_skipped,
    regenerate_note_from_post,
    suggest_connections,
)
from ai_job_hunter.company_hunter.ranking import CompanyFit, rank_companies
from ai_job_hunter.company_hunter.service import best_contact, draft_for_company
from ai_job_hunter.company_hunter.writing import HunterWritingError
from ai_job_hunter.models import Company, ConnectionRequest, Contact
from ai_job_hunter.services.cover_letters import CoverLetterError

HUNTER_COMMANDS = frozenset(
    {"companies", "find-contacts", "prune-contacts", "company-draft", "weekly", "connections", "connection"}
)
NOTHING_SENT = "Nothing was sent to any company or to LinkedIn."


def add_parsers(outreach_commands: Any) -> None:
    companies = outreach_commands.add_parser(
        "companies", help="rank known companies by explainable fit (no network)"
    )
    companies.add_argument("--limit", type=int, default=20)
    companies.add_argument("--excluded", action="store_true", help="also list companies excluded (applied/dismissed)")

    find = outreach_commands.add_parser(
        "find-contacts",
        help="read a company's own public pages politely and store verifiable contacts",
    )
    find.add_argument("company", nargs="?", help="company id or name")
    find.add_argument("--top", type=int, default=0, help="run for the N top-ranked companies instead")
    find.add_argument("--max-pages", type=int, default=8)

    prune = outreach_commands.add_parser(
        "prune-contacts",
        help="re-check stored Company Hunter contacts with the current rules (--apply deletes the invalid ones)",
    )
    prune.add_argument("--apply", action="store_true")

    draft = outreach_commands.add_parser(
        "company-draft", help="draft an email and a LinkedIn DM for one company with Claude (never sent)"
    )
    draft.add_argument("company", help="company id or name")
    draft.add_argument("--language", choices=("auto", "es", "en"), default="auto")
    draft.add_argument("--force", action="store_true", help="replace the existing drafts")

    weekly = outreach_commands.add_parser(
        "weekly", help="the weekly Company Hunter message (prints it; --send posts it to your Telegram chat)"
    )
    weekly.add_argument("--top", type=int, default=5)
    weekly.add_argument("--find-contacts", action="store_true", help="read public pages for the top companies first")
    weekly.add_argument("--send", action="store_true", help="post to your own Telegram chat")

    connections = outreach_commands.add_parser(
        "connections",
        help="today's manual LinkedIn connection suggestions (--send posts them to your Telegram chat)",
    )
    connections.add_argument("--count", type=int, default=5, help="people to suggest today (1-5)")
    connections.add_argument("--send", action="store_true", help="post to your own Telegram chat")
    connections.add_argument("--allow-weekend", action="store_true")

    connection = outreach_commands.add_parser(
        "connection", help="record what you did with a suggestion: sent, accepted, skip, post, followup"
    )
    connection.add_argument("action", choices=("sent", "accepted", "skip", "post", "followup", "show"))
    connection.add_argument("request_id", type=UUID)
    connection.add_argument("--text", help="with `post`: the pasted LinkedIn post text")
    connection.add_argument("--file", type=Path, help="with `post`: a file with the pasted post")


def validate(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    command = args.outreach_command
    if command == "companies" and args.limit < 1:
        parser.error("--limit must be positive")
    if command == "find-contacts":
        if args.top < 0 or args.max_pages < 1:
            parser.error("--top cannot be negative and --max-pages must be positive")
        if not args.company and args.top < 1:
            parser.error("give a company or --top N")
    if command == "weekly" and args.top < 1:
        parser.error("--top must be positive")
    if command == "connections" and not 1 <= args.count <= 5:
        parser.error("--count must be between 1 and 5")
    if command == "connection" and args.action == "post" and not (args.text or args.file):
        parser.error("post needs --text or --file")


def run(args: argparse.Namespace, session: Session, settings: Any) -> int:
    command = args.outreach_command
    try:
        if command == "companies":
            return _companies(args, session)
        if command == "find-contacts":
            return _find_contacts(args, session)
        if command == "prune-contacts":
            return _prune(args, session)
        if command == "company-draft":
            return _company_draft(args, session)
        if command == "weekly":
            return _weekly(args, session, settings)
        if command == "connections":
            return _connections(args, session, settings)
        if command == "connection":
            return _connection(args, session)
    except (CoverLetterError, ConnectionQueueError) as error:
        session.rollback()
        print(str(error), file=sys.stderr)
        return 2
    raise ValueError(f"Unknown outreach command: {command}")


def resolve_company(session: Session, reference: str) -> Company:
    try:
        company = session.get(Company, UUID(reference))
        if company is not None:
            return company
    except ValueError:
        pass
    wanted = reference.strip().casefold()
    matches = [row for row in session.scalars(select(Company)).all() if row.name.casefold() == wanted]
    if not matches:
        matches = [row for row in session.scalars(select(Company)).all() if wanted in row.name.casefold()]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise HunterWritingError(f"No company matches {reference!r}.")
    raise HunterWritingError(
        f"{len(matches)} companies match {reference!r}: " + ", ".join(f"{m.name} ({m.id})" for m in matches[:5])
    )


def _print_fit(index: int, fit: CompanyFit) -> None:
    print(f"{index}. {fit.name} | fit {fit.score}/100 (review priority, not probability) | stage {fit.stage.value} | company={fit.company_id}")
    for factor in fit.factors:
        print(f"     {factor.name}: {factor.status.value} +{factor.points}/{factor.max_points} — {factor.reason}")


def _companies(args: argparse.Namespace, session: Session) -> int:
    result = rank_companies(session, limit=args.limit)
    print(f"COMPANY HUNTER RANKING: {len(result.ranked)}")
    for index, fit in enumerate(result.ranked, start=1):
        _print_fit(index, fit)
    if result.unresolved_leads:
        print(f"{result.unresolved_leads} lead(s) are not linked to a company yet (resolve them first).")
    if args.excluded:
        for item in result.excluded:
            print(f"excluded: {item.name} — {item.reason}")
    return 0


def _find_contacts(args: argparse.Namespace, session: Session) -> int:
    if args.top:
        targets = [(fit.company_id, fit.name) for fit in rank_companies(session, limit=args.top).ranked]
    else:
        company = resolve_company(session, args.company)
        targets = [(company.id, company.name)]
    for company_id, name in targets:
        result = discover_contacts(
            session, company_id, fetcher=PoliteFetcher(max_pages=args.max_pages)
        )
        session.commit()
        print(
            f"{name}: pages={result.pages_fetched} api_calls={result.api_calls} found={result.found} "
            f"stored={result.created} existing={result.existing}"
        )
        if result.size is not None:
            print(f"  size: {result.size.size_class.value} ({result.size.basis.value}) — {result.size.detail}")
        for person, role, source in result.stored:
            print(f"  stored: {person} — {role or 'UNKNOWN ROLE'} — {source}")
        for person, role, why in result.skipped:
            print(f"  not stored: {person} — {role} — {why}")
        for note in result.notes:
            print(f"  note: {note}")
        for target, reason in result.refused:
            print(f"  not fetched: {target} — {reason}")
    print("Only public pages published by the company were read (robots.txt respected). LinkedIn was not contacted.")
    return 0


def _prune(args: argparse.Namespace, session: Session) -> int:
    result = prune_contacts(session, apply=args.apply)
    session.commit()
    print(f"CONTACTS CHECKED: {result.checked} | INVALID: {len(result.invalid)}")
    for contact, why in result.invalid:
        print(f"  invalid: {contact.name} — {contact.title or 'UNKNOWN ROLE'} @ {contact.company.name} — {why}")
    for contact in result.kept_referenced:
        print(f"  kept (referenced by an outreach or connection request): {contact.name}")
    print(f"deleted: {result.deleted}" if args.apply else "(dry run; add --apply to delete the invalid, unreferenced ones)")
    return 0


def _company_draft(args: argparse.Namespace, session: Session) -> int:
    company = resolve_company(session, args.company)
    outcome = draft_for_company(session, company.id, client=None, language=args.language, force=args.force)
    session.commit()
    print(("Created" if outcome.created else "Existing") + " DRAFT records (status DRAFT, not approved).")
    print(format_drafts(outcome))
    print(NOTHING_SENT)
    return 0


def _best_contacts(session: Session, fits: list[CompanyFit]) -> dict[UUID, Contact | None]:
    out: dict[UUID, Contact | None] = {}
    for fit in fits:
        contacts = tuple(
            session.scalars(select(Contact).where(Contact.company_id == fit.company_id).order_by(Contact.created_at)).all()
        )
        out[fit.company_id] = best_contact(contacts, small_known=fit.size.known_small if fit.size else False)
    return out


def _weekly(args: argparse.Namespace, session: Session, settings: Any) -> int:
    ranking = rank_companies(session, limit=args.top)
    fits = list(ranking.ranked)
    if args.find_contacts:
        for fit in fits:
            discover_contacts(session, fit.company_id, fetcher=PoliteFetcher())
            session.commit()
    now = datetime.now(UTC)
    iso = now.isocalendar()
    text, keyboard = weekly_message(fits, _best_contacts(session, fits), week_label=f"{iso.year}-W{iso.week:02d}")
    print(text.replace("<b>", "").replace("</b>", ""))
    if not args.send:
        print("(not sent; add --send to post it to your own Telegram chat)")
        return 0
    provider = _provider(settings)
    if provider is None:
        print("Telegram is not configured (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID).", file=sys.stderr)
        return 1
    send_weekly(provider, text, keyboard)
    print("REAL ACTION: one Telegram message was posted to your own chat. " + NOTHING_SENT)
    return 0


def _connections(args: argparse.Namespace, session: Session, settings: Any) -> int:
    now = datetime.now(UTC)
    ranked = rank_companies(session, limit=30).ranked
    result = suggest_connections(
        session, ranked, client=None, now=now, target=args.count, allow_weekend=args.allow_weekend
    )
    session.commit()
    print(f"CONNECTION SUGGESTIONS TODAY: {len(result.today)} ({len(result.new)} new)")
    if result.reason:
        print(f"note: {result.reason}")
    for failure in result.failures:
        print(f"skipped: {failure}")
    for index, request in enumerate(result.today, start=1):
        contact = request.contact
        linkedin = contact.linkedin_url or "search by name (no public profile link found)"
        print(f"{index}. {contact.name} — {contact.title or 'UNKNOWN ROLE'} @ {request.company.name} | {linkedin}")
        print(f"   request={request.id} status={request.status} note ({len(request.note)}/300, {request.language}): {request.note}")
    if not args.send:
        print("(not sent; add --send to post them to your own Telegram chat)")
        return 0
    if not result.today:
        return 0
    provider = _provider(settings)
    if provider is None:
        print("Telegram is not configured (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID).", file=sys.stderr)
        return 1
    delivery = send_connections(session, provider, result.today, now=now, day_label=local_day(now))
    session.commit()
    print(f"REAL ACTION: {delivery.sent} Telegram message(s) posted to your own chat. {NOTHING_SENT}")
    for failure in delivery.failed:
        print(f"delivery problem: {failure}", file=sys.stderr)
    return 0 if not delivery.failed else 1


def _connection(args: argparse.Namespace, session: Session) -> int:
    if args.action == "show":
        request = session.get(ConnectionRequest, args.request_id)
        if request is None:
            raise ConnectionQueueError("Connection request not found.")
    elif args.action == "sent":
        request = mark_sent(session, args.request_id)
    elif args.action == "accepted":
        request = mark_accepted(session, args.request_id)
    elif args.action == "skip":
        request = mark_skipped(session, args.request_id)
    elif args.action == "post":
        text = args.text if args.text else args.file.read_text(encoding="utf-8")
        request = regenerate_note_from_post(session, args.request_id, text, client=None)
    else:
        build_follow_up(session, args.request_id, client=None)
        request = session.get(ConnectionRequest, args.request_id)
    session.commit()
    print(
        f"{request.contact.name} @ {request.company.name} | status={request.status} "
        f"| suggested={request.suggested_at:%Y-%m-%d} sent={request.sent_at or '-'} accepted={request.accepted_at or '-'} "
        f"skip_until={request.skip_until or '-'}"
    )
    print(f"Note ({len(request.note)}/300): {request.note}")
    if request.follow_up_draft:
        print(f"Follow-up draft: {request.follow_up_draft}")
    print("This only records state; LinkedIn was not contacted.")
    return 0


def _provider(settings: Any):
    from ai_job_hunter.services.notifications import TelegramProvider

    if settings.telegram_bot_token is None or not settings.telegram_chat_id:
        return None
    try:
        return TelegramProvider(settings.telegram_bot_token, settings.telegram_chat_id)
    except ValueError:
        return None
