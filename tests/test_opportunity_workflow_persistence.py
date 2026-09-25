from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import configure_mappers

from ai_job_hunter.db.base import Base
from ai_job_hunter.domain.normalized_job import NormalizedJob
from ai_job_hunter.models import (
    Application,
    ApplicationEvent,
    ApplicationStatus,
    EvaluationStatus,
    HumanReviewStatus,
    Job,
    JobEvaluation,
    JobReview,
    JobSource,
)
from ai_job_hunter.services.ingestion import IngestionStatus, ingest_job


def _offer(**overrides: object) -> NormalizedJob:
    values: dict[str, object] = {
        "provider": "greenhouse",
        "external_id": "role-101",
        "source_url": "https://boards.greenhouse.io/acme/jobs/101",
        "canonical_url": "https://boards.greenhouse.io/acme/jobs/101",
        "title": "Backend Engineer",
        "company_name": "Acme",
        "company_website": "https://acme.example.test",
        "description": "Build and maintain backend services.",
        "location": "Madrid, Spain",
    }
    values.update(overrides)
    return NormalizedJob.model_validate(values)


def test_workflow_models_register_relationships_and_constraints(db_session) -> None:
    configure_mappers()

    assert {
        "applications",
        "application_events",
        "job_evaluations",
        "job_reviews",
    } <= set(Base.metadata.tables)
    assert Application.job.property.mapper.class_ is Job
    assert Application.events.property.mapper.class_ is ApplicationEvent
    assert ApplicationEvent.application.property.mapper.class_ is Application
    assert JobReview.job.property.mapper.class_ is Job
    assert JobEvaluation.job.property.mapper.class_ is Job

    job = Job(title="Backend Engineer")
    db_session.add(job)
    db_session.flush()

    review = JobReview(job=job)
    application = Application(job=job)
    db_session.add_all([review, application])
    db_session.flush()

    assert review.state == HumanReviewStatus.NEW.value
    assert application.status == ApplicationStatus.DRAFT.value
    assert db_session.scalar(select(func.count()).select_from(JobReview)) == 1
    assert db_session.scalar(select(func.count()).select_from(Application)) == 1


def test_application_event_history_is_ordered_and_survives_reload(db_session) -> None:
    job = Job(title="Backend Engineer")
    application = Application(job=job, status=ApplicationStatus.INTERVIEW.value)
    db_session.add(application)
    db_session.flush()

    applied_at = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    interview_at = datetime(2026, 9, 12, 9, 30, tzinfo=UTC)
    db_session.add_all(
        [
            ApplicationEvent(
                application=application,
                from_status=ApplicationStatus.APPLIED.value,
                to_status=ApplicationStatus.INTERVIEW.value,
                note="First interview scheduled.",
                occurred_at=interview_at,
            ),
            ApplicationEvent(
                application=application,
                from_status=None,
                to_status=ApplicationStatus.APPLIED.value,
                note="Application submitted.",
                occurred_at=applied_at,
            ),
        ]
    )
    db_session.commit()
    db_session.expire_all()

    loaded = db_session.scalars(select(Application)).one()
    assert loaded.status == ApplicationStatus.INTERVIEW.value
    assert [event.to_status for event in loaded.events] == [
        ApplicationStatus.APPLIED.value,
        ApplicationStatus.INTERVIEW.value,
    ]
    assert [event.note for event in loaded.events] == [
        "Application submitted.",
        "First interview scheduled.",
    ]


@pytest.mark.parametrize(
    ("model_factory", "error_match"),
    [
        (lambda job: JobReview(job=job, state="APPLIED"), "ck_job_reviews_state"),
        (lambda job: Application(job=job, status="SAVED"), "ck_applications_status"),
        (
            lambda job: JobEvaluation(
                job=job,
                evaluation_fingerprint="pending-with-decision",
                status=EvaluationStatus.PENDING.value,
                decision="APPLY",
                rubric_version="rubric-v1",
                policy_version="job_decision_v2",
                engine_name="jev",
                config_fingerprint="config-1",
            ),
            "ck_job_evaluations_completion_fields",
        ),
    ],
)
def test_workflow_models_reject_invalid_states(db_session, model_factory, error_match: str) -> None:
    job = Job(title="Backend Engineer")
    db_session.add(job)
    db_session.flush()
    db_session.add(model_factory(job))

    with pytest.raises(IntegrityError, match=error_match):
        db_session.commit()
    db_session.rollback()


def test_evaluations_allow_fingerprint_history_but_reject_duplicate_fingerprint(db_session) -> None:
    job = Job(title="Backend Engineer")
    db_session.add(job)
    db_session.flush()

    old_evaluation = JobEvaluation(
        job=job,
        evaluation_fingerprint="fingerprint-old",
        status=EvaluationStatus.EVALUATED.value,
        decision="REVIEW",
        rubric_version="rubric-v1",
        policy_version="job_decision_v2",
        engine_name="jev",
        config_fingerprint="config-1",
        deterministic_result={"decision": "PASS"},
        jev_signals={"role_relevance": 0.8},
        evaluated_at=datetime(2026, 9, 1, tzinfo=UTC),
    )
    pending_evaluation = JobEvaluation(
        job=job,
        evaluation_fingerprint="fingerprint-new",
        status=EvaluationStatus.PENDING.value,
        rubric_version="rubric-v2",
        policy_version="job_decision_v2",
        engine_name="jev",
        config_fingerprint="config-2",
    )
    db_session.add_all([old_evaluation, pending_evaluation])
    db_session.commit()

    assert db_session.scalar(select(func.count()).select_from(JobEvaluation)) == 2
    assert pending_evaluation.status == EvaluationStatus.PENDING.value
    assert pending_evaluation.decision is None

    db_session.add(
        JobEvaluation(
            job=job,
            evaluation_fingerprint="fingerprint-old",
            status=EvaluationStatus.PENDING.value,
            rubric_version="rubric-v1",
            policy_version="job_decision_v2",
            engine_name="jev",
            config_fingerprint="config-1",
        )
    )
    with pytest.raises(IntegrityError, match="UNIQUE constraint failed"):
        db_session.commit()
    db_session.rollback()


def test_same_source_refresh_updates_source_snapshot_and_preserves_human_state(db_session) -> None:
    initial = _offer()
    created = ingest_job(db_session, initial)
    assert created.status is IngestionStatus.CREATED

    job = db_session.get(Job, created.job_id)
    assert job is not None
    review = JobReview(job=job, state=HumanReviewStatus.SAVED.value)
    application = Application(
        job=job,
        status=ApplicationStatus.APPLIED.value,
        applied_at=datetime(2026, 9, 10, tzinfo=UTC),
        source="company careers page",
        notes="Referred by a former teammate.",
        application_url="https://acme.example.test/applications/role-101",
        cv_version="backend-2026-09",
    )
    evaluated = JobEvaluation(
        job=job,
        evaluation_fingerprint="initial-fingerprint",
        status=EvaluationStatus.EVALUATED.value,
        decision="APPLY",
        rubric_version="rubric-v1",
        policy_version="job_decision_v2",
        engine_name="jev",
        config_fingerprint="candidate-config-1",
        deterministic_result={"decision": "PASS"},
        jev_signals={"role_relevance": 0.9},
        evaluated_at=datetime(2026, 9, 10, tzinfo=UTC),
    )
    event = ApplicationEvent(
        application=application,
        from_status=None,
        to_status=ApplicationStatus.APPLIED.value,
        note="Submitted manually.",
        occurred_at=datetime(2026, 9, 10, tzinfo=UTC),
    )
    db_session.add_all([review, application, evaluated, event])
    db_session.commit()

    updated = _offer(
        title="Senior Backend Engineer",
        description="Lead and maintain distributed backend services.",
        location="Barcelona, Spain",
        raw_metadata={"team": "Core Platform", "updated": True},
    )
    refreshed = ingest_job(db_session, updated)
    assert refreshed.status is IngestionStatus.ALREADY_KNOWN
    assert refreshed.refreshed is True
    refreshed_again = ingest_job(db_session, updated)
    assert refreshed_again.status is IngestionStatus.ALREADY_KNOWN
    assert refreshed_again.job_id == created.job_id
    assert refreshed_again.job_source_id == refreshed.job_source_id
    db_session.expire_all()

    source = db_session.scalars(select(JobSource)).one()
    persisted_job = db_session.get(Job, created.job_id)
    persisted_review = db_session.scalars(select(JobReview)).one()
    persisted_application = db_session.scalars(select(Application)).one()
    persisted_evaluation = db_session.scalars(select(JobEvaluation)).one()

    assert source.source_title == "Senior Backend Engineer"
    assert source.source_description == "Lead and maintain distributed backend services."
    assert source.source_location == "Barcelona, Spain"
    assert source.raw_metadata == {"team": "Core Platform", "updated": True}
    assert persisted_job is not None
    assert persisted_job.id == created.job_id
    assert persisted_review.state == HumanReviewStatus.SAVED.value
    assert persisted_application.status == ApplicationStatus.APPLIED.value
    assert persisted_application.applied_at is not None
    assert persisted_application.applied_at.replace(tzinfo=UTC) == datetime(2026, 9, 10, tzinfo=UTC)
    assert persisted_application.source == "company careers page"
    assert persisted_application.notes == "Referred by a former teammate."
    assert persisted_application.application_url == "https://acme.example.test/applications/role-101"
    assert persisted_application.cv_version == "backend-2026-09"
    assert [item.note for item in persisted_application.events] == ["Submitted manually."]
    assert persisted_evaluation.evaluation_fingerprint == "initial-fingerprint"
    assert persisted_evaluation.decision == "APPLY"
    assert db_session.scalar(select(func.count()).select_from(Job)) == 1
    assert db_session.scalar(select(func.count()).select_from(JobSource)) == 1


def test_strong_cross_source_duplicate_keeps_review_and_application_on_canonical_job(db_session) -> None:
    original = _offer()
    created = ingest_job(db_session, original)
    job = db_session.get(Job, created.job_id)
    assert job is not None

    review = JobReview(job=job, state=HumanReviewStatus.DISMISSED.value)
    application = Application(job=job, status=ApplicationStatus.WITHDRAWN.value)
    db_session.add_all([review, application])
    db_session.commit()

    second_source = _offer(
        provider="lever",
        external_id="role-101-lever",
        source_url="https://jobs.lever.co/acme/role-101-lever",
        canonical_url=original.canonical_url,
    )
    matched = ingest_job(db_session, second_source)
    db_session.expire_all()

    assert matched.status is IngestionStatus.MATCHED_EXISTING
    assert matched.job_id == created.job_id
    assert db_session.scalar(select(func.count()).select_from(Job)) == 1
    assert db_session.scalar(select(func.count()).select_from(JobSource)) == 2
    assert db_session.scalars(select(JobReview)).one().state == HumanReviewStatus.DISMISSED.value
    assert db_session.scalars(select(Application)).one().status == ApplicationStatus.WITHDRAWN.value


def test_possible_duplicate_does_not_merge_human_state_into_a_new_job(db_session) -> None:
    created = ingest_job(db_session, _offer())
    job = db_session.get(Job, created.job_id)
    assert job is not None
    db_session.add_all(
        [
            JobReview(job=job, state=HumanReviewStatus.SAVED.value),
            Application(job=job, status=ApplicationStatus.APPLIED.value),
        ]
    )
    db_session.commit()

    possible = ingest_job(
        db_session,
        _offer(
            provider="other-board",
            external_id="possibly-same-role",
            canonical_url=None,
            source_url=None,
        ),
    )
    db_session.expire_all()

    assert possible.status is IngestionStatus.POSSIBLE_MATCH
    assert possible.job_id != created.job_id
    assert db_session.scalar(select(func.count()).select_from(Job)) == 2
    assert db_session.scalars(select(JobReview)).one().job_id == created.job_id
    assert db_session.scalars(select(Application)).one().job_id == created.job_id
