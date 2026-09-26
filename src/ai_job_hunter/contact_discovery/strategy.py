"""Provider-injected company/job contact lookup and conservative deduplication."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import replace

from ai_job_hunter.contact_discovery.domain import (
    ContactCandidate,
    ContactLookupResult,
    ContactMatchDecision,
    ContactPossibleMatch,
    ContactStrongDuplicate,
)
from ai_job_hunter.contact_discovery.matching import match_contacts
from ai_job_hunter.contact_discovery.protocol import ContactProvider


class ContactLookupStrategy:
    """Search injected providers and collapse only unambiguous strong duplicates."""

    def __init__(self, providers: Iterable[ContactProvider]) -> None:
        self._providers = tuple(providers)

    def search_company(self, company_name: str) -> ContactLookupResult:
        """Look up contacts at an exact company identity across providers."""

        candidates = tuple(
            candidate
            for provider in self._providers
            for candidate in provider.search_company(company_name)
        )
        return _build_result(company_name, None, candidates)

    def search_job(self, company_name: str, job_title: str) -> ContactLookupResult:
        """Look up contacts matching a company and job title via providers."""

        candidates = tuple(
            candidate
            for provider in self._providers
            for candidate in provider.search_job(company_name, job_title)
        )
        return _build_result(company_name, job_title, candidates)


def _build_result(
    company_name: str,
    job_title: str | None,
    candidates: Sequence[ContactCandidate],
) -> ContactLookupResult:
    contacts: list[ContactCandidate] = []
    strong_duplicates: list[ContactStrongDuplicate] = []
    possible_matches: list[ContactPossibleMatch] = []

    for candidate in candidates:
        comparisons = [(existing, match_contacts(existing, candidate)) for existing in contacts]
        exact_matches = [
            (existing, match)
            for existing, match in comparisons
            if match.decision is ContactMatchDecision.MATCH
        ]
        possible = [
            (existing, match)
            for existing, match in comparisons
            if match.decision is ContactMatchDecision.POSSIBLE_MATCH
        ]

        # A candidate that strongly matches one row but also possibly matches
        # another row is ambiguous in the collection, so retain it separately.
        if len(exact_matches) == 1 and not possible:
            canonical, match = exact_matches[0]
            strong_duplicates.append(ContactStrongDuplicate(canonical, candidate, match))
            continue

        for existing, match in exact_matches + possible:
            if match.decision is ContactMatchDecision.MATCH:
                match = replace(
                    match,
                    decision=ContactMatchDecision.POSSIBLE_MATCH,
                    reasons=(
                        "A strong match exists, but the candidate also matches another row; keep all rows separate for review.",
                    ),
                )
            possible_matches.append(ContactPossibleMatch(existing, candidate, match))
        contacts.append(candidate)

    return ContactLookupResult(
        company_name=company_name,
        job_title=job_title,
        contacts=tuple(contacts),
        strong_duplicates=tuple(strong_duplicates),
        possible_matches=tuple(possible_matches),
    )
