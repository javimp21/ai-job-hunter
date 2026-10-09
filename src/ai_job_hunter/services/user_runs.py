"""Evaluation and alerts for each signed-up person (phase 3 of docs/HOSTED_SERVICE_PLAN.md).

The scheduled run reads every source once for the owner. Afterwards this loop gives each other active person their own
pass over the offers already stored: the deterministic filter with their profile, Jev with a small per-person budget,
and alerts to their own chat. Nothing is fetched here, so another person costs only the Jev calls of offers that pass
their filter. One person's failure never stops the others.
"""

from __future__ import annotations

import html
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ai_job_hunter.db.user_context import acting_as
from ai_job_hunter.decision_engine import DecisionCache
from ai_job_hunter.models import Job, JobEvaluation, JobSource
from ai_job_hunter.models.job_evaluation import EvaluationStatus
from ai_job_hunter.models.user import User, UserStatus
from ai_job_hunter.services import preference_learning
from ai_job_hunter.services.notifications import (
    NotificationProvider,
    alerts_held,
    effective_review_threshold,
    pending_notification_job_ids,
    send_notifications,
)
from ai_job_hunter.services.opportunities import reevaluate_jobs
from ai_job_hunter.services.users import load_profile

logger = logging.getLogger(__name__)

# Paid, limited feeds kept for the owner: an offer seen only through one of these is never evaluated for other people.
OWNER_ONLY_PROVIDERS = ("fantastic_jobs",)

TRIAL_ENDED_TEXT = (
    "⏳ Tu prueba gratuita ha terminado, así que dejo de mandarte avisos. Tus datos siguen guardados unos días: "
    "/erase los borra ahora y, si quieres seguir, escríbele a quien te invitó."
)


@dataclass(slots=True)
class UserRunResult:
    user_id: object
    candidates: int = 0
    jev_evaluated: int = 0
    sent: int = 0
    failed: int = 0
    trial_ended: bool = False
    error: str | None = None  # an exception type name only: errors here may be near personal data


def run_for_users(
    session_factory: Callable[[], Session],
    provider_for_chat: Callable[[str], NotificationProvider],
    *,
    review_threshold: int,
    max_age_days: int,
    engine=None,  # noqa: ANN001 - a JobDecisionEngine; None builds the real Jev engine
    cache: DecisionCache | None = None,
    direct_postings=None,  # noqa: ANN001
    liveness=None,  # noqa: ANN001
    max_jev_jobs: int = 10,
    daily_jev_cap: int = 150,
    max_notifications: int = 5,
    max_candidates: int = 300,
    review_client=None,  # noqa: ANN001 - a Claude client; None builds the real one
    rescan: bool = False,
    now: datetime | None = None,
) -> list[UserRunResult]:
    moment = now or datetime.now(UTC)
    with session_factory() as session:
        due = session.scalars(
            select(User).where(User.is_owner.is_(False), User.status == UserStatus.ACTIVE.value)
        ).all()
        people = [(user.id, user.telegram_chat_id, user.trial_ends_at) for user in due if user.telegram_chat_id]
    results: list[UserRunResult] = []
    for user_id, chat_id, trial_ends_at in people:
        result = UserRunResult(user_id=user_id)
        results.append(result)
        try:
            if trial_ends_at is not None and _aware(trial_ends_at) <= moment:
                _end_trial(session_factory, user_id, provider_for_chat(chat_id))
                result.trial_ended = True
                continue
            with acting_as(user_id), session_factory() as session:
                _run_one(
                    session, provider_for_chat(chat_id), result,
                    user_id=user_id, moment=moment, review_threshold=review_threshold, max_age_days=max_age_days,
                    engine=engine, cache=cache, direct_postings=direct_postings, liveness=liveness,
                    max_jev_jobs=max_jev_jobs, daily_jev_cap=daily_jev_cap, max_notifications=max_notifications,
                    max_candidates=max_candidates, review_client=review_client, rescan=rescan,
                )
        except Exception as error:  # noqa: BLE001 - one person's failure must not stop the others
            result.error = type(error).__name__
            logger.warning("User run failed for %s: %s", user_id, result.error)
    return results


def _run_one(
    session: Session, provider: NotificationProvider, result: UserRunResult, *, user_id, moment, review_threshold,
    max_age_days, engine, cache, direct_postings, liveness, max_jev_jobs, daily_jev_cap, max_notifications, max_candidates,
    review_client, rescan,
) -> None:
    candidate = load_profile(session, session.get(User, user_id))
    if candidate is None:
        return
    user = session.get(User, user_id)
    held = alerts_held(candidate, now=moment, timezone=user.timezone or "Europe/Madrid")
    if held == "paused_until":
        return  # a pause: nothing is evaluated or sent, and what appears meanwhile is not alerted afterwards
    job_ids = _jobs_to_evaluate(session, moment, max_age_days, max_candidates)
    result.candidates = len(job_ids)
    if job_ids:
        spent = session.scalar(
            select(func.count()).select_from(JobEvaluation).where(
                JobEvaluation.jev_signals.is_not(None), JobEvaluation.created_at >= moment - timedelta(days=1)
            )
        ) or 0
        summary = reevaluate_jobs(
            session, candidate, job_ids, max_jev_jobs=max(0, min(max_jev_jobs, daily_jev_cap - spent)),
            cache=cache, engine=engine,
        )
        result.jev_evaluated = summary.jev_evaluated
    batch = send_notifications(
        session, candidate, provider,
        direct_postings=direct_postings, liveness=liveness,
        only_job_ids=None if rescan else set(job_ids) | pending_notification_job_ids(session),
        review_threshold=effective_review_threshold(candidate, review_threshold),
        max_age_days=max_age_days, limit=max_notifications, owner_features=False, dispatch=held is None,
    )
    result.sent, result.failed = batch.sent, batch.failed
    _adapt_and_announce(session, provider, user, moment, review_client)


def _adapt_and_announce(session: Session, provider: NotificationProvider, user: User, moment, client) -> None:  # noqa: ANN001
    """Turn this person's new opinions into undoable changes and tell them about each one."""

    announcements = preference_learning.adapt(session, user, client=client, now=moment)
    session.commit()
    for announcement in announcements:
        provider.send_message(
            html.escape(announcement.text),
            reply_markup={"inline_keyboard": [[{
                "text": "↩️ Deshacer", "callback_data": f"{preference_learning.UNDO_PREFIX}{announcement.change_id}"
            }]]},
        )


def _jobs_to_evaluate(session: Session, moment: datetime, max_age_days: int, limit: int) -> list:
    """Recent open offers this person has no final evaluation for (newest first); budget-deferred ones are retried."""

    since = moment - timedelta(days=max_age_days)
    recent = select(JobSource.job_id).where(
        JobSource.closed_at.is_(None), JobSource.discovered_at >= since, JobSource.provider.not_in(OWNER_ONLY_PROVIDERS)
    )
    done = select(JobEvaluation.job_id).where(JobEvaluation.status == EvaluationStatus.EVALUATED.value)
    return list(
        session.scalars(
            select(Job.id).where(Job.id.in_(recent), Job.id.not_in(done)).order_by(Job.created_at.desc()).limit(limit)
        )
    )


def _end_trial(session_factory: Callable[[], Session], user_id, provider: NotificationProvider) -> None:
    with session_factory() as session:
        user = session.get(User, user_id)
        user.status = UserStatus.TRIAL_ENDED.value
        session.commit()
    provider.send_message(TRIAL_ENDED_TEXT)


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=UTC)
