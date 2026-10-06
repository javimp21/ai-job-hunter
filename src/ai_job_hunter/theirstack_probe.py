"""Measure what TheirStack would add before it is enabled as a portal.

``count`` asks how many postings match the default filters (1 credit; API preview mode is not available by default).
``sample N`` fetches N postings (N credits, counted in the daily budget) and reports, with
counts only, how many we already have in the database, by employer URL or by company +
normalized title, and how many the deterministic prefilter lets through (PASS/REVIEW) rather than
rejects. No posting text, company or person is printed.
"""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_job_hunter.candidates import load_candidate_config
from ai_job_hunter.config import get_settings
from ai_job_hunter.connectors.theirstack import (
    DEFAULT_CREDITS_PATH,
    CreditBudget,
    TheirStackConnector,
    TheirStackConnectorError,
)
from ai_job_hunter.db.session import create_database_engine, create_session_factory
from ai_job_hunter.decision_engine import build_decision_contexts
from ai_job_hunter.deduplication.normalization import (
    normalize_company_name,
    normalize_job_title,
    normalize_job_url,
)
from ai_job_hunter.domain.normalized_job import NormalizedJob
from ai_job_hunter.models import Company, Job, JobSource


def known_identities(session: Session) -> tuple[set[str], set[tuple[str, frozenset[str]]]]:
    """URLs and (company, title tokens) of every job already stored."""

    urls: set[str] = set()
    for original, canonical, apply in session.execute(
        select(JobSource.original_url, JobSource.canonical_url, JobSource.apply_url)
    ):
        for value in (original, canonical, apply):
            normalized = normalize_job_url(value) if value else None
            if normalized:
                urls.add(normalized)
    pairs: set[tuple[str, frozenset[str]]] = set()
    for company, title in session.execute(select(Company.name, Job.title).join(Job, Job.company_id == Company.id)):
        pairs.add((normalize_company_name(company) or company.casefold(), normalize_job_title(title).tokens))
    return urls, pairs


def overlap(
    jobs: Sequence[NormalizedJob], urls: set[str], pairs: set[tuple[str, frozenset[str]]]
) -> Counter[str]:
    result: Counter[str] = Counter()
    for job in jobs:
        result["fetched"] += 1
        employer = normalize_job_url(job.apply_url) if job.apply_url else None
        if job.apply_url != job.source_url:
            result["with_employer_link"] += 1
        if employer and employer in urls:
            result["known_by_url"] += 1
        elif job.company_name and (
            normalize_company_name(job.company_name) or job.company_name.casefold(),
            normalize_job_title(job.title).tokens,
        ) in pairs:
            result["known_by_company_and_title"] += 1
        else:
            result["new"] += 1
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Measure TheirStack coverage against the stored jobs.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("count", help="matches for the default filters (1 credit)")
    sub.add_parser("balance", help="API credits left on the account (free)")
    sample = sub.add_parser("sample", help="fetch N postings (N credits) and compare them with the database")
    sample.add_argument("n", type=int, help="postings to fetch (1-25)")
    sample.add_argument("--page", type=int, default=0, help="page of N results to read (0 = newest)")
    args = parser.parse_args(argv)
    settings = get_settings()
    connector = TheirStackConnector(
        api_key=settings.theirstack_api_key,
        budget=CreditBudget(DEFAULT_CREDITS_PATH, settings.theirstack_daily_credits),
    )
    try:
        if args.command == "balance":
            print(f"THEIRSTACK CREDITS LEFT: {connector.credit_balance()}")
            return 0
        if args.command == "count":
            print(f"THEIRSTACK MATCHES (default filters, last day): {connector.count_matches()}")
            return 0
        if not 1 <= args.n <= 25:
            parser.error("n must be from 1 to 25")
        connector._page_size = args.n  # noqa: SLF001 - one measured page
        connector.page = max(0, args.page)
        jobs = connector.fetch_jobs()
    except TheirStackConnectorError as error:
        print(f"TheirStack: {error}")
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
        contexts = build_decision_contexts(list(jobs), load_candidate_config(candidate_path))
        for context in contexts:
            counts[f"prefilter_{context.deterministic.decision.value}"] += 1
    for key in ("fetched", "with_employer_link", "known_by_url", "known_by_company_and_title", "new",
                "prefilter_PASS", "prefilter_REVIEW", "prefilter_REJECT"):
        print(f"{key}: {counts[key]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
