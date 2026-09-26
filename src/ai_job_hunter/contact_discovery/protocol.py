"""Contact lookup provider contract."""

from __future__ import annotations

from typing import Protocol, Sequence, runtime_checkable

from ai_job_hunter.contact_discovery.domain import ContactCandidate


@runtime_checkable
class ContactProvider(Protocol):
    """A source that can return contacts for a company or a specific job.

    Implementations should return only data they are authorized to provide.
    The protocol deliberately has no outreach, LinkedIn scraping, or implicit
    network behavior.
    """

    name: str

    def search_company(self, company_name: str) -> Sequence[ContactCandidate]:
        """Return contacts associated with the exact company query."""

    def search_job(self, company_name: str, job_title: str) -> Sequence[ContactCandidate]:
        """Return contacts associated with the company and job query."""
