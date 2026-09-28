"""Factual, local-only application answer drafts for human review."""

from __future__ import annotations

import re
from typing import Sequence

from ai_job_hunter.application_prep.models import (
    ApplicationAnswerStatus,
    ApplicationQuestion,
    ApplicationQuestionHandling,
    ApplicationQuestionType,
    CandidateWritingStyle,
)
from ai_job_hunter.candidates.profile import CandidateConfig
from ai_job_hunter.domain.normalized_job import SalaryPeriod
from ai_job_hunter.outreach.projects import CandidateProject, select_relevant_project


_LEGAL_OR_WORK_AUTH_RE = re.compile(
    r"\b(?:work authorization|authorized to work|authori[sz]ed to work|permitted to work|"
    r"legally work|right to work|eligible to work|work permit|visa|sponsorship|"
    r"sponsor(?:ed|ship)?|citizenship|immigration status)\b",
    re.I,
)
_SENSITIVE_RE = re.compile(
    r"\b(?:race|ethnicity|gender|sex|sexual orientation|disability|disabled|religion|"
    r"religious|veteran|military|marital status|date of birth|birth date|age|"
    r"criminal record|conviction|background check|national origin)\b",
    re.I,
)
_SALARY_RE = re.compile(
    r"\b(?:salary|compensation|pay range|base pay|remuneration|expected earnings)\b",
    re.I,
)
_SALARY_EXPECTATION_RE = re.compile(
    r"\b(?:expect(?:ed|ation|ations)?|desired|target|minimum|requirement|range|"
    r"looking for|seeking|annual(?:ly)?|per year)\b",
    re.I,
)
_HISTORICAL_SALARY_RE = re.compile(
    r"\b(?:current|previous|past|last|most recent|former)\s+(?:(?:base|annual)\s+)?"
    r"(?:salary|compensation|pay|earnings)\b",
    re.I,
)
_YEARS_RE = re.compile(
    r"\b(?:how many|number of)\b|\byears? (?:of (?:[\w+#./-]+\s+){0,4})?experience\b|\byears? experience\b",
    re.I,
)
_CURRENT_ROLE_RE = re.compile(r"\bcurrent\s+(?:job\s+)?(?:role|position|title)\b", re.I)
_TECH_RE = re.compile(
    r"\b(?:technology|technologies|tech stack|programming languages?|frameworks?|tools?)\b",
    re.I,
)
_YES_NO_RE = re.compile(r"\b(?:do you have|have you|are you|can you|would you|willing to)\b", re.I)
_PERIOD_LABEL = {
    SalaryPeriod.HOUR: "hour",
    SalaryPeriod.DAY: "day",
    SalaryPeriod.WEEK: "week",
    SalaryPeriod.MONTH: "month",
    SalaryPeriod.YEAR: "year",
}


def _contains(text: str, phrase: str) -> bool:
    return re.search(rf"(?<![\w]){re.escape(phrase.strip())}(?![\w])", text, re.I) is not None


def _clean_values(values: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        value = " ".join(value.split())
        key = value.casefold()
        if value and key not in seen:
            result.append(value)
            seen.add(key)
    return tuple(result)


def _is_sensitive_or_legal(question: ApplicationQuestion) -> bool:
    if question.handling in {ApplicationQuestionHandling.LEGAL, ApplicationQuestionHandling.SENSITIVE}:
        return True
    return bool(_LEGAL_OR_WORK_AUTH_RE.search(question.label)) or bool(_SENSITIVE_RE.search(question.label))


def _unanswered(
    question: ApplicationQuestion,
    status: ApplicationAnswerStatus = ApplicationAnswerStatus.NEEDS_USER_INPUT,
) -> ApplicationQuestion:
    return question.model_copy(
        update={
            "answer": None,
            "answer_status": status,
            "answer_evidence": (),
            "human_review_required": True,
        }
    )


def _known_technology_mentions(text: str, configured: Sequence[str]) -> tuple[str, ...]:
    return tuple(skill for skill in _clean_values(configured) if _contains(text, skill))


def _salary_suggestion(candidate: CandidateConfig) -> tuple[str | None, tuple[str, ...]]:
    preferences = candidate.preferences
    amount = preferences.target_salary if preferences.target_salary is not None else preferences.minimum_salary
    if amount is None or preferences.salary_currency is None or preferences.salary_period is None:
        return None, ()
    amount_text = format(amount.normalize(), "f")
    period = _PERIOD_LABEL[preferences.salary_period]
    return (
        f"{amount_text} {preferences.salary_currency} per {period}",
        (
            f"Suggestion uses the candidate's configured {'target_salary' if preferences.target_salary is not None else 'minimum_salary'} preference: {amount_text}.",
            f"Configured salary currency is {preferences.salary_currency} and period is {preferences.salary_period.value}.",
        ),
    )


def _project_for_question(
    question_text: str,
    job_title: str,
    job_description: str,
    candidate: CandidateConfig,
    projects: Sequence[CandidateProject],
) -> CandidateProject | None:
    if not projects:
        return None
    profile = candidate.profile
    candidate_technologies = _clean_values(
        (*profile.primary_skills, *profile.secondary_skills, *profile.technologies)
    )
    job_context = f"{job_title} {job_description} {question_text}"
    relevant_technologies = tuple(
        skill for skill in candidate_technologies if _contains(job_context, skill)
    )
    if relevant_technologies:
        return select_relevant_project(job_title, relevant_technologies, projects).project
    # The selector itself requires explicit role-theme overlap; it returns no
    # project for a weak match.
    return select_relevant_project(job_title, (), projects).project


def _candidate_fact_answer(
    question: ApplicationQuestion,
    *,
    candidate: CandidateConfig,
    job_title: str,
    job_description: str,
    projects: Sequence[CandidateProject],
) -> tuple[str | None, tuple[str, ...]]:
    profile = candidate.profile
    label = question.label
    folded = label.casefold()
    skills = _clean_values((*profile.primary_skills, *profile.secondary_skills, *profile.technologies))

    if _YEARS_RE.search(label) and profile.years_of_experience is not None:
        amount = format(profile.years_of_experience.normalize(), "f")
        skill_mentions = _known_technology_mentions(label, skills)
        if skill_mentions:
            unit = "year" if profile.years_of_experience == 1 else "years"
            evidence = [f"Candidate configuration lists {amount} {unit} of overall experience."]
            if skills:
                evidence.append(f"Candidate configuration lists these skills: {', '.join(skills)}.")
            return (
                f"I have {amount} {unit} of overall experience; my profile does not specify a separate duration for {', '.join(skill_mentions)}.",
                tuple(evidence),
            )
        unit = "year" if profile.years_of_experience == 1 else "years"
        return f"I have {amount} {unit} of experience.", (
            f"Candidate configuration lists {amount} {unit} of experience.",
        )

    if _TECH_RE.search(label) or any(word in folded for word in ("experience with", "proficient in", "skill")):
        mentions = _known_technology_mentions(label, skills)
        if _YES_NO_RE.search(label) and mentions:
            return "Yes", (f"Candidate configuration explicitly lists {', '.join(mentions)}.",)
        if not mentions and (_TECH_RE.search(label) or "technolog" in folded or "skill" in folded):
            mentions = skills
        if mentions:
            return "My configured skills and technologies include " + ", ".join(mentions) + ".", (
                f"Candidate configuration explicitly lists {', '.join(mentions)}.",
            )

    if _CURRENT_ROLE_RE.search(label) and profile.current_role:
        return f"My current role is {profile.current_role}.", (
            f"Candidate configuration lists current role: {profile.current_role}.",
        )

    if any(term in folded for term in ("education", "degree", "qualification")) and profile.education:
        return profile.education, (f"Candidate configuration lists education: {profile.education}.",)

    if any(term in folded for term in ("what languages", "languages do you speak", "spoken languages")) and profile.languages:
        return ", ".join(profile.languages), (
            f"Candidate configuration lists languages: {', '.join(profile.languages)}.",
        )

    if any(term in folded for term in ("where are you based", "current location", "current city", "current country")):
        location = ", ".join(part for part in (profile.current_city, profile.current_country) if part)
        if location:
            return location, (f"Candidate configuration lists location: {location}.",)

    if "relocat" in folded:
        if "relocation_willingness" not in candidate.preferences.model_fields_set:
            return None, ()
        return ("Yes" if candidate.preferences.relocation_willingness else "No"), (
            f"Candidate preference lists relocation_willingness={str(candidate.preferences.relocation_willingness).lower()}.",
        )

    if "willing to learn" in folded:
        mentions = _known_technology_mentions(label, candidate.preferences.willing_to_learn_technologies)
        if mentions:
            return "Yes", (f"Candidate preferences explicitly list willingness to learn {', '.join(mentions)}.",)

    if any(term in folded for term in ("project", "portfolio")):
        project = _project_for_question(label, job_title, job_description, candidate, projects)
        if project is not None:
            project_facts = [f"Candidate project is {project.name}: {project.short_description}."]
            if project.technologies:
                project_facts.append("Configured project technologies: " + ", ".join(project.technologies) + ".")
            if question.normalized_type is ApplicationQuestionType.URL or "url" in folded or "link" in folded:
                return project.url, tuple(project_facts)
            return (
                f"My project {project.name} is {project.short_description.rstrip('.!?')}.",
                tuple(project_facts),
            )

    if "tell us about yourself" in folded or "briefly introduce yourself" in folded:
        parts: list[str] = []
        if profile.current_role:
            parts.append(f"I currently work as {profile.current_role}.")
        if profile.years_of_experience is not None:
            amount = format(profile.years_of_experience.normalize(), "f")
            unit = "year" if profile.years_of_experience == 1 else "years"
            parts.append(f"I have {amount} {unit} of experience.")
        if skills:
            parts.append("My listed skills include " + ", ".join(skills[:6]) + ".")
        if parts:
            evidence = tuple(
                [f"Candidate configuration lists current role: {profile.current_role}."] if profile.current_role else []
            )
            if profile.years_of_experience is not None:
                evidence += (f"Candidate configuration lists {amount} {unit} of experience.",)
            if skills:
                evidence += (f"Candidate configuration lists skills: {', '.join(skills[:6])}.",)
            return " ".join(parts), evidence

    # Motivation, product knowledge, leadership, achievements, and quantified
    # impact require candidate-supplied facts not represented by this profile.
    return None, ()


def draft_answers(
    questions: Sequence[ApplicationQuestion],
    *,
    candidate: CandidateConfig,
    job_title: str,
    job_description: str,
    projects: Sequence[CandidateProject] = (),
    writing_style: CandidateWritingStyle | None = None,
) -> list[ApplicationQuestion]:
    """Return question records with conservative draft answers where supported.

    Every generated answer remains marked for human review. Legal, sensitive,
    work-authorization, and file questions are never answered automatically.
    """

    style = writing_style or CandidateWritingStyle()
    results: list[ApplicationQuestion] = []
    for question in questions:
        # Preserve user-provided content and any existing answer verbatim.
        if question.answer is not None or question.answer_status in {
            ApplicationAnswerStatus.USER_PROVIDED,
            ApplicationAnswerStatus.DRAFTED,
            ApplicationAnswerStatus.REVIEW_REQUIRED,
        }:
            results.append(question)
            continue

        if question.normalized_type is ApplicationQuestionType.FILE or question.handling is ApplicationQuestionHandling.UNSUPPORTED:
            results.append(_unanswered(question, ApplicationAnswerStatus.UNSUPPORTED))
            continue

        if _is_sensitive_or_legal(question):
            results.append(_unanswered(question))
            continue

        label = question.label
        if _SALARY_RE.search(label):
            if _HISTORICAL_SALARY_RE.search(label) or not _SALARY_EXPECTATION_RE.search(label):
                results.append(_unanswered(question))
                continue
            suggestion, evidence = _salary_suggestion(candidate)
            if suggestion is None:
                results.append(_unanswered(question))
                continue
            amount = suggestion.split(" ", 1)[0]
            if question.normalized_type is ApplicationQuestionType.NUMBER:
                answer_value = amount
            elif question.options:
                # Numeric ranges or select values are ambiguous; do not
                # silently map a preference to an offered band.
                results.append(_unanswered(question))
                continue
            else:
                answer_value = suggestion
            results.append(
                question.model_copy(
                    update={
                        "answer": answer_value,
                        "answer_status": ApplicationAnswerStatus.REVIEW_REQUIRED,
                        "answer_evidence": evidence,
                        "human_review_required": True,
                    }
                )
            )
            continue

        answer, evidence = _candidate_fact_answer(
            question,
            candidate=candidate,
            job_title=job_title,
            job_description=job_description,
            projects=projects,
        )
        if answer is None:
            results.append(_unanswered(question))
            continue

        # Keep the authored fact concise according to the optional style cap.
        max_words = style.max_words_short_answer
        words = answer.split()
        if len(words) > max_words:
            answer = " ".join(words[:max_words]).rstrip(" ,;:")
            if not answer.endswith((".", "!", "?")):
                answer += "."
        if question.options:
            option = next((value for value in question.options if value.casefold() == answer.casefold()), None)
            if option is None:
                results.append(_unanswered(question))
                continue
            answer = option
        results.append(
            question.model_copy(
                update={
                    "answer": answer,
                    "answer_status": ApplicationAnswerStatus.DRAFTED,
                    "answer_evidence": evidence,
                    "human_review_required": True,
                }
            )
        )
    return results
