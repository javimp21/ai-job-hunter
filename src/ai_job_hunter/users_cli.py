"""Manage users: ``python -m ai_job_hunter.users_cli import-owner --candidate-config candidate.local.json``."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from ai_job_hunter.config import get_settings
from ai_job_hunter.db.session import create_database_engine, create_session_factory
from ai_job_hunter.services.direct_postings import DirectPostingResolver
from ai_job_hunter.services.liveness import PostingLiveness
from ai_job_hunter.services.notifications import TelegramProvider
from ai_job_hunter.services.user_runs import run_for_users
from ai_job_hunter.services.users import import_owner_profile


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Users of the service.")
    sub = parser.add_subparsers(dest="command", required=True)
    owner = sub.add_parser("import-owner", help="store candidate.local.json as the owner's profile")
    owner.add_argument("--candidate-config", type=Path, default=Path("candidate.local.json"))
    run = sub.add_parser("run", help="evaluate stored offers and send alerts for every active person (not the owner)")
    run.add_argument("--max-jev-jobs", type=int, default=10, help="new Jev evaluations per person per run")
    run.add_argument("--max-notifications", type=int, default=5, help="alerts per person per run")
    run.add_argument("--daily-jev-cap", type=int, default=150, help="new Jev evaluations per person per day")
    run.add_argument("--max-age-days", type=int, default=None, help="only offers found in this many days (default: the global setting)")
    args = parser.parse_args(argv)
    engine = create_database_engine()
    if args.command == "run":
        return _run_users(engine, args)
    with create_session_factory(engine)() as session:
        user, profile, changed = import_owner_profile(session, args.candidate_config)
        session.commit()
        print(f"OWNER {user.id} | sector={profile.sector} | profile {'updated' if changed else 'unchanged'}")
    return 0


def _run_users(engine, args) -> int:
    settings = get_settings()
    if settings.telegram_bot_token is None:
        print("TELEGRAM_BOT_TOKEN is not configured; nothing was sent.")
        return 1
    factory = create_session_factory(engine)
    with factory() as lookup_session:
        results = run_for_users(
            factory,
            lambda chat: TelegramProvider(settings.telegram_bot_token, chat),
            review_threshold=settings.notify_review_min_priority,
            max_age_days=args.max_age_days or settings.notify_max_age_days,
            direct_postings=DirectPostingResolver(lookup_session),
            liveness=PostingLiveness(),
            max_jev_jobs=args.max_jev_jobs,
            max_notifications=args.max_notifications,
            daily_jev_cap=args.daily_jev_cap,
        )
    for result in results:
        print(
            f"USER {result.user_id} | offers={result.candidates} jev={result.jev_evaluated} sent={result.sent} "
            f"failed={result.failed}" + (" | trial ended" if result.trial_ended else "") + (f" | ERROR {result.error}" if result.error else "")
        )
    print(f"USERS: {len(results)}")
    return 1 if any(result.error for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(main())
