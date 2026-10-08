"""Persisted core entities."""

from ai_job_hunter.models.company import Company
from ai_job_hunter.models.company_evidence import CompanyEvidence
from ai_job_hunter.models.company_lead import CompanyLead, CompanyLeadStatus
from ai_job_hunter.models.application import Application, ApplicationEvent, ApplicationStatus
from ai_job_hunter.models.job import Job
from ai_job_hunter.models.job_evaluation import EvaluationStatus, JobEvaluation
from ai_job_hunter.models.job_review import HumanReviewStatus, JobReview
from ai_job_hunter.models.job_source import JobSource
from ai_job_hunter.models.monitored_source import MonitoredSource, MonitoredSourceState
from ai_job_hunter.models.connection_request import ConnectionRequest, ConnectionRequestStatus
from ai_job_hunter.models.contact import Contact, ContactType
from ai_job_hunter.models.outreach import (
    Outreach,
    OutreachChannel,
    OutreachEvent,
    OutreachEventType,
    OutreachPurpose,
    OutreachStatus,
)
from ai_job_hunter.models.opportunity_notification import (
    OpportunityNotification,
    OpportunityNotificationStatus,
)
from ai_job_hunter.models.report_delivery import ReportDelivery
from ai_job_hunter.models.user import User, UserProfile, UserStatus

__all__ = [
    "Application",
    "ApplicationEvent",
    "ApplicationStatus",
    "Company",
    "CompanyEvidence",
    "CompanyLead",
    "CompanyLeadStatus",
    "ConnectionRequest",
    "ConnectionRequestStatus",
    "Contact",
    "ContactType",
    "EvaluationStatus",
    "HumanReviewStatus",
    "Job",
    "JobEvaluation",
    "JobReview",
    "JobSource",
    "MonitoredSource",
    "MonitoredSourceState",
    "Outreach",
    "OutreachChannel",
    "OutreachEvent",
    "OutreachEventType",
    "OutreachPurpose",
    "OutreachStatus",
    "OpportunityNotification",
    "OpportunityNotificationStatus",
    "ReportDelivery",
    "User",
    "UserProfile",
    "UserStatus",
]
