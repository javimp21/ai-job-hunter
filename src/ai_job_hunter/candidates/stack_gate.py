"""A strict stack: offers must use one of the person's core technologies, or say another language is fine without it.

With ``preferences.core_technologies`` set (for example Java and Spring Boot), an offer passes only when its title or
text mentions one of them, or when the text says experience in its own language is not needed ("no prior experience
required", "any programming language", "sin experiencia previa"...). An offer that names no technology at all does not
pass either: there is nothing to show it uses the person's stack. Empty ``core_technologies`` turns the gate off.
"""

from __future__ import annotations

import re
from dataclasses import replace

from ai_job_hunter.candidates.prefilter import JobPreFilterResult, PreFilterDecision
from ai_job_hunter.candidates.profile import CandidatePreferences
from ai_job_hunter.candidates.technologies import extract_job_technologies, normalize_technology_list

# Ways an offer says the person does not need to know its language already.
_NO_EXPERIENCE_NEEDED = re.compile(
    r"no (?:prior |previous )?(?:\w+ )?experience(?: (?:with|in) [\w.#+]+)? (?:is )?(?:required|needed|necessary)"
    r"|(?:any|whatever) (?:modern |major |mainstream |object[- ]oriented |backend |general[- ]purpose )*"
    r"(?:programming )?language"
    r"|(?:language|stack|technology)[- ]agnostic"
    r"|(?:we(?:'| wi)ll|will|we) (?:teach|train) you"
    r"|(?:don't|do not) need (?:to know|prior experience|experience)"
    r"|sin experiencia previa|no (?:se )?requiere experiencia(?: previa)?|no es necesaria experiencia(?: previa)?"
    r"|cualquier lenguaje|te formamos|formaci[oó]n a cargo de la empresa",
    re.IGNORECASE,
)


def stack_gate_reason(title: str, description: str | None, preferences: CandidatePreferences) -> str | None:
    """Why the offer fails the person's strict stack, or ``None`` when it passes (or the gate is off)."""

    core = normalize_technology_list(preferences.core_technologies, sector=preferences.sector)
    if not core:
        return None
    found, _required = extract_job_technologies(title, description, sector=preferences.sector)
    if core & set(found):
        return None
    if _NO_EXPERIENCE_NEEDED.search(f"{title}\n{description or ''}"):
        return None
    wanted = ", ".join(sorted(preferences.core_technologies))
    if not found:
        return f"The offer names no technology, so nothing shows it uses the candidate's core stack ({wanted})."
    return (
        f"The offer asks for {', '.join(found)} but not the candidate's core stack ({wanted}), "
        "and it does not say experience in its own stack is unnecessary."
    )


def apply_stack_gate(
    result: JobPreFilterResult, title: str, description: str | None, preferences: CandidatePreferences
) -> JobPreFilterResult:
    """The same result, rejected when the offer fails the strict stack."""

    reason = stack_gate_reason(title, description, preferences)
    if reason is None or result.decision is PreFilterDecision.REJECT:
        return result
    return replace(result, decision=PreFilterDecision.REJECT, reasons=(reason, *result.reasons))
