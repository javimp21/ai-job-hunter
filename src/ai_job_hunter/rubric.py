"""Versioned prompts and score anchors for the job-decision question set."""

from __future__ import annotations

RUBRIC_VERSION = "job_decision_v1"

ROLE_RELEVANCE_QUESTION = (
    "Is this role substantively relevant to a software/backend engineering candidate? "
    "Assess the actual work and domain; penalize sales, customer support, copywriting, "
    "office-assistant, and unrelated duties. Do not treat a shared word such as Engineer "
    "as sufficient."
)
EXPERIENCE_ACCESSIBILITY_QUESTION = (
    "Given approximately this candidate's experience and the job requirements, is this role "
    "realistically accessible enough to justify applying? Requirements of 2 years or 2–3 years "
    "are not automatically hard blockers. Staff, Principal, Engineering Manager, or clearly "
    "senior roles requiring many years are normally inaccessible. Consider the offer's actual "
    "requirements and stated flexibility."
)
BACKEND_RELEVANCE_QUESTION = (
    "How strongly does this role involve backend/software systems work relevant to this candidate? "
    "Consider full-stack, platform, generic software-engineer, AI-engineer, and support-engineering-like "
    "titles by the work described, not title keywords alone."
)
STACK_TRANSFERABILITY_QUESTION = (
    "Can the candidate's current backend foundation plausibly transfer to this job's core technology "
    "stack? Treat Java/Spring as a possible foundation for adjacent backend stacks such as Kotlin, "
    "Scala, Go, Python, Node.js, and cloud/backend work when the responsibilities support that transfer; "
    "do not imply transfer to a substantially different discipline."
)
REQUIREMENTS_FLEXIBILITY_QUESTION = (
    "Do the stated requirements appear flexible enough that the candidate could reasonably apply "
    "despite not matching every listed technology or year requirement? Distinguish strict hard "
    "requirements from wish lists, broad marketplace technology catalogs, and generic mentions."
)
CAREER_VALUE_QUESTION = (
    "How much technical growth value could this role offer this candidate, based only on evidence in "
    "the offer? Consider production ownership, architecture, CI/CD, cloud, testing, backend systems, "
    "distributed systems, deployment, small engineering teams, and meaningful responsibility. If the "
    "offer does not provide enough information, reflect that uncertainty through low answer confidence."
)
OBSERVABLE_ROLE_QUALITY_QUESTION = (
    "How strong is the observable quality of this role description and role scope for this candidate? "
    "Use only information present in the offer. Do not use prior knowledge of the company name or infer "
    "company reputation, funding, culture, salary, or other company facts that are not stated. Sparse "
    "or generic information should have low confidence."
)

BACKEND_SCORE_CRITERIA = [
    "No evidence of backend or software-systems work.",
    "Mostly unrelated or peripheral software work.",
    "Some relevant backend/software-systems work, but not central.",
    "Substantial backend/software-systems work is central to the role.",
    "Backend/software systems are the primary responsibility of the role.",
]
CAREER_VALUE_SCORE_CRITERIA = [
    "No concrete evidence of technical growth or responsibility in the offer.",
    "Limited technical growth; responsibilities are narrow or mostly routine.",
    "Some relevant technical learning or ownership is described.",
    "Strong evidence of production ownership, engineering practices, or meaningful backend work.",
    "Strong evidence across several growth areas such as architecture, cloud, testing, deployment, or distributed systems.",
]
ROLE_QUALITY_SCORE_CRITERIA = [
    "The offer gives almost no concrete information about the role or its work.",
    "The offer is mostly generic and gives little evidence about responsibilities or expectations.",
    "The offer gives some concrete role details, but important scope or requirements remain unclear.",
    "The offer clearly describes relevant responsibilities and reasonable expectations.",
    "The offer gives unusually clear, specific evidence about relevant responsibilities, scope, and expectations.",
]

RUBRIC_SPEC = {
    "version": RUBRIC_VERSION,
    "question_types": {
        "role_relevance": "noul",
        "experience_accessibility": "noul",
        "backend_relevance": "score",
        "stack_transferability": "noul",
        "requirements_flexibility": "noul",
        "career_value": "score",
        "observable_role_quality": "score",
    },
    "questions": {
        "role_relevance": ROLE_RELEVANCE_QUESTION,
        "experience_accessibility": EXPERIENCE_ACCESSIBILITY_QUESTION,
        "backend_relevance": BACKEND_RELEVANCE_QUESTION,
        "stack_transferability": STACK_TRANSFERABILITY_QUESTION,
        "requirements_flexibility": REQUIREMENTS_FLEXIBILITY_QUESTION,
        "career_value": CAREER_VALUE_QUESTION,
        "observable_role_quality": OBSERVABLE_ROLE_QUALITY_QUESTION,
    },
    "score_criteria": {
        "backend_relevance": BACKEND_SCORE_CRITERIA,
        "career_value": CAREER_VALUE_SCORE_CRITERIA,
        "observable_role_quality": ROLE_QUALITY_SCORE_CRITERIA,
    },
}
