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

    Ordering is contextual: recruiter-first by default (talent title or size not
    evidenced as small); leadership titles lead with the hiring manager;
    founder leads only with explicit small-company evidence.
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
        small = bool(company_size_evidence and company_size_evidence.is_evidenced_small_startup)
        if leadership:
            contacts.extend((ContactType.HIRING_MANAGER, ContactType.ENGINEERING_MANAGER, ContactType.RECRUITER))
            if small:
                contacts.append(ContactType.FOUNDER)
            reasons.append("The title signals an engineering leadership role; a hiring or engineering manager may clarify scope.")
        elif small:
            contacts.extend((ContactType.FOUNDER, ContactType.ENGINEERING_MANAGER, ContactType.ENGINEER, ContactType.RECRUITER))
            reasons.append(
                "Sourced small-company size evidence: a founder or engineering lead reads their own inbox and decides directly."
            )
        else:
            # Size unknown or larger: the recruiter owns the process and answers; engineers are a second touch.
            contacts.extend((ContactType.RECRUITER, ContactType.HIRING_MANAGER, ContactType.ENGINEERING_MANAGER))
            reasons.append(
                "Company size is not evidenced as small; the recruiter owns the process, then the hiring or engineering manager."
            )
    else:
        contacts.extend((ContactType.RECRUITER, ContactType.HIRING_MANAGER, ContactType.OTHER))
        reasons.append("The title does not identify a specific function; recruiter and role owner are broad starting points.")

    # Keep first occurrence and preserve this role-specific order.
    unique = tuple(dict.fromkeys(contacts))
    return ContactStrategy(preferred_contact_types=unique, reasons=tuple(reasons))
