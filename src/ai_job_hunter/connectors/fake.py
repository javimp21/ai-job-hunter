"""In-memory connector for tests and local development."""

from collections.abc import Iterable, Iterator

from ai_job_hunter.domain.normalized_job import NormalizedJob


class FakeJobConnector:
    """Return a repeatable set of normalized offers without network access."""

    def __init__(self, jobs: Iterable[NormalizedJob]) -> None:
        self._jobs = tuple(jobs)

    def fetch_jobs(self) -> Iterator[NormalizedJob]:
        """Yield the configured records on every call."""

        return iter(self._jobs)
