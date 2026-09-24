"""Candidate configuration and deterministic offer pre-filtering."""

from ai_job_hunter.candidates.facts import JobFacts
from ai_job_hunter.candidates.prefilter import (
    JobPreFilterResult,
    PreFilterDecision,
    evaluate_job,
)
from ai_job_hunter.candidates.profile import (
    CandidateConfig,
    CandidatePreferences,
    CandidateProfile,
    CandidateConfigError,
    RemotePreference,
    SeniorityLevel,
    load_candidate_config,
)

__all__ = [
    "CandidateConfig",
    "CandidateConfigError",
    "CandidatePreferences",
    "CandidateProfile",
    "JobFacts",
    "JobPreFilterResult",
    "PreFilterDecision",
    "RemotePreference",
    "SeniorityLevel",
    "evaluate_job",
    "load_candidate_config",
]
