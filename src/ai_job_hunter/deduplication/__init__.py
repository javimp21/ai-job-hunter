"""Deterministic, conservative job identity matching."""

from ai_job_hunter.deduplication.matcher import (
    DeduplicationDecision,
    DeduplicationResult,
    DeduplicationSignals,
    match_job,
)
from ai_job_hunter.deduplication.normalization import (
    NormalizedTitle,
    extract_company_domain,
    normalize_company_name,
    normalize_job_title,
    normalize_job_url,
    normalize_location,
)

__all__ = [
    "DeduplicationDecision",
    "DeduplicationResult",
    "DeduplicationSignals",
    "NormalizedTitle",
    "extract_company_domain",
    "match_job",
    "normalize_company_name",
    "normalize_job_title",
    "normalize_job_url",
    "normalize_location",
]
