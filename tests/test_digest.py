import dataclasses
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select

from ai_job_hunter.decision_engine import FinalDecision
from ai_job_hunter.models import HumanReviewStatus, OpportunityNotification
from ai_job_hunter.services import digest as digest_service
from ai_job_hunter.services.digest import (
    DIGEST_CHANNEL,
    preview_digest,
    select_digest_entries,
    send_digest,
)
from ai_job_hunter.services.notifications import preview_notifications, send_notifications
from tests.test_notifications import (
    AmbiguousProvider,
    FakeProvider,
    _candidate,
    _install_opportunities,
    _opportunity,
    _seed_evaluation,
)

OPTIONS = {"review_threshold": 70, "max_age_days": 3}


def _item(session, priority, *, decision=FinalDecision.REVIEW, title="Backend Engineer", company="Example Co", **changes):
    job, evaluation = _seed_evaluation(session, decision.value, fingerprint=f"fp-{uuid4()}")
    item = _opportunity(
        job.id, decision, priority, fingerprint=evaluation.evaluation_fingerprint, title=title, company=company
    )
    return dataclasses.replace(item, **changes) if changes else item


def test_digest_lists_second_tier_jobs_best_first(db_session, monkeypatch):
    rows = [
        _item(db_session, 60, title="Platform Engineer"),
        _item(db_session, 45, title="Data Engineer"),  # below the digest floor
        _item(db_session, 90, title="Staff Engineer"),  # alerts instead
        _item(db_session, 66, title="Java Developer"),
    ]
    _install_opportunities(monkeypatch, rows)

    entries = select_digest_entries(db_session, _candidate(), **OPTIONS)

    assert [entry.item.title for entry in entries] == ["Java Developer", "Platform Engineer"]
    assert {entry.reason for entry in entries} == {"review_priority_below_threshold"}


def test_dismissed_applied_and_old_jobs_are_left_out(db_session, monkeypatch):
    old = datetime.now(UTC) - timedelta(days=10)
    rows = [
        _item(db_session, 60, title="A Engineer", review_state=HumanReviewStatus.DISMISSED),
        _item(db_session, 60, title="B Engineer", first_seen_at=old),
        _item(db_session, 60, title="C Engineer", remote_policy="ONSITE"),  # on-site needs 70
        _item(db_session, 72, title="D Engineer", remote_policy="ONSITE"),
    ]
    _install_opportunities(monkeypatch, rows)

    entries = select_digest_entries(db_session, _candidate(), **OPTIONS)

    assert [(entry.item.title, entry.reason) for entry in entries] == [("D Engineer", "onsite_not_exceptional")]


def test_uncertain_location_review_goes_to_digest_not_alert(db_session, monkeypatch):
    item = _item(
        db_session,
        80,
        location="Barcelona, Spain",
        remote_policy=None,
        deterministic_result={"signals": {"preferred_location": {"status": "UNKNOWN"}}},
    )
    _install_opportunities(monkeypatch, [item])

    assert preview_notifications(db_session, _candidate(), review_threshold=70) == []
    entries = select_digest_entries(db_session, _candidate(), **OPTIONS)
    assert [entry.reason for entry in entries] == ["uncertain_location"]
    assert "⚠️ puede no ser remota" in digest_service.format_digest_message(entries)


def test_uncertain_location_apply_still_alerts(db_session, monkeypatch):
    item = _item(
        db_session,
        80,
        decision=FinalDecision.APPLY,
        location="Barcelona, Spain",
        remote_policy=None,
        deterministic_result={"signals": {"preferred_location": {"status": "UNKNOWN"}}},
    )
    _install_opportunities(monkeypatch, [item])

    assert len(preview_notifications(db_session, _candidate(), review_threshold=70)) == 1


def test_digest_is_sent_once_with_numbered_buttons_and_never_repeats(db_session, monkeypatch):
    rows = [_item(db_session, 60, title="Platform Engineer"), _item(db_session, 55, title="Java Developer")]
    _install_opportunities(monkeypatch, rows)
    provider = FakeProvider()
    now = datetime.now(UTC)

    result = send_digest(db_session, _candidate(), provider, now=now, **OPTIONS)

    assert result.status == "sent"
    assert len(provider.messages) == 1
    message = provider.messages[0]
    assert "<b>1.</b> [60]" in message and "<b>2.</b> [55]" in message
    keyboard = provider.markups[0]["inline_keyboard"]
    assert [button["text"] for button in keyboard[0]] == ["1 ✍️", "1 👍", "1 👎", "1 📝"]
    assert keyboard[1][0]["callback_data"] == f"cl:{rows[1].job_id}"
    assert all(len(button["callback_data"].encode()) <= 64 for row in keyboard for button in row)
    stored = db_session.scalars(select(OpportunityNotification).where(OpportunityNotification.channel == DIGEST_CHANNEL)).all()
    assert {row.job_id for row in stored} == {row.job_id for row in rows}

    # Within 20 hours nothing is sent; later the same jobs are not listed again.
    assert send_digest(db_session, _candidate(), provider, now=now + timedelta(hours=2), **OPTIONS).status == "too_soon"
    assert send_digest(db_session, _candidate(), provider, now=now + timedelta(hours=21), **OPTIONS).status == "empty"
    assert len(provider.messages) == 1


def test_digest_never_lists_an_alerted_job_and_does_not_affect_alerts(db_session, monkeypatch):
    alerted = _item(db_session, 85, title="Staff Engineer")
    _install_opportunities(monkeypatch, [alerted])
    assert send_notifications(db_session, _candidate(), FakeProvider(), review_threshold=70).sent == 1

    # The job later drops below the alert threshold: it was already seen.
    _install_opportunities(monkeypatch, [dataclasses.replace(alerted, priority=60)])
    assert select_digest_entries(db_session, _candidate(), **OPTIONS) == []

    # A digest entry does not count as an alert for cross-source suppression.
    listed = _item(db_session, 60, title="Platform Engineer")
    _install_opportunities(monkeypatch, [listed])
    send_digest(db_session, _candidate(), FakeProvider(), **OPTIONS)
    upgraded = dataclasses.replace(listed, decision=FinalDecision.APPLY, priority=90)
    _install_opportunities(monkeypatch, [upgraded])
    assert len(preview_notifications(db_session, _candidate(), review_threshold=70)) == 1


def test_failed_digest_records_nothing_and_preview_writes_nothing(db_session, monkeypatch):
    _install_opportunities(monkeypatch, [_item(db_session, 60)])

    assert preview_digest(db_session, _candidate(), **OPTIONS).status == "preview"
    assert send_digest(db_session, _candidate(), AmbiguousProvider(), **OPTIONS).status == "failed"
    assert db_session.scalars(select(OpportunityNotification)).all() == []
    assert send_digest(db_session, _candidate(), FakeProvider(), **OPTIONS).status == "sent"


def test_digest_message_escapes_job_text(db_session, monkeypatch):
    _install_opportunities(monkeypatch, [_item(db_session, 60, title="<b>Backend</b> & Co", company="A<B")])

    message = preview_digest(db_session, _candidate(), **OPTIONS).message

    assert "&lt;b&gt;Backend&lt;/b&gt; &amp; Co" in message
    assert "A&lt;B" in message


def test_newly_discovered_older_postings_reach_the_digest_up_to_30_days(db_session, monkeypatch):
    now = datetime.now(UTC)
    rows = [
        _item(db_session, 60, title="Recently found", published_at=now - timedelta(days=20), first_seen_at=now - timedelta(hours=3)),
        _item(db_session, 60, title="Too old", published_at=now - timedelta(days=31), first_seen_at=now - timedelta(hours=3)),
        _item(db_session, 60, title="Old and known", published_at=now - timedelta(days=20), first_seen_at=now - timedelta(days=10)),
    ]
    _install_opportunities(monkeypatch, rows)

    entries = select_digest_entries(db_session, _candidate(), **OPTIONS)

    assert [entry.item.title for entry in entries] == ["Recently found"]
