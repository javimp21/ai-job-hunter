"""Immutable contact discovery values and match reports."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


@dataclass(frozen=True, slots=True)
class ContactCandidate:
    """A provider-supplied contact record; missing personal data stays missing.

    The ``provider`` and ``external_id`` identify a source record, not a person
    globally. Names and employer information are optional and are never
    synthesized from an email address or URL.
    """

    provider: str = "manual"
    external_id: str | None = None
    full_name: str | None = None
    company: str | None = None
    job_title: str | None = None
    email: str | None = None
    linkedin_url: str | None = None


class ContactMatchDecision(StrEnum):
    """Whether two contact records can be treated as the same identity."""

    MATCH = "match"
    POSSIBLE_MATCH = "possible_match"
    NO_MATCH = "no_match"


@dataclass(frozen=True, slots=True)
class ContactMatchSignals:
    """Exact identity evidence used for one comparison."""

    strong_matches: tuple[str, ...]
    strong_conflicts: tuple[str, ...]
    name_company_match: bool


@dataclass(frozen=True, slots=True)
class ContactMatch:
    """An explainable identity comparison; only strong matches can deduplicate."""

    decision: ContactMatchDecision
    signals: ContactMatchSignals
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ContactStrongDuplicate:
    """A record suppressed from the canonical result by one unambiguous match."""

    canonical: ContactCandidate
    duplicate: ContactCandidate
    match: ContactMatch


@dataclass(frozen=True, slots=True)
class ContactPossibleMatch:
    """Two records that remain separate because identity is weak or ambiguous."""

    first: ContactCandidate
    second: ContactCandidate
    match: ContactMatch


@dataclass(frozen=True, slots=True)
class ContactLookupResult:
    """Provider results with safe strong deduplication and visible weak matches."""

    company_name: str
    job_title: str | None
    contacts: tuple[ContactCandidate, ...]
    strong_duplicates: tuple[ContactStrongDuplicate, ...]
    possible_matches: tuple[ContactPossibleMatch, ...]
