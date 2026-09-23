"""Structural contract implemented by future job source connectors."""

from typing import Iterable, Protocol, runtime_checkable

from ai_job_hunter.domain.normalized_job import NormalizedJob


@runtime_checkable
class JobConnector(Protocol):
    """A source adapter that returns provider-independent job records."""

    def fetch_jobs(self) -> Iterable[NormalizedJob]:
        """Fetch and normalize the source's currently available offers."""
