from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select

from ai_job_hunter.candidates import CandidateConfig, CandidateProfile
from ai_job_hunter.decision_engine import FinalDecision
from ai_job_hunter.models import (
    Company,
    EvaluationStatus,
    HumanReviewStatus,
    Job,
    JobEvaluation,
    OpportunityNotification,
    OpportunityNotificationStatus,
)
from ai_job_hunter.services import notifications
from ai_job_hunter.services.notifications import (
    NotificationService,
    TelegramAmbiguousError,
    TelegramProvider,
    TelegramRejectedError,
    TelegramSendResult,
    format_notification_message,
    list_notification_history,
    list_pending_notifications,
    preview_notifications,
    retry_failed_notifications,
    send_notifications,
)
from ai_job_hunter.services.opportunities import Opportunity


def _candidate() -> CandidateConfig:
    return CandidateConfig(profile=CandidateProfile())


def _opportunity(
    job_id,
    decision: FinalDecision | None,
    priority: int | None,
    *,
    stale: bool = False,
    fingerprint: str = "snapshot-1",
    company: str = "Example Co",
    title: str = "Backend Engineer",
) -> Opportunity:
    return Opportunity(
        job_id=job_id,
        title=title,
        company=company,
        location="Remote — Spain",
        remote_policy="REMOTE",
        employment_type="FULL_TIME",
        url="https://jobs.example.test/role?email=candidate@example.test#apply",
        technologies=("Python", "PostgreSQL"),
        required_technologies=("Python",),
        salary_min="60000",
        salary_max="80000",
        currency="EUR",
        salary_period="YEAR",
        published_at=None,
        decision=decision,
        evaluation_status=EvaluationStatus.EVALUATED,
        evaluation_is_stale=stale,
        review_state=HumanReviewStatus.DISMISSED,
        application_status=None,
        priority=priority,
        deterministic_result={},
        jev_signals={},
        jev_reasons={
            "reasons": ["raw Jev text must not be sent"],
            "review_reasons": [
                {"code": "ROLE_FAMILY_UNCERTAIN", "message": "raw reason with candidate@example.test"},
                {"code": "STACK_UNCERTAIN", "message": "another raw provider explanation"},
            ],
        },
        evaluation_fingerprint=fingerprint,
    )


def _seed_evaluation(session, decision: str = "APPLY", *, fingerprint: str = "snapshot-1"):
    company = Company(name="Example Co", website_url="https://example.test")
    session.add(company)
    session.flush()
    job = Job(company_id=company.id, title="Backend Engineer", location="Remote — Spain")
    session.add(job)
    session.flush()
    evaluation = JobEvaluation(
        job_id=job.id,
        evaluation_fingerprint=fingerprint,
        status=EvaluationStatus.EVALUATED.value,
        decision=decision,
        rubric_version="test-rubric",
        policy_version="test-policy",
        engine_name="fake",
        engine_configuration=None,
        model_version="fake-v1",
        config_fingerprint="candidate-config-1",
        deterministic_result={},
        jev_signals={},
        jev_reasons={
            "review_reasons": [
                {"code": "ROLE_FAMILY_UNCERTAIN", "message": "raw provider text"}
            ]
        },
        evaluated_at=datetime.now(UTC),
    )
    session.add(evaluation)
    session.commit()
    return job, evaluation


def _install_opportunities(monkeypatch, items):
    def fake_list(session, candidate, **kwargs):
        assert kwargs["include_dismissed"] is True
        return items

    monkeypatch.setattr(notifications, "list_opportunities", fake_list)


class FakeProvider:
    def __init__(self):
        self.messages = []

    def send_message(self, message: str) -> TelegramSendResult:
        self.messages.append(message)
        return TelegramSendResult(message_id="msg-123")


class RejectedProvider:
    def __init__(self):
        self.calls = 0

    def send_message(self, message: str) -> TelegramSendResult:
        self.calls += 1
        raise TelegramRejectedError(429)


class AmbiguousProvider:
    def __init__(self):
        self.calls = 0

    def send_message(self, message: str) -> TelegramSendResult:
        self.calls += 1
        raise RuntimeError("timeout: bot-token-secret-value")


def test_preview_policy_is_read_only_and_includes_dismissed_rows(db_session, monkeypatch):
    rows = []
    for decision, priority in (
        (FinalDecision.APPLY, 42),
        (FinalDecision.REVIEW, 70),
        (FinalDecision.REVIEW, 69),
        (FinalDecision.SKIP, 99),
        (None, None),
    ):
        job, evaluation = _seed_evaluation(
            db_session,
            decision.value if decision else "REVIEW",
            fingerprint=f"fingerprint-{len(rows)}",
        )
        rows.append(
            _opportunity(
                job.id,
                decision,
                priority,
                fingerprint=evaluation.evaluation_fingerprint,
            )
        )
    rows[-1] = _opportunity(rows[-1].job_id, None, None)
    _install_opportunities(monkeypatch, rows)

    preview = preview_notifications(db_session, _candidate(), review_threshold=70)

    assert [(item.decision, item.priority) for item in preview] == [("REVIEW", 70), ("APPLY", 42)]
    assert db_session.scalar(select(func.count()).select_from(OpportunityNotification)) == 0
    assert "candidate@example.test" not in " ".join(item.message for item in preview)


def test_send_is_idempotent_and_uses_evaluation_configuration_identity(db_session, monkeypatch):
    job, evaluation = _seed_evaluation(db_session)
    _install_opportunities(monkeypatch, [_opportunity(job.id, FinalDecision.APPLY, 81)])
    provider = FakeProvider()

    first = send_notifications(db_session, _candidate(), provider)
    assert preview_notifications(db_session, _candidate()) == []
    second = send_notifications(db_session, _candidate(), provider)

    assert (first.created, first.sent) == (1, 1)
    assert (second.created, second.sent, second.reused) == (0, 0, 1)
    assert len(provider.messages) == 1
    row = db_session.scalar(select(OpportunityNotification))
    assert row.status == OpportunityNotificationStatus.SENT.value
    assert row.provider_message_id == "msg-123"

    evaluation.config_fingerprint = "candidate-config-2"
    db_session.commit()
    third = send_notifications(db_session, _candidate(), provider)
    assert (third.created, third.sent) == (1, 1)
    assert len(provider.messages) == 2
    assert db_session.scalar(select(func.count()).select_from(OpportunityNotification)) == 2


def test_low_review_is_suppressed_then_reactivated_when_threshold_changes(db_session, monkeypatch):
    job, _ = _seed_evaluation(db_session, decision="REVIEW")
    _install_opportunities(monkeypatch, [_opportunity(job.id, FinalDecision.REVIEW, 69)])
    provider = FakeProvider()

    suppressed = send_notifications(db_session, _candidate(), provider, review_threshold=70)
    assert suppressed.suppressed == 1
    assert provider.messages == []
    row = db_session.scalar(select(OpportunityNotification))
    assert row.status == OpportunityNotificationStatus.SUPPRESSED.value

    eligible = send_notifications(db_session, _candidate(), provider, review_threshold=69)
    assert eligible.sent == 1
    assert row.status == OpportunityNotificationStatus.SENT.value


def test_ambiguous_failure_is_not_retried_but_definite_rejection_is(db_session, monkeypatch):
    job, _ = _seed_evaluation(db_session)
    _install_opportunities(monkeypatch, [_opportunity(job.id, FinalDecision.APPLY, 81)])
    ambiguous = AmbiguousProvider()
    failed = send_notifications(db_session, _candidate(), ambiguous)
    row = db_session.scalar(select(OpportunityNotification))
    assert failed.failed == 1
    assert row.retryable is False
    assert "bot-token-secret-value" not in str(row.failure_reason)
    assert retry_failed_notifications(db_session, _candidate(), FakeProvider()).sent == 0
    assert ambiguous.calls == 1

    job2, _ = _seed_evaluation(db_session, fingerprint="snapshot-2")
    _install_opportunities(monkeypatch, [_opportunity(job2.id, FinalDecision.APPLY, 81, fingerprint="snapshot-2")])
    rejected = RejectedProvider()
    first = send_notifications(db_session, _candidate(), rejected)
    row2 = db_session.scalar(
        select(OpportunityNotification).where(OpportunityNotification.job_id == job2.id)
    )
    assert first.failed == 1
    assert row2.retryable is True
    retried = retry_failed_notifications(db_session, _candidate(), FakeProvider())
    assert retried.sent == 1
    assert row2.status == OpportunityNotificationStatus.SENT.value
    assert row2.attempt_count == 2


def test_dispatch_claim_is_not_resent_after_interrupted_attempt(db_session, monkeypatch):
    job, evaluation = _seed_evaluation(db_session)
    _install_opportunities(monkeypatch, [_opportunity(job.id, FinalDecision.APPLY, 81)])
    service = NotificationService(db_session, FakeProvider(), _candidate())
    row = OpportunityNotification(
        job_id=job.id,
        evaluation_fingerprint=notifications._notification_fingerprint(evaluation),
        channel="TELEGRAM",
        decision="APPLY",
        status="PENDING",
        message="safe message",
        attempt_count=1,
        dispatch_started=True,
        dispatch_started_at=datetime.now(UTC) - timedelta(minutes=3),
    )
    db_session.add(row)
    db_session.commit()

    service.send_pending()

    db_session.refresh(row)
    assert row.status == OpportunityNotificationStatus.FAILED.value
    assert row.failure_reason == "delivery_outcome_unknown_after_interruption"
    assert row.retryable is False
    assert service.provider.messages == []


def test_interrupted_retry_remains_visible_and_resumable(db_session, monkeypatch):
    job, _ = _seed_evaluation(db_session)
    _install_opportunities(monkeypatch, [_opportunity(job.id, FinalDecision.APPLY, 81)])

    rejected = RejectedProvider()
    first = send_notifications(db_session, _candidate(), rejected)
    assert first.failed == 1
    row = db_session.scalar(select(OpportunityNotification))
    assert row.status == OpportunityNotificationStatus.FAILED.value
    assert row.retryable is True

    dispatch = notifications._dispatch_pending

    def simulate_interruption(*_args, **_kwargs):
        raise RuntimeError("simulated interruption before dispatch")

    monkeypatch.setattr(notifications, "_dispatch_pending", simulate_interruption)
    with pytest.raises(RuntimeError):
        retry_failed_notifications(db_session, _candidate(), FakeProvider())

    db_session.refresh(row)
    assert row.status == OpportunityNotificationStatus.PENDING.value
    assert row.retryable is True
    assert row.attempt_count == 1
    assert list_pending_notifications(db_session) == [row]

    monkeypatch.setattr(notifications, "_dispatch_pending", dispatch)
    assert len(preview_notifications(db_session, _candidate())) == 1
    resumed = retry_failed_notifications(db_session, _candidate(), FakeProvider())
    db_session.refresh(row)
    assert resumed.sent == 1
    assert row.status == OpportunityNotificationStatus.SENT.value
    assert row.attempt_count == 2


def test_formatter_is_bounded_safe_and_includes_role_details():
    job_id = uuid4()
    item = _opportunity(job_id, FinalDecision.REVIEW, 79)

    message = format_notification_message(item)

    assert message.startswith("👀 REVIEW")
    assert "Remote — Spain" in message
    assert "Work mode: REMOTE" in message
    assert "Salary: 60000–80000 EUR per year" in message
    assert "Technologies: Python, PostgreSQL" in message
    assert "Priority: 79/100 (ranking score, not probability)" in message
    assert "candidate@example.test" not in message
    assert "raw Jev" not in message
    assert "candidate@example.test" not in message.split("Open: ")[-1]
    assert "?email=" not in message
    assert "#apply" not in message
    assert "Role and backend fit need review" in message
    apply_message = format_notification_message(
        _opportunity(job_id, FinalDecision.APPLY, 81)
    )
    assert apply_message.startswith("🔥 APPLY")
    assert len(message) <= 3500


def test_telegram_provider_returns_message_id_and_redacts_provider_errors():
    token = "telegram-secret-token"
    seen = {}

    def success(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = request.read().decode()
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 987}})

    provider = TelegramProvider(token, "chat-private", client=httpx.Client(transport=httpx.MockTransport(success)))
    result = provider.send_message("safe test")
    assert result == TelegramSendResult(message_id="987")
    assert token in seen["url"]
    assert "safe+test" in seen["body"] or "safe test" in seen["body"]

    def rejection(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"ok": False, "error_code": 400, "description": f"failed with {token}"},
        )

    rejected = TelegramProvider(token, "chat-private", client=httpx.Client(transport=httpx.MockTransport(rejection)))
    with pytest.raises(TelegramRejectedError) as error:
        rejected.send_message("safe test")
    assert token not in str(error.value)

    def timeout(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(f"request contained {token}")

    ambiguous = TelegramProvider(token, "chat-private", client=httpx.Client(transport=httpx.MockTransport(timeout)))
    with pytest.raises(TelegramAmbiguousError) as error:
        ambiguous.send_message("safe test")
    assert token not in str(error.value)


@pytest.mark.parametrize("decision", [FinalDecision.APPLY, FinalDecision.REVIEW])
def test_pending_history_and_stale_apply_or_high_priority_review_are_excluded(
    db_session, monkeypatch, decision
):
    job, _ = _seed_evaluation(db_session)
    _install_opportunities(
        monkeypatch,
        [_opportunity(job.id, decision, 100, stale=True)],
    )
    assert preview_notifications(db_session, _candidate()) == []
    assert list_pending_notifications(db_session) == []
    assert list_notification_history(db_session) == []


def test_notification_threshold_must_be_an_integer_between_zero_and_hundred(db_session):
    with pytest.raises(ValueError):
        preview_notifications(db_session, _candidate(), review_threshold=101)
    with pytest.raises(ValueError):
        preview_notifications(db_session, _candidate(), review_threshold=True)
