"""Deterministic, local outreach planning and draft helpers.

This package prepares drafts only. It has no provider integration or message
delivery capability.
"""

from ai_job_hunter.outreach.drafts import (
    DraftChannel,
    DraftMessage,
    DraftTemplate,
    generate_draft,
)
from ai_job_hunter.outreach.projects import (
    CandidateProject,
    ProjectSelection,
    load_candidate_projects,
    select_relevant_project,
)
from ai_job_hunter.outreach.recommendations import (
    OutreachRecommendation,
    outreach_recommendation_reasons,
    recommend_outreach,
)
from ai_job_hunter.outreach.strategy import (
    CompanySizeEvidence,
    ContactStrategy,
    ContactType,
    recommend_contact_strategy,
)

__all__ = [
    "CandidateProject",
    "CompanySizeEvidence",
    "ContactStrategy",
    "ContactType",
    "DraftChannel",
    "DraftMessage",
    "DraftTemplate",
    "OutreachRecommendation",
    "ProjectSelection",
    "generate_draft",
    "load_candidate_projects",
    "outreach_recommendation_reasons",
    "recommend_contact_strategy",
    "recommend_outreach",
    "select_relevant_project",
]
