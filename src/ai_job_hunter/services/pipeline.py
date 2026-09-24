"""Run a connector and ingest each offer independently."""

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from ai_job_hunter.connectors.protocol import JobConnector
from ai_job_hunter.domain.normalized_job import NormalizedJob
from ai_job_hunter.services.ingestion import (
    IngestionResult,
    IngestionStatus,
    ingest_job,
)


@dataclass(frozen=True, slots=True)
class PipelineFailure:
    """A connector or offer failure recorded in the pipeline summary."""

    provider: str
    external_id: str | None
    message: str


@dataclass(slots=True)
class PipelineSummary:
    """Counts of fetched offers and their ingestion outcomes."""

    fetched: int = 0
    created: int = 0
    already_known: int = 0
    matched_existing: int = 0
    possible_match: int = 0
    failed: int = 0
    failures: list[PipelineFailure] = field(default_factory=list)
    possible_matches: list[IngestionResult] = field(default_factory=list)
    matched_results: list[IngestionResult] = field(default_factory=list)


def run_ingestion_pipeline(connector: JobConnector, session: Session) -> PipelineSummary:
    """Fetch normalized offers and persist them one transaction at a time."""

    summary = PipelineSummary()
    try:
        for offer in connector.fetch_jobs():
            summary.fetched += 1
            _ingest_one(offer, session, summary)
    except Exception as error:
        summary.failed += 1
        summary.failures.append(
            PipelineFailure(
                provider=type(connector).__name__,
                external_id=None,
                message=f"{type(error).__name__}: {error}",
            )
        )
    return summary


def _ingest_one(offer: NormalizedJob, session: Session, summary: PipelineSummary) -> None:
    try:
        result = ingest_job(session, offer)
    except Exception as error:
        summary.failed += 1
        summary.failures.append(
            PipelineFailure(
                provider=offer.provider,
                external_id=offer.external_id,
                message=f"{type(error).__name__}: {error}",
            )
        )
        return

    if result.status is IngestionStatus.CREATED:
        summary.created += 1
    elif result.status is IngestionStatus.ALREADY_KNOWN:
        summary.already_known += 1
    elif result.status is IngestionStatus.MATCHED_EXISTING:
        summary.matched_existing += 1
        summary.matched_results.append(result)
    elif result.status is IngestionStatus.POSSIBLE_MATCH:
        summary.possible_match += 1
        summary.possible_matches.append(result)
