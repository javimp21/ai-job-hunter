"""Everything stored about one person: counted for /my_data and erased for /erase."""

from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from ai_job_hunter.db.user_context import SKIP_USER_SCOPE
from ai_job_hunter.models import (
    Application,
    ApplicationEvent,
    ConnectionRequest,
    JobEvaluation,
    JobFeedbackNote,
    JobReview,
    OpportunityNotification,
    Outreach,
    OutreachEvent,
    ReportDelivery,
)
from ai_job_hunter.models.job_feedback import FeedbackPrompt
from ai_job_hunter.models.usage import GeneratedDocument, UsageEvent
from ai_job_hunter.models.user import User, UserProfile, UserStatus

# (label shown to the person, model) in the order they can be deleted (children before parents).
LABELED_TABLES = (
    ("notas", JobFeedbackNote),
    ("avisos", OpportunityNotification),
    ("evaluaciones", JobEvaluation),
    ("votos", JobReview),
    ("informes", ReportDelivery),
    ("mensajes de contacto", ConnectionRequest),
    ("preguntas del bot", FeedbackPrompt),
    ("documentos", GeneratedDocument),
    ("usos", UsageEvent),
)
_SCOPE = {"execution_options": {SKIP_USER_SCOPE: True}}


def count_user_rows(session: Session, user: User) -> dict[str, int]:
    counts = {
        label: session.scalar(select(func.count()).select_from(model).where(model.user_id == user.id), **_SCOPE) or 0
        for label, model in LABELED_TABLES
    }
    counts["candidaturas"] = session.scalar(
        select(func.count()).select_from(Application).where(Application.user_id == user.id), **_SCOPE
    ) or 0
    counts["borradores"] = session.scalar(
        select(func.count()).select_from(Outreach).where(Outreach.user_id == user.id), **_SCOPE
    ) or 0
    return counts


def erase_user(session: Session, user: User) -> None:
    """Delete the person's data and leave the account as an empty tombstone (no chat, no profile, no consent)."""

    for _label, model in LABELED_TABLES[:1]:
        session.execute(delete(model).where(model.user_id == user.id), **_SCOPE)
    application_ids = list(session.scalars(select(Application.id).where(Application.user_id == user.id), **_SCOPE))
    if application_ids:
        session.execute(delete(ApplicationEvent).where(ApplicationEvent.application_id.in_(application_ids)), **_SCOPE)
    outreach_ids = list(session.scalars(select(Outreach.id).where(Outreach.user_id == user.id), **_SCOPE))
    if outreach_ids:
        session.execute(delete(OutreachEvent).where(OutreachEvent.outreach_id.in_(outreach_ids)), **_SCOPE)
    for _label, model in LABELED_TABLES[1:]:
        session.execute(delete(model).where(model.user_id == user.id), **_SCOPE)
    session.execute(delete(Outreach).where(Outreach.user_id == user.id), **_SCOPE)
    session.execute(delete(Application).where(Application.user_id == user.id), **_SCOPE)
    session.execute(delete(UserProfile).where(UserProfile.user_id == user.id))
    user.status = UserStatus.DELETED.value
    user.telegram_chat_id = None
    user.onboarding = None
    user.consent_at = user.consent_version = user.trial_started_at = user.trial_ends_at = None
    session.flush()
