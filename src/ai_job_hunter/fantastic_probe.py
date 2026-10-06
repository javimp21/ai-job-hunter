"""Measure what Fantastic.jobs would add before it is enabled as a portal.

``sample N`` fetches one page of N postings (N job credits, one request credit, counted in the daily budget) and
reports, with counts only, how many we already have (by URL or by company + normalized title), how many pass the
deterministic prefilter, and how fresh they are. No posting text, company or person is printed.
"""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from ai_job_hunter.candidates import load_candidate_config
from ai_job_hunter.config import get_settings
from ai_job_hunter.connectors.fantastic_jobs import (
    DEFAULT_CREDITS_PATH,
    FantasticJobsConnector,
    FantasticJobsConnectorError,
)
from ai_job_hunter.connectors.theirstack import CreditBudget
from ai_job_hunter.db.session import create_database_engine, create_session_factory
from ai_job_hunter.decision_engine import build_decision_contexts
from ai_job_hunter.theirstack_probe import known_identities, overlap


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Measure Fantastic.jobs coverage against the stored jobs.")
    parser.add_argument("n", type=int, help="postings to fetch (1-100)")
    parser.add_argument("--time-frame", default="24h", choices=("1h", "24h", "7d"))
    args = parser.parse_args(argv)
    if not 1 <= args.n <= 100:
        parser.error("n must be from 1 to 100")
    settings = get_settings()
    connector = FantasticJobsConnector(
        api_key=settings.fantastic_jobs_api_key,
        budget=CreditBudget(DEFAULT_CREDITS_PATH, max(settings.fantastic_jobs_daily_credits, args.n)),
        page_size=args.n,
        time_frame=args.time_frame,
    )
    try:
        jobs = connector.fetch_jobs()
    except FantasticJobsConnectorError as error:
        print(f"Fantastic.jobs: {error}")
        return 2
    engine = create_database_engine(settings)
    try:
        with create_session_factory(engine)() as session:
            urls, pairs = known_identities(session)
    finally:
        engine.dispose()
    counts = overlap(jobs, urls, pairs)
    candidate_path = Path("candidate.local.json")
    if candidate_path.exists():
        for context in build_decision_contexts(list(jobs), load_candidate_config(candidate_path)):
            counts[f"prefilter_{context.deterministic.decision.value}"] += 1
    now = datetime.now(UTC)
    ages: Counter[str] = Counter()
    for job in jobs:
        hours = (now - job.published_at).total_seconds() / 3600 if job.published_at else None
        ages["unknown" if hours is None else "<3h" if hours < 3 else "<24h" if hours < 24 else ">=24h"] += 1
    boards = Counter((job.raw_metadata or {}).get("board") for job in jobs)
    for key in ("fetched", "known_by_url", "known_by_company_and_title", "new",
                "prefilter_PASS", "prefilter_REVIEW", "prefilter_REJECT"):
        print(f"{key}: {counts[key]}")
    print("age:", dict(ages))
    print("boards:", dict(boards))
    print("balance:", {k: v for k, v in connector.last_headers.items() if "remaining" in k})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
