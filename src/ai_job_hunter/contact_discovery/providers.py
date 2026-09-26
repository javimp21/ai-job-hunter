"""Non-network contact providers for manual records and deterministic tests."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from ai_job_hunter.contact_discovery.domain import ContactCandidate
from ai_job_hunter.deduplication.normalization import normalize_company_name, normalize_job_title


class ManualContactProvider:
    """Read user-entered candidates without completing or enriching their fields."""

    name = "manual"

    def __init__(self, contacts: Iterable[ContactCandidate] = ()) -> None:
        self._contacts = tuple(contacts)

    def search_company(self, company_name: str) -> tuple[ContactCandidate, ...]:
        key = normalize_company_name(company_name)
        if key is None:
            return ()
        return tuple(
            contact
            for contact in self._contacts
            if normalize_company_name(contact.company) == key
        )

    def search_job(self, company_name: str, job_title: str) -> tuple[ContactCandidate, ...]:
        company_key = normalize_company_name(company_name)
        title_key = _title_key(job_title)
        if company_key is None or not any(title_key):
            return ()
        return tuple(
            contact
            for contact in self._contacts
            if normalize_company_name(contact.company) == company_key
            and _title_key(contact.job_title or "") == title_key
        )


class FakeContactProvider:
    """Canned provider used by tests; it makes no network calls."""

    name = "fake"

    def __init__(
        self,
        *,
        company_results: Mapping[str, Iterable[ContactCandidate]] | None = None,
        job_results: Mapping[tuple[str, str], Iterable[ContactCandidate]] | None = None,
    ) -> None:
        self._company_results = {
            normalize_company_name(key) or "": tuple(values)
            for key, values in (company_results or {}).items()
        }
        self._job_results = {
            (normalize_company_name(company) or "", _title_key(title)): tuple(values)
            for (company, title), values in (job_results or {}).items()
        }
        self.company_queries: list[str] = []
        self.job_queries: list[tuple[str, str]] = []

    def search_company(self, company_name: str) -> tuple[ContactCandidate, ...]:
        self.company_queries.append(company_name)
        return self._company_results.get(normalize_company_name(company_name) or "", ())

    def search_job(self, company_name: str, job_title: str) -> tuple[ContactCandidate, ...]:
        self.job_queries.append((company_name, job_title))
        key = (normalize_company_name(company_name) or "", _title_key(job_title))
        return self._job_results.get(key, ())


def _title_key(title: str) -> tuple[frozenset[str], frozenset[str]]:
    normalized = normalize_job_title(title)
    return normalized.tokens, normalized.seniority
