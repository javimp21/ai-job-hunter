from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from test_opportunity_service import FakeEngine, _install_fetch, _monitor_company, _offer

from ai_job_hunter.candidates import CandidateConfig, CandidateProfile
from ai_job_hunter.db.user_context import acting_as
from ai_job_hunter.decision_engine import DecisionCache
from ai_job_hunter.models import Job, JobEvaluation, JobSource, OpportunityNotification, User
from ai_job_hunter.services.notifications import TelegramSendResult
from ai_job_hunter.services import opportunities
from ai_job_hunter.services.opportunities import refresh_opportunities
from ai_job_hunter.services.user_runs import TRIAL_ENDED_TEXT, run_for_users
from ai_job_hunter.services.users import ensure_owner, save_profile


class Outbox:
    """One fake Telegram provider per chat, all writing to the same list."""

    def __init__(self, broken_chats: tuple[str, ...] = ()) -> None:
        self.sent: list[tuple[str, str]] = []
        self.broken = broken_chats

    def provider(self, chat: str):
        outbox = self

        class Provider:
            def send_message(self, message, *, reply_markup=None):
                if chat in outbox.broken:
                    raise RuntimeError("telegram is down for this chat")
                outbox.sent.append((chat, message))
                return TelegramSendResult(message_id=str(100 + len(outbox.sent)))

        return Provider()


@pytest.fixture
def world(db_session, monkeypatch, tmp_path):
    # Alerts read evaluations by the real engine's identity; here the fake one stands in for it.
    monkeypatch.setattr(opportunities, "JevJobDecisionEngine", FakeEngine)
    _monitor_company(db_session)
    owner = ensure_owner(db_session, telegram_chat_id="1")
    now = datetime.now(UTC)
    # The first import of a board is only its baseline; the offer that appears later is the new one that alerts.
    for offers in ([_offer("role-a")], [_offer("role-a"), _offer("role-b", published_at=now)]):
        _install_fetch(monkeypatch, offers)
        refresh_opportunities(
            db_session, CandidateConfig(profile=CandidateProfile()), max_jev_jobs=5,
            cache=DecisionCache(tmp_path / "owner.local.json"), engine=FakeEngine(),
        )
        db_session.commit()
    # The board was first read days before role-b appeared (the test itself runs in seconds).
    first = db_session.scalar(select(Job).join(JobSource).where(JobSource.external_id == "role-a"))
    first.created_at = now - timedelta(days=10)
    db_session.commit()
    people = {}
    for name, chat, trial in (("ana", "200", now + timedelta(days=5)), ("bea", "300", now + timedelta(days=5)), ("old", "400", now - timedelta(days=1))):
        user = User(telegram_chat_id=chat, status="ACTIVE", consent_at=now, trial_started_at=now - timedelta(days=7), trial_ends_at=trial)
        db_session.add(user)
        db_session.flush()
        save_profile(db_session, user, CandidateConfig(profile=CandidateProfile()))
        people[name] = user.id
    db_session.commit()
    return owner, people, tmp_path, now


def evaluations_of(session, user_id):
    with acting_as(user_id):
        return session.scalars(select(JobEvaluation)).all()


def run(db_session, world, outbox, engine, **options):
    _, _, tmp_path, now = world
    return run_for_users(
        lambda: db_session, outbox.provider, review_threshold=70, max_age_days=3, engine=engine,
        cache=DecisionCache(tmp_path / "people.local.json"), now=now, **options,
    )


def test_each_person_gets_their_own_evaluations_and_alerts_and_a_second_pass_repeats_nothing(world, db_session) -> None:
    owner, people, _, _ = world
    outbox, engine = Outbox(), FakeEngine()
    owner_rows = len(evaluations_of(db_session, owner.id))

    results = {str(r.user_id): r for r in run(db_session, world, outbox, engine)}

    ana, bea = results[str(people["ana"])], results[str(people["bea"])]
    assert ana.error is None and ana.candidates == 2 and ana.sent == 1 and bea.sent == 1
    assert {chat for chat, _ in outbox.sent} == {"200", "300", "400"}  # 400 only hears that their trial ended
    assert [text for chat, text in outbox.sent if chat == "400"] == [TRIAL_ENDED_TEXT]
    assert len(evaluations_of(db_session, people["ana"])) == 2 == len(evaluations_of(db_session, people["bea"]))
    assert len(evaluations_of(db_session, owner.id)) == owner_rows  # the owner's own data is untouched
    first_messages, first_calls = len(outbox.sent), len(engine.calls)

    again = {str(r.user_id): r for r in run(db_session, world, outbox, engine)}

    assert again[str(people["ana"])].candidates == 0 and len(outbox.sent) == first_messages
    assert len(engine.calls) == first_calls  # the second pass never asks Jev again
    with acting_as(people["ana"]):
        assert db_session.scalar(select(OpportunityNotification.user_id)) == people["ana"]


def test_an_ended_trial_stops_the_alerts_once_and_says_so(world, db_session) -> None:
    _, people, _, _ = world
    outbox = Outbox()

    first = {str(r.user_id): r for r in run(db_session, world, outbox, FakeEngine())}
    second = {str(r.user_id): r for r in run(db_session, world, outbox, FakeEngine())}

    assert first[str(people["old"])].trial_ended and str(people["old"]) not in second
    assert db_session.get(User, people["old"]).status == "TRIAL_ENDED"
    assert [text for chat, text in outbox.sent if chat == "400"] == [TRIAL_ENDED_TEXT]


def test_one_persons_failure_does_not_stop_the_others_and_never_leaks_details(world, db_session) -> None:
    _, people, _, _ = world
    outbox = Outbox(broken_chats=("200",))

    results = {str(r.user_id): r for r in run(db_session, world, outbox, FakeEngine())}

    assert results[str(people["bea"])].sent >= 1 and results[str(people["bea"])].error is None
    assert results[str(people["ana"])].sent == 0 and (results[str(people["ana"])].error or results[str(people["ana"])].failed)
    assert "telegram is down" not in repr(results)


def test_the_jev_budget_per_person_limits_new_evaluations(world, db_session) -> None:
    _, people, _, _ = world
    engine = FakeEngine()

    results = {str(r.user_id): r for r in run(db_session, world, Outbox(), engine, max_jev_jobs=1)}

    assert results[str(people["ana"])].jev_evaluated == 1 and results[str(people["bea"])].jev_evaluated == 1
    assert len(engine.calls) == 2


def test_offers_seen_only_through_an_owner_only_feed_are_not_evaluated_for_other_people(world, db_session) -> None:
    _, people, _, _ = world
    source = db_session.scalar(select(JobSource).where(JobSource.external_id == "role-b"))
    source.provider = "fantastic_jobs"
    db_session.commit()
    engine = FakeEngine()

    results = {str(r.user_id): r for r in run(db_session, world, Outbox(), engine)}

    assert results[str(people["ana"])].candidates == 1 and engine.calls == ["role-a"]  # the second person reuses the cached answer


def test_the_weekly_opinion_review_reads_only_that_persons_notes_and_runs_once_a_week(world, db_session) -> None:
    from types import SimpleNamespace

    from ai_job_hunter.models import Job, JobFeedbackNote

    _, people, _, _ = world
    job = db_session.scalar(select(Job))
    with acting_as(people["ana"]):
        for index in range(5):
            db_session.add(JobFeedbackNote(job_id=job.id, text=f"opinion {index} <b>"))
        db_session.commit()
    seen: list[str] = []

    def create(**request):
        seen.append(request["messages"][0]["content"])
        return SimpleNamespace(content=[SimpleNamespace(type="text", text="1. Prefieres remoto & sueldo.")])

    claude = SimpleNamespace(messages=SimpleNamespace(create=create))
    outbox = Outbox()

    run(db_session, world, outbox, FakeEngine(), review_client=claude)
    run(db_session, world, outbox, FakeEngine(), review_client=claude)

    reviews = [text for chat, text in outbox.sent if "Lo que me has contado" in text]
    assert len(reviews) == 1 and "&amp; sueldo" in reviews[0] and "quien te invitó" in reviews[0]
    assert len(seen) == 1 and "opinion 0" in seen[0]
    assert [chat for chat, text in outbox.sent if "Lo que me has contado" in text] == ["200"]
