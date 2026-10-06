import dataclasses
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select

from ai_job_hunter.candidates import CandidateConfig, CandidateProfile
from ai_job_hunter.decision_engine import FinalDecision
from ai_job_hunter.models import (
    ApplicationStatus,
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
    cover_letter_keyboard,
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
    review_state: HumanReviewStatus = HumanReviewStatus.NEW,
    application_status: ApplicationStatus | None = None,
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
        review_state=review_state,
        application_status=application_status,
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
        self.markups = []

    def send_message(self, message: str, **kwargs) -> TelegramSendResult:
        self.messages.append(message)
        self.markups.append(kwargs.get("reply_markup"))
        return TelegramSendResult(message_id="msg-123")


class RejectedProvider:
    def __init__(self):
        self.calls = 0

    def send_message(self, message: str, **kwargs) -> TelegramSendResult:
        self.calls += 1
        raise TelegramRejectedError(429)


class AmbiguousProvider:
    def __init__(self):
        self.calls = 0

    def send_message(self, message: str, **kwargs) -> TelegramSendResult:
        self.calls += 1
        raise RuntimeError("timeout: bot-token-secret-value")


def test_preview_policy_is_read_only(db_session, monkeypatch):
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
                title=f"Backend Engineer {chr(65 + len(rows))}",
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

    # A re-evaluation with the same decision is not news: no second alert.
    evaluation.config_fingerprint = "candidate-config-2"
    db_session.commit()
    third = send_notifications(db_session, _candidate(), provider)
    assert (third.created, third.sent) == (0, 0)
    assert len(provider.messages) == 1
    assert db_session.scalar(select(func.count()).select_from(OpportunityNotification)) == 1


def test_review_to_apply_upgrade_alerts_again_but_review_repeat_does_not(db_session, monkeypatch):
    job, evaluation = _seed_evaluation(db_session, decision="REVIEW")
    _install_opportunities(monkeypatch, [_opportunity(job.id, FinalDecision.REVIEW, 80)])
    provider = FakeProvider()
    assert send_notifications(db_session, _candidate(), provider).sent == 1

    evaluation.config_fingerprint = "candidate-config-2"
    db_session.commit()
    repeat = send_notifications(db_session, _candidate(), provider)
    assert repeat.sent == 0
    suppressed = db_session.scalars(
        select(OpportunityNotification).where(
            OpportunityNotification.status == OpportunityNotificationStatus.SUPPRESSED.value
        )
    ).all()
    assert [row.suppression_reason for row in suppressed] == ["already_notified"]

    evaluation.decision = "APPLY"
    evaluation.config_fingerprint = "candidate-config-3"
    db_session.commit()
    _install_opportunities(monkeypatch, [_opportunity(job.id, FinalDecision.APPLY, 85)])
    upgrade = send_notifications(db_session, _candidate(), provider)
    assert upgrade.sent == 1
    assert len(provider.messages) == 2

    evaluation.config_fingerprint = "candidate-config-4"
    db_session.commit()
    assert send_notifications(db_session, _candidate(), provider).sent == 0
    assert len(provider.messages) == 2


@pytest.mark.parametrize(
    ("review_state", "application_status"),
    [
        (HumanReviewStatus.DISMISSED, None),
        (HumanReviewStatus.SEEN, ApplicationStatus.APPLIED),
        (HumanReviewStatus.NEW, ApplicationStatus.DRAFT),
    ],
)
def test_dismissed_or_applied_jobs_never_alert(db_session, monkeypatch, review_state, application_status):
    job, _ = _seed_evaluation(db_session)
    _install_opportunities(
        monkeypatch,
        [
            _opportunity(
                job.id,
                FinalDecision.APPLY,
                95,
                review_state=review_state,
                application_status=application_status,
            )
        ],
    )
    provider = FakeProvider()

    assert preview_notifications(db_session, _candidate()) == []
    result = send_notifications(db_session, _candidate(), provider)

    assert result.sent == 0
    assert provider.messages == []


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

    assert message.startswith("👀 <b>REVIEW</b> · prioridad 79/100")
    assert "<b>Backend Engineer</b>" in message
    assert "🏢 Example Co" in message
    assert "📍 Remote — Spain · 🏠 remoto" in message
    assert "💰 60.000–80.000 €/año" in message
    assert "🎓 Experiencia: no especificada" in message
    assert "🧰 Python, PostgreSQL" in message
    assert "encaje de rol/backend por confirmar" in message
    assert '<a href="https://jobs.example.test/role">Ver oferta →</a>' in message
    assert "candidate@example.test" not in message
    assert "raw Jev" not in message
    assert "?email=" not in message
    assert "#apply" not in message
    assert "⚠️" not in message
    apply_message = format_notification_message(_opportunity(job_id, FinalDecision.APPLY, 81))
    assert apply_message.startswith("🔥 <b>APPLY</b>")
    assert "A revisar" not in apply_message
    assert len(message) <= 3500


def test_formatter_escapes_html_and_reports_missing_fields_and_strengths():
    item = _opportunity(uuid4(), FinalDecision.REVIEW, 75, company="R&D <Labs>", title="Backend <b>Engineer</b>")
    item = dataclasses.replace(
        item,
        salary_min=None,
        salary_max=None,
        remote_policy=None,
        location=None,
        technologies=(),
        required_technologies=(),
        jev_signals={
            "role_relevance": {"value": 0.9},
            "backend_relevance": {"value": 0.8},
            "career_value": {"value": 0.5},
        },
    )

    message = format_notification_message(item)

    assert "R&amp;D &lt;Labs&gt;" in message
    assert "Backend &lt;b&gt;Engineer&lt;/b&gt;" in message
    assert "💰 Salario no publicado" in message
    assert "📍 Ubicación no indicada · modalidad no indicada" in message
    assert "✅ <b>Encaja en:</b> rol, backend" in message
    assert "valor de carrera" not in message


@pytest.mark.parametrize(
    ("location", "remote_policy", "preferred_status", "warned"),
    [
        ("Barcelona, Spain", None, "UNKNOWN", True),
        ("Madrid, Spain", None, "COMPATIBLE", False),
        ("Remote Spain", None, "UNKNOWN", False),
        ("Barcelona, Spain", "REMOTE", "UNKNOWN", False),
    ],
)
def test_unknown_work_mode_city_outside_locations_is_flagged(location, remote_policy, preferred_status, warned):
    item = dataclasses.replace(
        _opportunity(uuid4(), FinalDecision.REVIEW, 81),
        location=location,
        remote_policy=remote_policy,
        deterministic_result={"signals": {"preferred_location": {"status": preferred_status}}},
    )

    message = format_notification_message(item)

    assert ("⚠️ " + location + ": la oferta no indica modalidad" in message) is warned


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


def test_each_alert_is_sent_with_a_cover_letter_button(db_session, monkeypatch):
    job, _ = _seed_evaluation(db_session)
    _install_opportunities(monkeypatch, [_opportunity(job.id, FinalDecision.APPLY, 81)])
    provider = FakeProvider()

    send_notifications(db_session, _candidate(), provider)

    assert provider.markups == [cover_letter_keyboard(job.id)]
    row = provider.markups[0]["inline_keyboard"]
    assert len(row) == 3 and [button["text"] for button in row[0]] == ["✍️ Cover letter", "🇪🇸 En español"]
    assert [button["callback_data"] for button in row[0]] == [f"cl:{job.id}", f"cles:{job.id}"]
    assert [button["callback_data"] for button in row[1]] == [f"up:{job.id}", f"dn:{job.id}"]
    assert [button["callback_data"] for button in row[2]] == [f"pc:{job.id}"]
    assert all(len(button["callback_data"].encode()) <= 64 for buttons in row for button in buttons)


def test_telegram_provider_posts_reply_markup_as_json():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(parse_qs(request.read().decode()))
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    provider = TelegramProvider("token", "chat", client=httpx.Client(transport=httpx.MockTransport(handler)))
    keyboard = cover_letter_keyboard(uuid4())
    provider.send_message("hi", reply_markup=keyboard)
    provider.send_message("plain")

    assert json.loads(seen[0]["reply_markup"][0]) == keyboard
    assert "reply_markup" not in seen[1]


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


@pytest.mark.parametrize(
    ("decision", "priority", "alerts"),
    [
        (FinalDecision.REVIEW, 80, False),
        (FinalDecision.REVIEW, 85, True),
        (FinalDecision.APPLY, 60, True),
    ],
)
def test_onsite_roles_alert_only_when_exceptional(db_session, monkeypatch, decision, priority, alerts):
    job, _ = _seed_evaluation(db_session, decision.value)
    item = dataclasses.replace(_opportunity(job.id, decision, priority), remote_policy="ONSITE")
    _install_opportunities(monkeypatch, [item])

    previews = preview_notifications(db_session, _candidate())

    assert bool(previews) is alerts



def _seed_job(session, company: str, title: str, decision: str = "REVIEW"):
    job, evaluation = _seed_evaluation(session, decision, fingerprint=f"fp-{uuid4()}")
    return job, evaluation


def test_same_posting_from_another_source_alerts_once(db_session, monkeypatch):
    first, first_eval = _seed_job(db_session, "Example Co", "Backend Engineer")
    second, second_eval = _seed_job(db_session, "Example Co", "Backend Engineer")
    provider = FakeProvider()
    _install_opportunities(monkeypatch, [_opportunity(first.id, FinalDecision.REVIEW, 80, fingerprint=first_eval.evaluation_fingerprint)])
    assert send_notifications(db_session, _candidate(), provider).sent == 1

    # The same posting arrives later from a portal as a different job.
    _install_opportunities(monkeypatch, [_opportunity(second.id, FinalDecision.REVIEW, 82, fingerprint=second_eval.evaluation_fingerprint)])
    again = send_notifications(db_session, _candidate(), provider)

    assert again.sent == 0
    assert len(provider.messages) == 1
    reasons = {row.suppression_reason for row in db_session.scalars(select(OpportunityNotification)).all()}
    assert "already_notified_elsewhere" in reasons


def test_duplicates_in_one_run_and_company_cap(db_session, monkeypatch):
    rows = []
    titles = ["Backend Engineer", "Backend Engineer", "Platform Engineer", "Java Developer"]
    for index, title in enumerate(titles):
        job, evaluation = _seed_job(db_session, "Example Co", title)
        rows.append(_opportunity(job.id, FinalDecision.REVIEW, 90 - index, fingerprint=evaluation.evaluation_fingerprint, title=title))
    _install_opportunities(monkeypatch, rows)

    previews = preview_notifications(db_session, _candidate())

    # Duplicate "Backend Engineer" dropped; at most two alerts for the company.
    assert [item.title for item in previews] == ["Backend Engineer", "Platform Engineer"]


@pytest.mark.parametrize(
    ("published_days_ago", "first_seen_days_ago", "alerts"),
    [(1, None, True), (5, None, False), (None, 1, True), (None, 10, False), (None, None, True)],
)
def test_only_recent_postings_alert(db_session, monkeypatch, published_days_ago, first_seen_days_ago, alerts):
    job, evaluation = _seed_evaluation(db_session, "APPLY")
    now = datetime.now(UTC)
    item = dataclasses.replace(
        _opportunity(job.id, FinalDecision.APPLY, 90, fingerprint=evaluation.evaluation_fingerprint),
        published_at=now - timedelta(days=published_days_ago) if published_days_ago is not None else None,
        first_seen_at=now - timedelta(days=first_seen_days_ago) if first_seen_days_ago is not None else None,
    )
    _install_opportunities(monkeypatch, [item])

    assert bool(preview_notifications(db_session, _candidate(), max_age_days=3)) is alerts
    assert preview_notifications(db_session, _candidate())  # no age limit unless requested


def test_apply_jobs_are_not_held_back_by_the_company_cap(db_session, monkeypatch):
    rows = []
    for index, title in enumerate(["Backend Engineer", "Platform Engineer", "Java Developer"]):
        job, evaluation = _seed_job(db_session, "Example Co", title)
        rows.append(_opportunity(job.id, FinalDecision.APPLY, 90 - index, fingerprint=evaluation.evaluation_fingerprint, title=title))
    _install_opportunities(monkeypatch, rows)

    previews = preview_notifications(db_session, _candidate())

    assert [item.title for item in previews] == ["Backend Engineer", "Platform Engineer", "Java Developer"]


def test_alert_suggests_a_salary_answer_only_when_no_salary_is_published():
    from dataclasses import replace
    from uuid import uuid4

    base = _opportunity(uuid4(), FinalDecision.REVIEW, 75)
    unpublished = replace(base, salary_min=None, salary_max=None, currency=None, salary_period=None)

    from ai_job_hunter.candidates.profile import SalaryGuideEntry

    guide = {
        "Switzerland": SalaryGuideEntry(low=70_000, answer=80_000, high=90_000, currency="CHF"),
        "Spain": SalaryGuideEntry(low=28_000, answer=32_000, high=34_000, currency="€"),
        "Ireland": SalaryGuideEntry(low=38_000, answer=44_000, high=48_000, currency="€"),
    }
    swiss = format_notification_message(replace(unpublished, location="Bioggio, Ticino"), salary_guide=guide)
    spanish = format_notification_message(replace(unpublished, location="Madrid, Community of Madrid"), salary_guide=guide)
    mixed = format_notification_message(replace(unpublished, location="Madrid; Dublin"), salary_guide=guide)
    published = format_notification_message(replace(base, location="Bioggio, Ticino"), salary_guide=guide)
    no_guide = format_notification_message(replace(unpublished, location="Bioggio, Ticino"))

    assert "🎯 Si te piden expectativa: 80.000 CHF (rango 70.000 CHF a 90.000 CHF)" in swiss
    assert "🎯 Si te piden expectativa: 32.000 €" in spanish
    assert "expectativa" not in mixed and "expectativa" not in published and "expectativa" not in no_guide


def test_alert_links_keep_the_parameter_that_identifies_the_posting_and_nothing_else():
    from ai_job_hunter.services.notifications import _safe_public_url

    assert _safe_public_url("https://careers.nebius.com/?gh_jid=4960679101&utm_source=x&email=a@b.test#apply") == (
        "https://careers.nebius.com/?gh_jid=4960679101"
    )
    assert _safe_public_url("https://careers.toasttab.com/jobs?gh_jid=8174263") == (
        "https://careers.toasttab.com/jobs?gh_jid=8174263"
    )
    assert _safe_public_url("https://jobs.example.test/role?email=candidate@example.test#apply") == (
        "https://jobs.example.test/role"
    )
    assert _safe_public_url("https://jobs.example.test/role?gh_jid=") == "https://jobs.example.test/role"


def test_postings_in_a_language_the_candidate_does_not_speak_never_alert():
    from dataclasses import replace
    from uuid import uuid4

    from ai_job_hunter.services.notifications import _foreign_language_suppression

    item = _opportunity(uuid4(), FinalDecision.REVIEW, 90)

    assert _foreign_language_suppression(item) is None
    assert _foreign_language_suppression(replace(item, foreign_language="portuguese")) == "foreign_language"


def test_board_postings_count_from_when_they_were_first_seen_and_a_first_import_is_never_new():
    from dataclasses import replace
    from datetime import UTC, datetime, timedelta
    from uuid import uuid4

    from ai_job_hunter.services.notifications import _older_than

    now = datetime.now(UTC)
    item = replace(_opportunity(uuid4(), FinalDecision.REVIEW, 80), published_at=now - timedelta(days=30), first_seen_at=now - timedelta(hours=2))

    assert _older_than(item, 3) is True  # a portal posting published 30 days ago
    assert _older_than(replace(item, from_board=True), 3) is False  # a board posting that appeared 2 hours ago
    assert _older_than(replace(item, from_board=True, is_baseline=True), 3) is True  # it was in the first import
    assert _older_than(replace(item, from_board=True, first_seen_at=now - timedelta(days=5)), 3) is True


def test_alerts_show_the_work_mode_and_salary_the_text_states_marked_as_such():
    from dataclasses import replace
    from uuid import uuid4

    base = _opportunity(uuid4(), FinalDecision.REVIEW, 75)
    bare = replace(base, remote_policy=None, salary_min=None, salary_max=None, currency=None, salary_period=None)

    plain = format_notification_message(bare)
    from_text = format_notification_message(replace(bare, text_work_mode="HYBRID", text_salary="25.000–35.000 €"))
    stated = format_notification_message(replace(base, text_work_mode="REMOTE"))

    assert "modalidad no indicada" in plain and "Salario no publicado" in plain
    assert "híbrido (según el texto)" in from_text and "25.000–35.000 € (según el texto)" in from_text
    assert "según el texto" not in stated  # the stated work mode wins and is not annotated
