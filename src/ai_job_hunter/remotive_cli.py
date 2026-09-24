"""Manual preview and ingestion commands for Remotive."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Sequence

from ai_job_hunter.connectors.remotive import RemotiveConnector, RemotiveConnectorError
from ai_job_hunter.db.session import create_database_engine, create_session_factory
from ai_job_hunter.services.pipeline import PipelineSummary, run_ingestion_pipeline

LOGGER = logging.getLogger("ai_job_hunter.remotive")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Preview or ingest jobs from Remotive's public API."
    )
    parser.add_argument("--limit", type=int, default=5, help="maximum API results (default: 5)")
    parser.add_argument("--all", action="store_true", help="request all active API results")
    parser.add_argument(
        "--show", type=int, default=3, help="number of offers to display in preview mode"
    )
    parser.add_argument("--search", help="Remotive's title/description search filter")
    parser.add_argument("--category", help="Remotive category name or slug")
    parser.add_argument("--company-name", help="Remotive company-name filter")
    parser.add_argument(
        "--ingest",
        action="store_true",
        help="persist offers through the existing pipeline using DATABASE_URL",
    )
    args = parser.parse_args(argv)

    if args.limit < 1:
        parser.error("--limit must be a positive integer")
    if args.show < 0:
        parser.error("--show cannot be negative")

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    connector = RemotiveConnector(
        limit=None if args.all else args.limit,
        search=args.search,
        category=args.category,
        company_name=args.company_name,
    )
    try:
        with connector:
            if args.ingest:
                summary = _ingest(connector)
                _log_summary(summary)
                return 1 if summary.failed else 0

            offers = connector.fetch_jobs()
            LOGGER.info("Fetched %d jobs from Remotive", len(offers))
            for offer in offers[: args.show]:
                company = offer.company_name or "Company not supplied"
                print(f"- {offer.title} | {company}")
                print(f"  Source: Remotive ({offer.source_url})")
            return 0
    except RemotiveConnectorError as error:
        LOGGER.error("Remotive request failed: %s", error)
        return 1


def _ingest(connector: RemotiveConnector) -> PipelineSummary:
    engine = create_database_engine()
    try:
        session_factory = create_session_factory(engine)
        with session_factory() as session:
            return run_ingestion_pipeline(connector, session)
    finally:
        engine.dispose()


def _log_summary(summary: PipelineSummary) -> None:
    LOGGER.info("Fetched %d jobs from Remotive", summary.fetched)
    LOGGER.info("Created: %d", summary.created)
    LOGGER.info("Already known: %d", summary.already_known)
    LOGGER.info("Matched existing: %d", summary.matched_existing)
    LOGGER.info("Possible matches: %d", summary.possible_match)
    LOGGER.info("Failed: %d", summary.failed)
    for failure in summary.failures:
        LOGGER.error("%s: %s", failure.provider, failure.message)


if __name__ == "__main__":
    raise SystemExit(main())
