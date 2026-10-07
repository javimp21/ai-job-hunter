"""Versioned prompts and score anchors for the job-decision question set.

The wording lives in the sector template (``sectors/templates/<sector>.json``); the names below are the software
template's, which is the only one the engine evaluates with so far.
"""

from __future__ import annotations

from ai_job_hunter.sectors.engine import get_template

_SPEC = get_template("software").template.rubric
assert _SPEC is not None, "the software sector template must define its rubric"
_QUESTIONS = _SPEC.questions
_CRITERIA = _SPEC.score_criteria

RUBRIC_VERSION = _SPEC.version
ROLE_RELEVANCE_QUESTION = _QUESTIONS["role_relevance"]
EXPERIENCE_ACCESSIBILITY_QUESTION = _QUESTIONS["experience_accessibility"]
BACKEND_RELEVANCE_QUESTION = _QUESTIONS["backend_relevance"]
STACK_TRANSFERABILITY_QUESTION = _QUESTIONS["stack_transferability"]
REQUIREMENTS_FLEXIBILITY_QUESTION = _QUESTIONS["requirements_flexibility"]
CAREER_VALUE_QUESTION = _QUESTIONS["career_value"]
OBSERVABLE_ROLE_QUALITY_QUESTION = _QUESTIONS["observable_role_quality"]

BACKEND_SCORE_CRITERIA = _CRITERIA["backend_relevance"]
CAREER_VALUE_SCORE_CRITERIA = _CRITERIA["career_value"]
ROLE_QUALITY_SCORE_CRITERIA = _CRITERIA["observable_role_quality"]

RUBRIC_SPEC = {
    "version": RUBRIC_VERSION,
    "question_types": dict(_SPEC.question_types),
    "questions": dict(_QUESTIONS),
    "score_criteria": {name: list(items) for name, items in _CRITERIA.items()},
}


def rubric_spec_for_sector(sector: str) -> dict:
    """The rubric of a sector template; a template without its own rubric is judged with the software one."""

    spec = get_template(sector).template.rubric
    if spec is None:
        return RUBRIC_SPEC
    return {
        "version": spec.version,
        "question_types": dict(spec.question_types),
        "questions": dict(spec.questions),
        "score_criteria": {name: list(items) for name, items in spec.score_criteria.items()},
    }


def rubric_version_for_sector(sector: str) -> str:
    return rubric_spec_for_sector(sector)["version"]
