from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from test_onboarding import CV_DRAFT, NOW, new_user

from ai_job_hunter.candidates import CandidateConfig, CandidateProfile
from ai_job_hunter.candidates.exclusions import company_matches, exclusion_reason, title_matches
from ai_job_hunter.db.user_context import acting_as
from ai_job_hunter.models import Company, Job, JobFeedbackNote, PreferenceChange, UserProfile
from ai_job_hunter.services import learned, preference_learning
from ai_job_hunter.services.notifications import alerts_held
from ai_job_hunter.services.onboarding import build_config
from ai_job_hunter.services.opportunities import _config_fingerprint
from ai_job_hunter.services.users import load_profile, save_profile


def test_a_term_matches_whole_words_in_any_spelling_and_never_inside_other_words() -> None:
    assert title_matches("Full-Stack Developer", "full stack") and title_matches("Fullstack Engineer", "full stack")
    assert title_matches("Senior FULL STACK Engineer", "Full Stack")
    assert not title_matches("JavaScript Developer", "java") and title_matches("Java Developer", "java")
    assert not title_matches("Backend Engineer", "full stack")
    assert company_matches("Acme S.L.", "acme sl") and not company_matches("Acme Labs", "Acme")


def test_exclusions_read_the_personal_lists_only() -> None:
    prefs = CandidateConfig(
        profile=CandidateProfile(), preferences={"excluded_title_terms": ["frontend"], "excluded_companies": ["Acme"]}
    ).preferences
    assert "frontend" in exclusion_reason("Frontend Engineer", "Zeta", prefs)
    assert "Acme" in exclusion_reason("Backend Engineer", "ACME", prefs)
    assert exclusion_reason("Backend Engineer", "Zeta", prefs) is None


def test_new_preference_fields_never_change_the_fingerprint_of_anyone_who_did_not_use_them() -> None:
    def config(**preferences):
        return CandidateConfig(profile=CandidateProfile(current_role="Dev"), preferences=preferences)

    fingerprint = _config_fingerprint(config(), "engine")
    gated = config(quiet_hours_start=22, quiet_hours_end=8, paused_until="2026-10-20")
    assert _config_fingerprint(gated, "engine") == fingerprint  # gating the alerts never re-evaluates anything
    assert _config_fingerprint(config(excluded_title_terms=["frontend"]), "engine") != fingerprint
    assert _config_fingerprint(config(accept_offers_without_salary=False), "engine") != fingerprint


def test_quiet_hours_and_pause_hold_the_alerts_in_the_persons_local_time() -> None:
    night = CandidateConfig(profile=CandidateProfile(), preferences={"quiet_hours_start": 22, "quiet_hours_end": 8})
    at_23_madrid = datetime(2026, 10, 9, 21, 0, tzinfo=UTC)  # 23:00 in Madrid (CEST)
    at_12_madrid = datetime(2026, 10, 9, 10, 0, tzinfo=UTC)
    assert alerts_held(night, now=at_23_madrid) == "quiet_hours" and alerts_held(night, now=at_12_madrid) is None
    day = CandidateConfig(profile=CandidateProfile(), preferences={"quiet_hours_start": 9, "quiet_hours_end": 17})
    assert alerts_held(day, now=at_12_madrid) == "quiet_hours" and alerts_held(day, now=at_23_madrid) is None
    paused = CandidateConfig(profile=CandidateProfile(), preferences={"paused_until": "2026-10-12"})
    assert alerts_held(paused, now=at_12_madrid) == "paused_until"
    assert alerts_held(paused, now=datetime(2026, 10, 13, 10, 0, tzinfo=UTC)) is None


class FakeClaude:
    def __init__(self, changes):
        self.requests = []
        self._changes = changes
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **request):
        self.requests.append(request)
        return SimpleNamespace(content=[SimpleNamespace(type="tool_use", input={"changes": self._changes})])


@pytest.fixture
def person(db_session):
    _, user = new_user(db_session)
    user.status = "ACTIVE"
    save_profile(
        db_session, user, build_config({**CV_DRAFT, "sector": "software", "role": "Backend", "locations": ["Madrid"]})
    )
    company = Company(name="Acme")
    job = Job(title="Full Stack Developer", company=company)
    db_session.add_all([company, job])
    db_session.flush()
    with acting_as(user.id):
        for text in ("sueldo bajo aquí", "no quiero consultoras", "este tipo de puesto (Full Stack Developer) no me interesa"):
            db_session.add(JobFeedbackNote(job_id=job.id, text=text, vote="DISMISSED"))
        db_session.flush()
    return user


def test_clear_opinions_become_applied_changes_with_an_announcement_and_can_be_undone(db_session, person) -> None:
    claude = FakeClaude([
        {"kind": "exclude_title_term", "value": "full stack", "note_number": 3, "reason": "No quieres puestos full stack."},
        {"kind": "exclude_company", "value": "Acme", "note_number": 2, "reason": "Quieres evitar esa empresa."},
        {"kind": "bogus", "value": "x", "note_number": 1, "reason": "x"},
        {"kind": "exclude_title_term", "value": "ab", "note_number": 1, "reason": "too short"},
        {"kind": "exclude_title_term", "value": "backend", "note_number": 99, "reason": "no such note"},
    ])
    with acting_as(person.id):
        announcements = preference_learning.adapt(db_session, person, client=claude, now=NOW)
        db_session.commit()
        assert len(announcements) == 2 and "«full stack»" in announcements[0].text
        assert "este tipo de puesto" in announcements[0].text and "no quiero consultoras" in announcements[1].text
        config = load_profile(db_session, person)
        assert config.preferences.excluded_title_terms == ["full stack"]
        assert config.preferences.excluded_companies == ["Acme"]
        assert db_session.scalars(select(PreferenceChange.status)).all() == ["APPLIED", "APPLIED"]
        assert "opinion" in repr(claude.requests[0]["messages"]) or "sueldo" in repr(claude.requests[0]["messages"])

        assert preference_learning.undo(db_session, person, announcements[0].change_id) == "Hecho, he deshecho ese cambio."
        assert load_profile(db_session, person).preferences.excluded_title_terms == []
        assert "ya estaba deshecho" in preference_learning.undo(db_session, person, announcements[0].change_id)
    stored = db_session.scalar(select(UserProfile).where(UserProfile.user_id == person.id))
    assert "excluded" not in repr(stored.config.get("preferences", {}).get("excluded_companies"))  # answers untouched
    assert stored.learned["excluded_companies"] == ["Acme"]


def test_nothing_is_spent_with_fewer_than_three_notes_or_right_after_an_adaptation(db_session, person) -> None:
    claude = FakeClaude([])
    with acting_as(person.id):
        for note in db_session.scalars(select(JobFeedbackNote)).all()[:1]:
            db_session.delete(note)
        db_session.flush()
        base = datetime.now(UTC) - timedelta(hours=1)
        assert preference_learning.adapt(db_session, person, client=claude, now=base) == [] and claude.requests == []

        job = db_session.scalar(select(Job))
        db_session.add(JobFeedbackNote(job_id=job.id, text="una más"))
        db_session.flush()
        preference_learning.adapt(db_session, person, client=claude, now=base)
        assert len(claude.requests) == 1
        db_session.add_all([JobFeedbackNote(job_id=job.id, text=f"otra {i}") for i in range(3)])
        db_session.flush()
        preference_learning.adapt(db_session, person, client=claude, now=base + timedelta(hours=5))
        assert len(claude.requests) == 1  # less than two days later
        preference_learning.adapt(db_session, person, client=claude, now=base + timedelta(days=3))
        assert len(claude.requests) == 2


def test_quiet_hours_pause_and_more_like_this_merge_over_the_answers(db_session, person) -> None:
    with acting_as(person.id):
        assert learned.apply_change(db_session, person, "quiet_hours", {"start": 22, "end": 8})
        assert learned.apply_change(db_session, person, "pause_until", "2026-10-12")
        assert learned.apply_change(db_session, person, "more_like_this", "Backend Engineer")
        assert learned.apply_change(db_session, person, "exclude_language", "german")
        assert not learned.apply_change(db_session, person, "exclude_language", "German")  # already there
        assert not learned.apply_change(db_session, person, "quiet_hours", {"start": 5, "end": 5})
        assert not learned.apply_change(db_session, person, "pause_until", "not a date")
        prefs = load_profile(db_session, person).preferences
    assert (prefs.quiet_hours_start, prefs.quiet_hours_end, prefs.paused_until) == (22, 8, date(2026, 10, 12))
    assert "Backend Engineer" in prefs.preferred_roles and prefs.excluded_languages == ["german"]


def test_an_excluded_title_is_skipped_before_jev_and_an_excluded_company_never_alerts(db_session, monkeypatch, tmp_path) -> None:
    from test_opportunity_service import FakeEngine, _install_fetch, _monitor_company, _offer

    from ai_job_hunter.decision_engine import DecisionCache
    from ai_job_hunter.services.opportunities import refresh_opportunities

    _monitor_company(db_session)
    _install_fetch(monkeypatch, [_offer("keep", title="Backend Engineer"), _offer("drop", title="Full-Stack Developer")])
    candidate = CandidateConfig(profile=CandidateProfile(), preferences={"excluded_title_terms": ["full stack"]})
    engine = FakeEngine()

    summary = refresh_opportunities(
        db_session, candidate, max_jev_jobs=5, cache=DecisionCache(tmp_path / "x.local.json"), engine=engine
    )

    assert engine.calls == ["keep"] and summary.hard_skips == 1  # the excluded one never reached Jev
