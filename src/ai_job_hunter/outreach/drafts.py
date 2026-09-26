"""Template-based outreach drafts; deterministic and without a send pathway."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
import re
from typing import Sequence

from pydantic import BaseModel, ConfigDict

from ai_job_hunter.candidates.profile import CandidateProfile
from ai_job_hunter.outreach.projects import (
    CandidateProject,
    select_relevant_project,
)


class DraftTemplate(StrEnum):
    RECRUITER_INTRO = "RECRUITER_INTRO"
    REFERRAL_REQUEST = "REFERRAL_REQUEST"
    HIRING_MANAGER_INTRO = "HIRING_MANAGER_INTRO"
    ENGINEER_REFERRAL = "ENGINEER_REFERRAL"
    COLD_OUTREACH = "COLD_OUTREACH"


class DraftChannel(StrEnum):
    LINKEDIN = "LINKEDIN"
    EMAIL = "EMAIL"


class DraftMessage(BaseModel):
    """A local draft for human review; this object cannot send messages."""

    model_config = ConfigDict(frozen=True)

    template: DraftTemplate
    channel: DraftChannel
    subject: str | None = None
    body: str
    word_count: int
    project: CandidateProject | None = None


_WORD_RE = re.compile(r"[\w’'-]+", re.UNICODE)


def _word_count(text: str) -> int:
    return len(_WORD_RE.findall(text))


def _clip(value: str | None, limit: int = 64) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(value.split())
    if not cleaned:
        return None
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 1].rstrip() + "…"


def _canonical(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold().replace("_", " ")).strip()


def _experience_text(profile: CandidateProfile | None, job_technologies: Sequence[str]) -> str:
    if profile is None:
        return "I’m exploring this opening based on its published role details."

    facts: list[str] = []
    if role := _clip(profile.current_role, 48):
        facts.append(f"My current role is {role}.")
    if profile.years_of_experience is not None:
        years = _format_decimal(profile.years_of_experience)
        unit = "year" if profile.years_of_experience == 1 else "years"
        facts.append(f"I have {years} {unit} of experience.")
    profile_technologies = {
        _canonical(item): item
        for item in (*profile.technologies, *profile.primary_skills, *profile.secondary_skills)
    }
    overlap = [
        profile_technologies[_canonical(item)]
        for item in job_technologies
        if _canonical(item) in profile_technologies
    ]
    overlap = list(dict.fromkeys(overlap))[:3]
    if overlap:
        facts.append("My listed technologies include " + ", ".join(overlap) + ".")
    if not facts:
        return "I’m exploring this opening based on its published role details."
    return " ".join(facts)


def _format_decimal(value: Decimal) -> str:
    return format(value.normalize(), "f")


def _project_text(project: CandidateProject | None) -> str:
    if project is None:
        return ""
    name = _clip(project.name, 36) or project.name
    description = _clip(project.short_description, 64) or project.short_description
    # The link is configured candidate data; never derive or fabricate one.
    return f"One configured public project is {name}: {description} ({project.url})."


def _greeting(contact_name: str | None) -> str:
    name = _clip(contact_name, 36)
    return f"Hello {name}," if name else "Hello,"


def _opening(
    template: DraftTemplate,
    company: str,
    job_title: str | None,
    contact_name: str | None,
) -> str:
    greeting = _greeting(contact_name)
    if template is DraftTemplate.COLD_OUTREACH:
        return f"{greeting} I’m reaching out to ask whether {company} expects to consider software engineering candidates."
    return f"{greeting} I’m reaching out about the {job_title} opening at {company}."


def _linkedin_body(
    template: DraftTemplate,
    opening: str,
    experience: str,
    project: str,
    company: str,
) -> str:
    if template is DraftTemplate.RECRUITER_INTRO:
        request = (
            "Would you be able to share whether the team is still considering candidates and what the next step is? "
            "Thank you for your time."
        )
    elif template is DraftTemplate.REFERRAL_REQUEST:
        request = (
            f"Could you share how referrals work at {company}, or point me to the public process? "
            "No pressure if you are not the right person. Thank you."
        )
    elif template is DraftTemplate.HIRING_MANAGER_INTRO:
        request = (
            "If your work is connected to this opening, could you share which experience is most important for the team? "
            "I understand if you are not the right contact. Thank you."
        )
    elif template is DraftTemplate.ENGINEER_REFERRAL:
        request = (
            "Could you share which technical areas are central or whether a public referral process exists? "
            "No pressure if you are not connected to the role. Thank you."
        )
    else:
        request = (
            "If a public careers page or a more appropriate contact is available, I would appreciate being pointed there. "
            "If no relevant opening is expected, no reply is needed. Thank you for your time."
        )
    parts = [opening, experience]
    if project:
        parts.append(project)
    parts.append(request)
    return " ".join(parts)


def _email_body(
    template: DraftTemplate,
    opening: str,
    experience: str,
    project: str,
    company: str,
) -> str:
    if template is DraftTemplate.RECRUITER_INTRO:
        purpose = (
            "Could you let me know whether the position is active, which experience the team is prioritizing, "
            "and the appropriate next step in the recruiting process? If another public channel handles this search, "
            "please feel free to point me there. I do not want to assume you are attached to this opening."
        )
    elif template is DraftTemplate.REFERRAL_REQUEST:
        purpose = (
            f"Would you be comfortable sharing how employee referrals work for this opening at {company}, "
            "or directing me to the public application process? I am asking for guidance and do not want to assume "
            "that you know the hiring team. Please feel free to decline if this is not convenient or not your area."
        )
    elif template is DraftTemplate.HIRING_MANAGER_INTRO:
        purpose = (
            "If your role is connected to this search, could you share the most important technical priorities "
            "or experience for the team? I do not want to assume you are the hiring manager for this opening. "
            "If there is a public channel for role questions, I would be glad to use it instead."
        )
    elif template is DraftTemplate.ENGINEER_REFERRAL:
        purpose = (
            "If you have context on the engineering work, could you share which technical areas are central "
            "or whether a public employee-referral process exists? I do not want to assume you are connected "
            "to the hiring decision, so a pointer to the right public channel would also be helpful."
        )
    else:
        purpose = (
            "Could you point me to a public careers page or the appropriate contact for future software roles? "
            "I do not have a specific vacancy to reference and do not want to assume that a suitable position "
            "is currently open. If this is outside your area, no reply is needed."
        )

    closing = (
        "Thank you for considering this. I appreciate your time; no reply is needed if this falls outside your area."
    )
    parts = [opening, experience]
    if project:
        parts.append(project)
    parts.extend((purpose, closing, "Regards,"))
    return "\n\n".join(parts)


def generate_draft(
    template: DraftTemplate | str,
    channel: DraftChannel | str,
    company: str,
    job_title: str | None = None,
    job_technologies: Sequence[str] = (),
    candidate_profile: CandidateProfile | None = None,
    contact_name: str | None = None,
    contact_role: str | None = None,
    candidate_projects: Sequence[CandidateProject] = (),
) -> DraftMessage:
    """Render a deterministic LinkedIn or email draft from supplied facts.

    Contact role is accepted for API compatibility but intentionally not used
    in prose: a role title alone is insufficient evidence that this person is
    attached to a particular vacancy. A project is added only after explicit
    technology/theme matching. This function performs no network or send call.
    """

    selected_template = DraftTemplate(template)
    selected_channel = DraftChannel(channel)
    clean_company = _clip(company, 60)
    if clean_company is None:
        raise ValueError("company is required")
    clean_title = _clip(job_title, 60)
    if selected_template is DraftTemplate.COLD_OUTREACH:
        clean_title = None
    elif clean_title is None:
        raise ValueError("job_title is required for job-specific templates")

    project: CandidateProject | None = None
    if clean_title is not None and candidate_projects:
        project = select_relevant_project(
            clean_title,
            tuple(job_technologies),
            tuple(candidate_projects),
        ).project

    experience = _experience_text(candidate_profile, job_technologies)
    project_sentence = _project_text(project)
    opening = _opening(selected_template, clean_company, clean_title, contact_name)
    if selected_channel is DraftChannel.LINKEDIN:
        body = _linkedin_body(
            selected_template,
            opening,
            experience,
            project_sentence,
            clean_company,
        )
        subject = None
        minimum, maximum = 40, 80
    else:
        body = _email_body(
            selected_template,
            opening,
            experience,
            project_sentence,
            clean_company,
        )
        subject = (
            f"Question about future software roles at {clean_company}"
            if selected_template is DraftTemplate.COLD_OUTREACH
            else f"Question about {clean_title} at {clean_company}"
        )
        minimum, maximum = 80, 130

    words = _word_count(body)
    if not minimum <= words <= maximum:
        raise ValueError(
            f"Rendered {selected_channel.value} draft has {words} words; expected {minimum}-{maximum}."
        )
    return DraftMessage(
        template=selected_template,
        channel=selected_channel,
        subject=subject,
        body=body,
        word_count=words,
        project=project,
    )
