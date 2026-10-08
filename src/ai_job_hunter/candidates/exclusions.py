"""What a person has asked never to see: title terms and companies (learned from their opinions, always undoable).

A term matches whole words of the title, and also the same words written together or apart: "full stack" matches
"Full-Stack Developer" and "Fullstack Engineer"; "java" never matches "JavaScript".
"""

from __future__ import annotations

import re
from dataclasses import replace

from ai_job_hunter.candidates.prefilter import JobPreFilterResult, PreFilterDecision
from ai_job_hunter.candidates.profile import CandidatePreferences

_WORDS = re.compile(r"[^\W_]+", re.UNICODE)


def _tokens(text: str) -> list[str]:
    return _WORDS.findall(text.casefold())


def title_matches(title: str, term: str) -> bool:
    words, wanted = _tokens(title), _tokens(term)
    if not wanted:
        return False
    size = len(wanted)
    if any(words[start:start + size] == wanted for start in range(len(words) - size + 1)):
        return True
    joined = "".join(wanted)
    return size > 1 and joined in words  # "full stack" also matches the single word "fullstack"


def company_matches(company: str | None, excluded: str) -> bool:
    """Same name ignoring case, punctuation and spacing ("Acme S.L." is "acme sl")."""

    return bool(company) and "".join(_tokens(company)) == "".join(_tokens(excluded)) != ""


def exclusion_reason(title: str, company: str | None, preferences: CandidatePreferences) -> str | None:
    for term in preferences.excluded_title_terms:
        if title_matches(title, term):
            return f"The title contains '{term}', which the candidate asked not to receive."
    for name in preferences.excluded_companies:
        if company_matches(company, name):
            return f"The company is '{name}', which the candidate asked not to receive."
    return None


def apply_exclusions(
    result: JobPreFilterResult, title: str, company: str | None, preferences: CandidatePreferences
) -> JobPreFilterResult:
    """The same result, rejected when the person excluded this title term or company."""

    reason = exclusion_reason(title, company, preferences)
    if reason is None or result.decision is PreFilterDecision.REJECT:
        return result
    return replace(result, decision=PreFilterDecision.REJECT, reasons=(reason, *result.reasons))
