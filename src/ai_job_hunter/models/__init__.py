"""Persisted core entities."""

from ai_job_hunter.models.company import Company
from ai_job_hunter.models.company_evidence import CompanyEvidence
from ai_job_hunter.models.application import Application, ApplicationEvent, ApplicationStatus
from ai_job_hunter.models.job import Job
from ai_job_hunter.models.job_evaluation import EvaluationStatus, JobEvaluation
from ai_job_hunter.models.job_review import HumanReviewStatus, JobReview
from ai_job_hunter.models.job_source import JobSource
from ai_job_hunter.models.contact import Contact, ContactType
from ai_job_hunter.models.outreach import (
    Outreach,
    OutreachChannel,
    OutreachEvent,
    OutreachEventType,
    OutreachPurpose,
    OutreachStatus,
)

__all__ = [
    "Application",
    "ApplicationEvent",
    "ApplicationStatus",
    "Company",
    "CompanyEvidence",
    "Contact",
    "ContactType",
    "EvaluationStatus",
    "HumanReviewStatus",
    "Job",
    "JobEvaluation",
    "JobReview",
    "JobSource",
    "Outreach",
    "OutreachChannel",
    "OutreachEvent",
    "OutreachEventType",
    "OutreachPurpose",
    "OutreachStatus",
]
