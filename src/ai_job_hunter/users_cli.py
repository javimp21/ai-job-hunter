"""Manage users: ``python -m ai_job_hunter.users_cli import-owner --candidate-config candidate.local.json``."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from ai_job_hunter.db.session import create_database_engine, create_session_factory
from ai_job_hunter.services.users import import_owner_profile


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Users of the service.")
    sub = parser.add_subparsers(dest="command", required=True)
    owner = sub.add_parser("import-owner", help="store candidate.local.json as the owner's profile")
    owner.add_argument("--candidate-config", type=Path, default=Path("candidate.local.json"))
    args = parser.parse_args(argv)
    engine = create_database_engine()
    with create_session_factory(engine)() as session:
        user, profile, changed = import_owner_profile(session, args.candidate_config)
        session.commit()
        print(f"OWNER {user.id} | sector={profile.sector} | profile {'updated' if changed else 'unchanged'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
