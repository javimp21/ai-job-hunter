"""How useful a person is as a cold-outreach target for a junior backend candidate.

The candidate wants engineering leaders and engineers (and tech recruiters), not
the executive team of a large company. A stated role is assessed from its own
words only; nothing is inferred. Non-engineering C-level people are relevant
only for companies known (from evidence, not hints) to have at most 50 people.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from ai_job_hunter.models.contact import ContactType

SMALL_COMPANY_MAX_EMPLOYEES = 50
MAX_ROLE_CHARS = 80
MAX_ROLE_WORDS = 10


class RoleKind(StrEnum):
    ENGINEERING_C = "ENGINEERING_C"  # CTO, VP Engineering
    ENGINEERING_HEAD = "ENGINEERING_HEAD"  # Head/Director of Engineering
    ENGINEERING_MANAGER = "ENGINEERING_MANAGER"
    TECH_LEAD = "TECH_LEAD"
    SENIOR_ENGINEER = "SENIOR_ENGINEER"  # Staff / Principal / Senior
    ENGINEER = "ENGINEER"
    RECRUITER = "RECRUITER"  # Talent / tech recruiter
    NON_ENGINEERING_C = "NON_ENGINEERING_C"  # CEO, CFO, COO, CRO, founder, president...


@dataclass(frozen=True, slots=True)
class RoleAssessment:
    kind: RoleKind
    contact_type: ContactType
    label: str

    @property
    def is_non_engineering_c_level(self) -> bool:
        return self.kind is RoleKind.NON_ENGINEERING_C


_PATTERNS: tuple[tuple[RoleKind, re.Pattern[str]], ...] = (
    (
        RoleKind.ENGINEERING_C,
        re.compile(
            r"\bcto\b|\bchief (?:technology|technical) officer\b|\bvp\b.{0,12}\b(?:engineering|technology)\b"
            r"|\bvice president\b.{0,12}\b(?:engineering|technology)\b|\bdirector (?:t[eé]cnico|de tecnolog[ií]a)\b",
            re.IGNORECASE,
        ),
    ),
    (
        RoleKind.ENGINEERING_HEAD,
        re.compile(
            r"\bhead of (?:engineering|technology|tech|platform|software|backend|development|infrastructure|data engineering)\b"
            r"|\bdirector\b.{0,6}\b(?:engineering|software|platform|technology)\b|\bengineering director\b"
            r"|\bresponsable de (?:ingenier[ií]a|tecnolog[ií]a|desarrollo)\b|\bjefe de (?:ingenier[ií]a|desarrollo)\b",
            re.IGNORECASE,
        ),
    ),
    (
        RoleKind.ENGINEERING_MANAGER,
        re.compile(
            r"\bengineering manager\b|\bmanager,? engineering\b|\bsoftware (?:development |engineering )?manager\b"
            r"|\bdevelopment manager\b|\bmanager de (?:ingenier[ií]a|desarrollo)\b|\bgerente de ingenier[ií]a\b",
            re.IGNORECASE,
        ),
    ),
    (
        RoleKind.TECH_LEAD,
        re.compile(
            r"\btech(?:nical)? lead\b|\bengineering lead\b|\bteam lead\b.{0,15}\b(?:engineer|developer)\b"
            r"|\blead (?:software |backend |back-end |platform |data )?(?:engineer|developer)\b|\bl[ií]der t[eé]cnico\b",
            re.IGNORECASE,
        ),
    ),
    (
        RoleKind.SENIOR_ENGINEER,
        re.compile(
            r"\b(?:staff|principal|senior|sr\.?)\b.{0,25}\b(?:engineer|developer|architect|sre)\b"
            r"|\b(?:engineer|developer)\b.{0,12}\b(?:staff|principal|senior)\b",
            re.IGNORECASE,
        ),
    ),
    (
        RoleKind.ENGINEER,
        re.compile(
            r"\bengineer\b|\bdeveloper\b|\bprogrammer\b|\bsoftware architect\b|\bsre\b|\bdevops\b"
            r"|\bingenier[oa] de\b|\bingenier[oa]\b.{0,12}\bsoftware\b|\bdesarrollador[a]?\b",
            re.IGNORECASE,
        ),
    ),
    (
        RoleKind.RECRUITER,
        re.compile(
            r"\brecruit|\btalent (?:acquisition|partner|sourcer|specialist)\b|\bsourcer\b|\bselecci[oó]n de talento\b",
            re.IGNORECASE,
        ),
    ),
    (
        RoleKind.NON_ENGINEERING_C,
        re.compile(
            r"\bc[efmopri]o\b|\bciso\b|\bchief\b.{0,40}\bofficer\b|\bfounder\b|\bco-?founder\b|\bpresident\b"
            r"|\bmanaging (?:director|partner)\b|\bgeneral manager\b|\bfundador[a]?\b|\bdirector[a]? general\b",
            re.IGNORECASE,
        ),
    ),
)
_ENGINEERING_KINDS = frozenset(
    {RoleKind.ENGINEERING_C, RoleKind.ENGINEERING_HEAD, RoleKind.ENGINEERING_MANAGER, RoleKind.TECH_LEAD,
     RoleKind.SENIOR_ENGINEER, RoleKind.ENGINEER}
)
_FOUNDER = re.compile(r"\bfounder\b|\bco-?founder\b|\bfundador[a]?\b|\bceo\b|\bchief executive\b", re.IGNORECASE)
_TALENT = re.compile(r"\btalent\b", re.IGNORECASE)
_NOT_BACKEND = re.compile(
    r"\bmarketing\b|\bsales\b|\bsupport\b|\bcustomer\b|\bsolutions?\b|\bsuccess\b|\bpre-?sales\b|\bfield\b"
    r"|\baccount\b|\badvocate\b|\bdevrel\b|\bdeveloper relations\b|\btechnical writer\b|\bqa\b|\bquality\b"
    r"|\btest(?:er|ing)?\b|\bimplementation\b|\bconsultant\b",
    re.IGNORECASE,
)
_SENTENCE_END = re.compile(r"[.!?]$")

# Score for a junior backend candidate; higher = better target. Technical recruiters come
# first (they own the hiring funnel and answer cold messages), then the managers and leads
# who hire for a team. Directors and CTOs of large companies rarely answer a junior, so they
# rank below engineers; in a company known to be small the CTO is the best contact.
_BASE_SCORES = {
    RoleKind.RECRUITER: 95,
    RoleKind.ENGINEERING_MANAGER: 85,
    RoleKind.TECH_LEAD: 80,
    RoleKind.ENGINEERING_HEAD: 70,
    RoleKind.SENIOR_ENGINEER: 70,
    RoleKind.ENGINEER: 65,
    RoleKind.NON_ENGINEERING_C: 20,
}
_C_LEVEL_SMALL = 100
_C_LEVEL_LARGE_OR_UNKNOWN = 40


def assess_role(role: str | None) -> RoleAssessment | None:
    """The outreach-relevant meaning of a stated role, or None when it is not one we target."""

    if not role:
        return None
    text = " ".join(role.split())
    if not text or len(text) > MAX_ROLE_CHARS or len(text.split()) > MAX_ROLE_WORDS:
        return None
    if len(text.split()) > 6 and _SENTENCE_END.search(text):
        return None  # a sentence, not a title
    for kind, pattern in _PATTERNS:
        if pattern.search(text):
            if kind in _ENGINEERING_KINDS and _NOT_BACKEND.search(text):
                return None  # sales/support/marketing engineers are not who a backend candidate writes to
            return RoleAssessment(kind, _contact_type(kind, text), text)
    return None


def _contact_type(kind: RoleKind, text: str) -> ContactType:
    if kind in {RoleKind.ENGINEERING_C, RoleKind.ENGINEERING_HEAD, RoleKind.ENGINEERING_MANAGER}:
        return ContactType.ENGINEERING_MANAGER
    if kind in {RoleKind.TECH_LEAD, RoleKind.SENIOR_ENGINEER, RoleKind.ENGINEER}:
        return ContactType.ENGINEER
    if kind is RoleKind.RECRUITER:
        return ContactType.TALENT if _TALENT.search(text) else ContactType.RECRUITER
    return ContactType.FOUNDER if _FOUNDER.search(text) else ContactType.OTHER


def role_score(assessment: RoleAssessment, *, small_known: bool) -> int:
    if assessment.kind is RoleKind.ENGINEERING_C:
        return _C_LEVEL_SMALL if small_known else _C_LEVEL_LARGE_OR_UNKNOWN
    return _BASE_SCORES[assessment.kind]


def is_target(assessment: RoleAssessment | None, *, small_known: bool) -> bool:
    """Whether this person may be stored/suggested for a company of the given (evidenced) size."""

    if assessment is None:
        return False
    if assessment.kind is RoleKind.SENIOR_ENGINEER:
        return False  # staff/principal/senior engineers do not hire and rarely answer a junior
    if assessment.kind is RoleKind.ENGINEERING_C:
        return small_known  # a CTO answers only where the company is known to be small
    if assessment.is_non_engineering_c_level:
        return small_known
    return True


def relevance(title: str | None, *, small_known: bool) -> int | None:
    """Score for the title at this company size, or None when the person is not a target."""

    assessment = assess_role(title)
    return role_score(assessment, small_known=small_known) if is_target(assessment, small_known=small_known) else None


_C_ACRONYM = re.compile(r"c[efmoprit]o|ciso", re.IGNORECASE)
_TAIL_SEPARATOR = re.compile(r"\s(?:at|@)\s+|\s*@\s*|,\s+|\s+[-–—|]\s+", re.IGNORECASE)
_EXPLICIT_EMPLOYER = re.compile(r"\bat\b|@", re.IGNORECASE)
_TEAM_LEVEL_KINDS = frozenset(
    {RoleKind.ENGINEERING_HEAD, RoleKind.ENGINEERING_MANAGER, RoleKind.TECH_LEAD, RoleKind.SENIOR_ENGINEER,
     RoleKind.ENGINEER}
)
MAX_TEAM_TAIL_WORDS = 4
_TAIL_FILLER = frozenset(
    {"and", "of", "the", "y", "de", "del", "la", "el", "e", "&", "team", "teams", "engineering", "platform", "data",
     "infrastructure", "backend", "frontend", "core", "security", "product", "cloud", "software", "technology",
     "tech", "development", "services", "payments", "ai", "ml", "mobile", "web", "ingeniería", "equipo"}
)


def role_belongs_to(role: str | None, company_names: Sequence[str]) -> bool:
    """False when the role text says the person works somewhere else.

    "CEO at Ent.Kow", "CFO, Meine Erde" or "Founder & CEO, unwind your mind" (customer
    testimonials on a team-like page) carry a trailing company that is not ours. A tail is
    accepted when it names this company, is itself a role, or is only department words
    ("Senior Engineer, Platform Team").
    """

    if not role:
        return False
    text = " ".join(role.split())
    match = _TAIL_SEPARATOR.search(text)
    if match is None:
        # "CTO RawTree": a C-level acronym followed by one unrelated word names another company.
        words = text.split()
        if len(words) == 2 and _C_ACRONYM.fullmatch(words[0]):
            second = words[1].casefold()
            return second in _TAIL_FILLER or any(
                len(token) >= 3 and token in second
                for name in company_names
                for token in re.split(r"[^\w]+", name.casefold())
            )
        return True
    tail = text[match.end():].strip(" .")
    if not tail:
        return True
    folded = tail.casefold()
    for name in company_names:
        for token in re.split(r"[^\w]+", name.casefold()):
            if len(token) >= 3 and token in folded:
                return True
    if assess_role(tail) is not None:
        return True
    words = [word for word in re.split(r"[^\w&]+", folded) if word]
    if bool(words) and all(word in _TAIL_FILLER for word in words):
        return True
    # "Director of Engineering, Mail" / "Staff Engineer - VPN": after a comma or dash (not
    # "at"/"@"), a short tail following a team-level engineering title is the team or product.
    # Testimonials name executives ("CFO, Meine Erde"), so C-level heads stay strict.
    head = assess_role(text[:match.start()])
    return (
        not _EXPLICIT_EMPLOYER.search(match.group(0))
        and head is not None
        and head.kind in _TEAM_LEVEL_KINDS
        and len(words) <= MAX_TEAM_TAIL_WORDS
    )
