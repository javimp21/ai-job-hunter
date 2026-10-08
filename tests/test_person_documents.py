from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from uuid import uuid4

import pytest
from sqlalchemy import select
from test_opportunity_service import FakeEngine, _install_fetch, _monitor_company, _offer

from ai_job_hunter.candidates import CandidateConfig, CandidateProfile
from ai_job_hunter.db.user_context import acting_as
from ai_job_hunter.decision_engine import DecisionCache
from ai_job_hunter.models import GeneratedDocument, JobSource, UsageEvent, User, UserProfile
from ai_job_hunter.services import usage
from ai_job_hunter.services.cover_letters import CoverLetterError, build_cover_letter_request
from ai_job_hunter.services.notifications import cover_letter_keyboard
from ai_job_hunter.services.opportunities import refresh_opportunities
from ai_job_hunter.services.person_documents import PersonDocuments, QuotaExceeded
from ai_job_hunter.services.user_erasure import erase_user
from ai_job_hunter.services.users import ensure_owner, save_profile

CV_TEXT = "Contable en Acme (2023-2025): cierre mensual, conciliaciones. ADE en la UCM."


class FakeClaude:
    """Records the requests and answers every one with a letter."""

    def __init__(self) -> None:
        self.requests: list[dict] = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **request):
        self.requests.append(request)
        block = SimpleNamespace(type="text", text="Hola equipo, me gustaría trabajar con vosotros en el cierre mensual. Un saludo,")
        return SimpleNamespace(content=[block], stop_reason="end_turn", model="fake-opus", usage=None)


@pytest.fixture
def world(db_session, monkeypatch, tmp_path):
    _monitor_company(db_session)
    ensure_owner(db_session, telegram_chat_id="1")
    _install_fetch(monkeypatch, [_offer("role-a"), _offer("role-b")])
    refresh_opportunities(
        db_session, CandidateConfig(profile=CandidateProfile()), max_jev_jobs=5,
        cache=DecisionCache(tmp_path / "owner.local.json"), engine=FakeEngine(),
    )
    db_session.commit()
    people = {}
    for name, chat in (("ana", "200"), ("bea", "300")):
        user = User(telegram_chat_id=chat, status="ACTIVE", consent_at=datetime.now(UTC))
        db_session.add(user)
        db_session.flush()
        save_profile(db_session, user, CandidateConfig(profile=CandidateProfile(current_role="Contable")), cv_text=CV_TEXT)
        people[name] = user.id
    db_session.commit()
    jobs = {s.external_id: s.job_id for s in db_session.scalars(select(JobSource))}
    claude = FakeClaude()
    return SimpleNamespace(session=db_session, people=people, jobs=jobs, claude=claude, docs=PersonDocuments(lambda: db_session, claude))


def test_a_letter_is_written_from_the_stored_summary_saved_for_that_person_and_resent_for_free(world) -> None:
    first = world.docs.letter(world.people["ana"], world.jobs["role-a"])
    again = world.docs.letter(world.people["ana"], world.jobs["role-a"])

    assert not first.reused and again.reused and again.text == first.text
    assert len(world.claude.requests) == 1  # asking again never pays again
    sent = world.claude.requests[0]["messages"][0]["content"]
    assert any(CV_TEXT in block.get("text", "") for block in sent)
    assert "Contable" in repr(world.claude.requests[0]) and "passionate about" in repr(world.claude.requests[0]["system"])
    with acting_as(world.people["ana"]):
        assert world.session.scalar(select(UsageEvent.kind)) == "LETTER"
    with acting_as(world.people["bea"]):  # the other person has nothing: no document, no usage
        assert world.session.scalar(select(GeneratedDocument.id)) is None
        assert world.session.scalar(select(UsageEvent.id)) is None


def test_quotas_stop_new_letters_but_not_the_ones_already_written(world) -> None:
    ana = world.people["ana"]
    for index in range(3):  # three per day: the same job in another language is a new letter, other jobs too
        world.docs.letter(ana, world.jobs["role-a"], ["auto", "es", "en"][index])
    with pytest.raises(QuotaExceeded) as refused:
        world.docs.letter(ana, world.jobs["role-b"])
    assert "3 cartas de hoy" in str(refused.value)
    assert world.docs.letter(ana, world.jobs["role-a"], "es").reused  # already written: still resent
    assert len(world.claude.requests) == 3
    world.docs.letter(world.people["bea"], world.jobs["role-b"])  # the limit is per person
    assert len(world.claude.requests) == 4


def test_quota_windows_reset_and_the_weekly_limit_counts(db_session) -> None:
    ensure_owner(db_session)
    now = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
    for days_ago in (0, 0, 2, 3, 3, 4, 4, 5, 5, 6):
        usage.record_usage(db_session, usage.LETTER, now=now - timedelta(days=days_ago, minutes=5))
    decision = usage.check_quota(db_session, usage.LETTER, now=now)
    assert not decision.allowed and "10 cartas de esta semana" in decision.message
    assert usage.check_quota(db_session, usage.LETTER, now=now + timedelta(days=2)).allowed
    assert usage.check_quota(db_session, usage.INTERVIEW, now=now).allowed


def test_an_interview_brief_needs_the_summary_and_is_stored_like_a_letter(world) -> None:
    brief = world.docs.interview(world.people["ana"], world.jobs["role-a"])
    assert not brief.reused and world.docs.interview(world.people["ana"], world.jobs["role-a"]).reused
    assert CV_TEXT in repr(world.claude.requests[0])
    profile = world.session.scalar(select(UserProfile).where(UserProfile.user_id == world.people["bea"]))
    profile.cv_text = None
    world.session.commit()
    with pytest.raises(CoverLetterError) as missing:
        world.docs.interview(world.people["bea"], world.jobs["role-a"])
    assert "resumen de tu experiencia" in str(missing.value) and len(world.claude.requests) == 1


def test_erasing_a_person_removes_their_documents_and_usage(world) -> None:
    world.docs.letter(world.people["ana"], world.jobs["role-a"])
    erase_user(world.session, world.session.get(User, world.people["ana"]))
    world.session.commit()
    from sqlalchemy import func

    assert world.session.scalar(select(func.count()).select_from(GeneratedDocument).execution_options(skip_user_scope=True)) == 0
    assert world.session.scalar(select(func.count()).select_from(UsageEvent).execution_options(skip_user_scope=True)) == 0


def test_alerts_for_other_people_have_no_application_pack_button_and_the_owners_keep_it() -> None:
    job = uuid4()
    assert len(cover_letter_keyboard(job)["inline_keyboard"]) == 3
    assert len(cover_letter_keyboard(job, application_pack=False)["inline_keyboard"]) == 2


def test_the_letter_request_carries_the_summary_only_when_there_is_one() -> None:
    posting = {"company": "Acme", "title": "Contable"}
    plain = build_cover_letter_request(posting=posting, candidate_facts={}, style_guide="s", cv_pdf=None)
    withcv = build_cover_letter_request(posting=posting, candidate_facts={}, style_guide="s", cv_pdf=None, cv_text="mi resumen")
    assert "candidate_cv" not in repr(plain) and "<candidate_cv>\nmi resumen" in repr(withcv).replace("\\n", "\n")
