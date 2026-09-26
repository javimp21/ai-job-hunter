"""Evidence-led contact role suggestions; no universal contact ranking."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re


class ContactType(StrEnum):
    RECRUITER = "RECRUITER"
    TALENT = "TALENT"
    HIRING_MANAGER = "HIRING_MANAGER"
    ENGINEERING_MANAGER = "ENGINEERING_MANAGER"
    ENGINEER = "ENGINEER"
    FOUNDER = "FOUNDER"
    OTHER = "OTHER"


@dataclass(frozen=True)
class CompanySizeEvidence:
    """Optional sourced size evidence used to decide whether a founder is apt."""

    size_bucket: str | None = None
    source: str | None = None
    employee_count: int | None = None

    @property
    def is_evidenced_small_startup(self) -> bool:
        if not self.source or not self.source.strip():
            return False
        bucket = (self.size_bucket or "").strip().casefold().replace("-", "_")
        return bucket in {"startup", "small_startup", "small"} or (
            self.employee_count is not None and 0 < self.employee_count <= 50
        )


@dataclass(frozen=True)
class ContactStrategy:
    preferred_contact_types: tuple[ContactType, ...]
    reasons: tuple[str, ...]


def recommend_contact_strategy(
    job_title: str,
    company_size_evidence: CompanySizeEvidence | None = None,
) -> ContactStrategy:
    """Suggest roles using the job title and optional sourced company size.

    Ordering is contextual: recruiter-first for explicit recruiting/seniority
    signals; engineering peers/managers are foregrounded for technical roles;
    founder is included only with explicit small-startup evidence.
    """

    title = job_title.strip()
    lowered = title.casefold()
    if not title:
        return ContactStrategy(
            preferred_contact_types=(ContactType.RECRUITER, ContactType.OTHER),
            reasons=("No title evidence; only general contact roles are suggested.",),
        )

    reasons: list[str] = []
    contacts: list[ContactType] = []
    recruiting_title = bool(re.search(r"\b(recruit|talent|people|sourc)", lowered))
    engineering = bool(
        re.search(
            r"\b(software|backend|back-end|platform|devops|sre|data|engineering|engineer|ai|ml)\b",
            lowered,
        )
    )
    leadership = bool(re.search(r"\b(manager|director|head|lead|chief)\b", lowered))

    if recruiting_title:
        contacts.extend((ContactType.TALENT, ContactType.RECRUITER, ContactType.HIRING_MANAGER))
        reasons.append("The title names recruiting/talent work, so a talent contact is directly relevant.")
    elif engineering:
        # Vary the order based on concrete title evidence instead of a global ranking.
        if leadership:
            contacts.extend((ContactType.HIRING_MANAGER, ContactType.ENGINEERING_MANAGER, ContactType.ENGINEER))
            reasons.append("The title signals an engineering leadership role; a hiring or engineering manager may clarify scope.")
        else:
            contacts.extend((ContactType.ENGINEERING_MANAGER, ContactType.ENGINEER, ContactType.RECRUITER))
            reasons.append("The title describes technical work; engineering peers/managers can speak to the team and recruiter can clarify process.")
    else:
        contacts.extend((ContactType.RECRUITER, ContactType.HIRING_MANAGER, ContactType.OTHER))
        reasons.append("The title does not identify a specific function; recruiter and role owner are broad starting points.")

    if company_size_evidence and company_size_evidence.is_evidenced_small_startup:
        if engineering:
            contacts.append(ContactType.FOUNDER)
            reasons.append("Sourced small-startup size evidence makes a founder a possible additional contact.")
        else:
            reasons.append("Sourced small-startup size evidence is present, but the title does not establish founder relevance.")

    # Keep first occurrence and preserve this role-specific order.
    unique = tuple(dict.fromkeys(contacts))
    return ContactStrategy(preferred_contact_types=unique, reasons=tuple(reasons))
