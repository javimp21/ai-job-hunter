"""Conservative candidate-to-requirement fit mapping from configured facts."""

from __future__ import annotations

import re
from typing import Sequence

from ai_job_hunter.application_prep.models import (
    CandidateFit,
    CandidateFitStatus,
    JobApplicationRequirement,
    RequirementCategory,
)
from ai_job_hunter.candidates.experience import (
    ExperienceExpressionKind, ExperienceStrength, extract_experience_requirements,
)
from ai_job_hunter.candidates.profile import CandidateConfig
from ai_job_hunter.candidates.technologies import normalize_technology
from ai_job_hunter.outreach.projects import CandidateProject


# A small vocabulary lets us recognize an explicit job skill even when it is
# absent from the candidate's configured list. Absence still means UNKNOWN;
# only an explicit learn-to preference can turn such a gap into LEARNABLE_GAP.
_KNOWN_SKILLS = (
    "PostgreSQL", "TypeScript", "JavaScript", "Spring Boot", "Kubernetes",
    "FastAPI", "Django", "Flask", "Node.js", "React", "Angular", "Vue",
    "Docker", "MongoDB", "MySQL", "Redis", "Kafka", "GraphQL", "AWS",
    "Azure", "GCP", "Terraform", "Python", "Java", "Kotlin", "Go",
    "Golang", "Rust", "C++", "C#", ".NET", "SQL", "NoSQL", "Linux",
    "Git", "CI/CD", "REST", "REST APIs", "HTML", "CSS", "Scala", "Swift",
)
_ROLE_TERMS = frozenset(
    {"backend", "frontend", "fullstack", "software", "engineer", "developer", "platform", "data", "devops", "api"}
)


def _normal(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold().replace("_", " ")).strip()


def _skill_key(value: str) -> str:
    return normalize_technology(value)


def _contains(text: str, phrase: str) -> bool:
    """Match a phrase as a phrase, including punctuation in tech names."""

    escaped = re.escape(phrase.strip())
    # A tech name containing punctuation (C++, .NET, Node.js) cannot use a
    # conventional word boundary on both sides. Whitespace/punctuation edges
    # are sufficient and avoid matching substrings such as Java in JavaScript.
    return re.search(rf"(?<![\w]){escaped}(?![\w])", text, re.I) is not None


def _explicit_skills(text: str, vocabulary: Sequence[str]) -> list[str]:
    matches: list[tuple[int, int, str]] = []
    for skill in vocabulary:
        flags = 0 if _skill_key(skill) == "go" else re.I
        match = re.search(rf"(?<![\w]){re.escape(skill.strip())}(?![\w])", text, flags)
        if match is not None:
            matches.append((match.start(), match.end(), skill))
    # Avoid counting nested labels such as both REST and REST APIs in the same
    # requirement as two separate capabilities.
    selected: list[tuple[int, int, str]] = []
    for start, end, skill in sorted(matches, key=lambda item: (item[0], -(item[1] - item[0]))):
        if any(start < prior_end and end > prior_start for prior_start, prior_end, _ in selected):
            continue
        selected.append((start, end, skill))
    return [skill for _, _, skill in selected]


def _dedupe(values: Sequence[str]) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = _normal(value)
        if key and key not in seen:
            seen.add(key)
            result.append(value)
    return tuple(result)


def _candidate_fact_evidence(candidate: CandidateConfig) -> tuple[str, ...]:
    profile = candidate.profile
    evidence: list[str] = []
    skills = _dedupe((*profile.primary_skills, *profile.secondary_skills, *profile.technologies))
    for skill in skills:
        evidence.append(f"Candidate configuration lists {skill}.")
    if profile.current_role:
        evidence.append(f"Candidate configuration lists current role: {profile.current_role}.")
    if profile.years_of_experience is not None:
        years = format(profile.years_of_experience.normalize(), "f")
        unit = "year" if profile.years_of_experience == 1 else "years"
        evidence.append(f"Candidate configuration lists {years} {unit} of experience.")
    if profile.education:
        evidence.append(f"Candidate configuration lists education: {profile.education}.")
    return tuple(evidence)


def _project_skill_evidence(
    requirement: str,
    requirement_skills: Sequence[str],
    projects: Sequence[CandidateProject],
) -> tuple[CandidateProject | None, tuple[str, ...]]:
    for project in projects:
        searchable = " ".join((project.name, project.short_description, *project.technologies, *project.tags))
        project_keys = {_skill_key(value) for value in project.technologies}
        matched = [
            skill for skill in requirement_skills
            if _contains(searchable, skill) or _skill_key(skill) in project_keys
        ]
        if matched:
            return project, tuple(
                f"Configured project {project.name} explicitly lists or describes {skill}."
                for skill in matched
            )

    # For non-technology requirements, a project's explicit tags or summary
    # may directly support a role-theme requirement (for example, backend API).
    requirement_terms = [term for term in _ROLE_TERMS if _contains(requirement, term)]
    if requirement_terms:
        for project in projects:
            searchable = " ".join((project.name, project.short_description, *project.tags))
            matched = [term for term in requirement_terms if _contains(searchable, term)]
            if matched:
                return project, (
                    f"Configured project {project.name} explicitly describes {', '.join(matched)} work.",
                )
    return None, ()


def _min_years(requirement: str) -> tuple[float, bool] | None:
    requirements = extract_experience_requirements(requirement)
    # Share range/bound parsing with discovery. An upper bound is not a
    # minimum, and optional/ambiguous clauses cannot establish a hard gap.
    minima = [
        item for item in requirements
        if item.strength is ExperienceStrength.MANDATORY
        and item.kind in {ExperienceExpressionKind.FLOOR, ExperienceExpressionKind.RANGE}
        and item.minimum_years is not None
        and not item.minimum_exclusive
        and (item.maximum_years is None or item.minimum_years <= item.maximum_years)
    ]
    if not minima:
        return None
    minimum = max(item.minimum_years for item in minima)
    return float(minimum), any(item.scope_specific for item in minima)


def map_candidate_fit(
    requirements: Sequence[JobApplicationRequirement],
    candidate: CandidateConfig,
    projects: Sequence[CandidateProject] = (),
) -> list[CandidateFit]:
    """Map requirements to explicit candidate facts without inferring skills.

    A missing skill in the profile is not treated as evidence that the
    candidate lacks it. It remains UNKNOWN unless the candidate explicitly
    listed willingness to learn that technology. MISSING is reserved here for
    a known experience duration that falls below an explicitly stated minimum.
    """

    profile = candidate.profile
    configured_skills = _dedupe(
        (*profile.primary_skills, *profile.secondary_skills, *profile.technologies)
    )
    learnable_skills = tuple(candidate.preferences.willing_to_learn_technologies)
    vocabulary = _dedupe((*_KNOWN_SKILLS, *configured_skills, *learnable_skills))
    candidate_skill_keys = {_skill_key(skill) for skill in configured_skills}
    learnable_keys = {_skill_key(skill) for skill in learnable_skills}
    role = profile.current_role or ""
    # Generic words such as "software", "engineer", and "developer" occur
    # throughout company copy; only specific role families count as evidence.
    specific_role_terms = _ROLE_TERMS - {"software", "engineer", "developer"}
    role_terms = [term for term in specific_role_terms if _contains(role, term)]
    base_evidence = _candidate_fact_evidence(candidate)

    results: list[CandidateFit] = []
    for requirement in requirements:
        text = requirement.text
        required_skills = _explicit_skills(text, vocabulary)
        direct_skills = [
            configured
            for skill in required_skills
            for configured in configured_skills
            if _skill_key(skill) == _skill_key(configured)
        ]
        direct_skills = list({
            _skill_key(skill): skill for skill in direct_skills
        }.values())
        learnable = [
            skill for skill in required_skills
            if _skill_key(skill) in learnable_keys and _skill_key(skill) not in candidate_skill_keys
        ]
        project, project_evidence = _project_skill_evidence(text, required_skills, projects)
        project_skills: list[str] = []
        if project is not None:
            searchable = " ".join((project.name, project.short_description, *project.technologies, *project.tags))
            required_keys = {_skill_key(value) for value in required_skills}
            project_keys = {_skill_key(value) for value in project.technologies}
            project_skills = list({
                _skill_key(skill): skill
                for skill in project.technologies
                if _skill_key(skill) in required_keys
            }.values())
            project_skills.extend(
                skill for skill in required_skills
                if _contains(searchable, skill) and _skill_key(skill) not in project_keys
            )
            project_skills = list({
                _skill_key(skill): skill for skill in project_skills
            }.values())
        supported_skills = _dedupe((*direct_skills, *project_skills))

        year_requirement = _min_years(text) if requirement.category is RequirementCategory.MUST_HAVE else None
        year_minimum, scoped_years = year_requirement if year_requirement is not None else (None, False)
        known_years = float(profile.years_of_experience) if profile.years_of_experience is not None else None
        role_matches = [term for term in role_terms if _contains(text, term)]
        evidence: list[str] = []
        evidence.extend(
            item for item in base_evidence
            if any(_normal(skill) in _normal(item) for skill in direct_skills)
            or (role_matches and item.startswith("Candidate configuration lists current role:"))
            or (year_minimum is not None and item.startswith("Candidate configuration lists ") and " experience." in item)
        )
        evidence.extend(project_evidence)

        status = CandidateFitStatus.UNKNOWN
        candidate_experience: str | None = None
        candidate_project = project.name if project is not None else None
        if year_minimum is not None and known_years is not None:
            years_text = format(profile.years_of_experience.normalize(), "f")
            unit = "year" if profile.years_of_experience == 1 else "years"
            candidate_experience = f"{years_text} {unit} of experience"
            evidence.append(f"Candidate reports {years_text} {unit}; the requirement states at least {year_minimum:g} years.")
            if known_years < year_minimum:
                # Other matching skills can show partial alignment, while the
                # unmet explicit duration remains a clear gap.
                status = CandidateFitStatus.PARTIAL_MATCH if supported_skills or role_matches else CandidateFitStatus.MISSING
            elif scoped_years:
                status = CandidateFitStatus.UNKNOWN
                evidence.append("Configured total career years do not verify the duration in this specific role or technology.")
            else:
                status = CandidateFitStatus.MATCH
        elif required_skills:
            if len(supported_skills) == len(required_skills):
                status = CandidateFitStatus.MATCH
            elif supported_skills:
                status = CandidateFitStatus.PARTIAL_MATCH
            elif learnable and len(learnable) == len(required_skills):
                status = CandidateFitStatus.LEARNABLE_GAP
                evidence.extend(
                    f"Candidate explicitly lists willingness to learn {skill}." for skill in learnable
                )
        elif role_matches:
            status = CandidateFitStatus.MATCH
        elif project_evidence:
            status = CandidateFitStatus.MATCH

        if direct_skills:
            evidence.extend(f"Candidate explicitly lists {skill}." for skill in direct_skills)
        if project_skills:
            evidence.extend(f"Configured project {project.name} supports {skill}." for skill in project_skills)
        if learnable and supported_skills:
            evidence.extend(
                f"Candidate explicitly lists willingness to learn {skill}." for skill in learnable
            )

        results.append(
            CandidateFit(
                requirement_id=requirement.id,
                status=status,
                candidate_skills=tuple(supported_skills),
                candidate_experience=candidate_experience,
                candidate_project=candidate_project,
                job_requirement=text,
                evidence=_dedupe(evidence),
            )
        )
    return results
