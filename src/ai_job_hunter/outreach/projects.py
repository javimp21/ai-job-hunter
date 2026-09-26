"""Optional local portfolio-project configuration and conservative matching."""

from __future__ import annotations

import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator


class CandidateProject(BaseModel):
    """A public candidate project explicitly entered in local configuration."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=160)
    url: str = Field(min_length=1, max_length=2048)
    short_description: str = Field(min_length=1, max_length=500)
    technologies: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()

    @field_validator("url")
    @classmethod
    def validate_public_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme.casefold() not in {"https", "http"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError("url must be an absolute HTTP(S) URL")
        # Query strings and fragments can contain access tokens or private
        # state. They are not needed to reference a public project in a draft.
        host = parsed.hostname.casefold()
        if parsed.port is not None:
            host = f"{host}:{parsed.port}"
        return urlunsplit((parsed.scheme.casefold(), host, parsed.path, "", ""))

    @field_validator("technologies", "tags")
    @classmethod
    def normalize_list(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(value.strip() for value in values)
        if any(not value for value in cleaned):
            raise ValueError("items must not be blank")
        return tuple(dict.fromkeys(cleaned))


class CandidateProjectsConfigError(ValueError):
    """Readable error for malformed local candidate-project configuration."""


def load_candidate_projects(
    path: str | Path | None = None,
) -> list[CandidateProject]:
    """Load local project facts; a missing optional file means no projects."""

    config_path = Path(path) if path is not None else Path.cwd() / "candidate_projects.local.json"
    try:
        raw = config_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except OSError as error:
        raise CandidateProjectsConfigError(
            f"Cannot read candidate projects config '{config_path}': {error}"
        ) from error
    try:
        payload: Any = json.loads(raw)
    except json.JSONDecodeError as error:
        raise CandidateProjectsConfigError(
            f"Candidate projects config '{config_path}' is invalid JSON at line {error.lineno}, "
            f"column {error.colno}: {error.msg}"
        ) from error
    if isinstance(payload, dict):
        payload = payload.get("projects")
    if not isinstance(payload, list):
        raise CandidateProjectsConfigError(
            f"Candidate projects config '{config_path}' must contain a projects array."
        )
    try:
        return [CandidateProject.model_validate(item) for item in payload]
    except ValidationError as error:
        locations = "; ".join(
            f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}"
            for item in error.errors()
        )
        raise CandidateProjectsConfigError(
            f"Invalid candidate project in '{config_path}': {locations}"
        ) from error


class ProjectSelection(BaseModel):
    """A single matching project, or no project if evidence is too weak."""

    model_config = ConfigDict(frozen=True)

    project: CandidateProject | None = None
    reasons: tuple[str, ...] = ()


_CONCEPT_PATTERNS: dict[str, re.Pattern[str]] = {
    "backend": re.compile(r"\b(back[ -]?end|api|apis|server[ -]?side|microservices?)\b", re.I),
    "ai": re.compile(r"\b(ai|ml|machine learning|agents?|llms?|genai)\b", re.I),
    "data": re.compile(r"\b(data|etl|pipelines?|analytics|warehouse)\b", re.I),
    "platform": re.compile(r"\b(platform|infrastructure|developer tooling)\b", re.I),
    "cloud": re.compile(r"\b(cloud|aws|azure|gcp|kubernetes|docker)\b", re.I),
    "security": re.compile(r"\b(security|identity|iam|authentication|authorization)\b", re.I),
    "frontend": re.compile(r"\b(front[ -]?end|react|vue|angular|browser|ui)\b", re.I),
}


def _canonical(value: str) -> str:
    normalized = re.sub(r"\s+", " ", value.casefold().replace("_", " ")).strip()
    aliases = {
        "node.js": "nodejs",
        "node js": "nodejs",
        "back end": "backend",
        "back-end": "backend",
        "apis": "api",
        "llm": "ai",
        "llms": "ai",
        "ml": "ai",
        "machine learning": "ai",
        "genai": "ai",
        "agents": "agent",
        "microservices": "backend",
        "server side": "backend",
        "server-side": "backend",
    }
    return aliases.get(normalized, normalized)


def _concepts(values: tuple[str, ...] | list[str]) -> set[str]:
    joined = " ".join(values)
    found = {concept for concept, pattern in _CONCEPT_PATTERNS.items() if pattern.search(joined)}
    # Preserve explicitly supplied technology labels for exact comparison.
    found.update(_canonical(value) for value in values if value.strip())
    return found


def select_relevant_project(
    job_title: str,
    job_technologies: tuple[str, ...] | list[str],
    projects: tuple[CandidateProject, ...] | list[CandidateProject],
) -> ProjectSelection:
    """Choose at most one project only when explicit role/project terms overlap."""

    if not projects:
        return ProjectSelection(reasons=("No candidate projects are configured.",))

    job_values = (job_title, *job_technologies)
    job_concepts = _concepts(list(job_values))
    job_techs = {_canonical(item) for item in job_technologies if item.strip()}

    ranked: list[tuple[float, int, CandidateProject, tuple[str, ...]]] = []
    for index, project in enumerate(projects):
        project_techs = {_canonical(item) for item in project.technologies}
        tech_overlap = job_techs & project_techs
        project_text = (
            *project.technologies,
            *project.tags,
            project.short_description,
        )
        project_concepts = _concepts(list(project_text))
        concept_overlap = (job_concepts & project_concepts) - tech_overlap
        score = len(tech_overlap) * 3.0 + len(concept_overlap) * 1.5
        if score < 1.5:
            continue
        reasons: list[str] = []
        if tech_overlap:
            reasons.append("Shares configured job technologies: " + ", ".join(sorted(tech_overlap)) + ".")
        if concept_overlap:
            reasons.append("Project tags/description overlap the job's explicit themes: " + ", ".join(sorted(concept_overlap)) + ".")
        ranked.append((score, index, project, tuple(reasons)))

    if not ranked:
        return ProjectSelection(reasons=("No project has enough explicit technology or role-theme overlap.",))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    _, _, selected, reasons = ranked[0]
    return ProjectSelection(project=selected, reasons=reasons)
