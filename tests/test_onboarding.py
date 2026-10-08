from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from ai_job_hunter.db.user_context import acting_as
from ai_job_hunter.models import Company, Job, JobFeedbackNote, JobReview, User, UserProfile
from ai_job_hunter.services.onboarding import (
    Event,
    build_config,
    create_invitation,
    handle,
    handle_command,
    handle_erase_press,
    parse_salary,
    redeem_invitation,
)
from ai_job_hunter.services.users import ensure_owner, load_profile

NOW = datetime(2026, 10, 9, 10, 0, tzinfo=UTC)
CV_DRAFT = {
    "current_role": "Contable", "years_of_experience": 2, "primary_skills": ["Contabilidad", "Cierre mensual"],
    "technologies": ["Excel", "SAP"], "languages": ["Spanish", "English"], "education": "ADE",
    "current_country": "Spain", "current_city": "Madrid",
}


def fake_extract(text, file, previous, correction):
    draft = dict(previous or CV_DRAFT)
    if correction:
        draft["years_of_experience"] = 3
    return draft


def say(session, user, **event):
    return handle(session, user, Event(**event), fake_extract, now=NOW)


def new_user(session):
    owner = ensure_owner(session)
    user, _ = redeem_invitation(session, create_invitation(session, owner, now=NOW).code, "100", now=NOW)
    return owner, user


def test_invitations_are_single_use_expire_and_one_chat_has_one_account(db_session) -> None:
    owner = ensure_owner(db_session)
    invitation = create_invitation(db_session, owner, now=NOW)
    assert len(invitation.code) == 8

    assert redeem_invitation(db_session, "NOPE", "1", now=NOW) == (None, "unknown")
    user, outcome = redeem_invitation(db_session, invitation.code.lower(), "100", now=NOW)
    assert outcome == "new" and user.status == "ONBOARDING" and user.telegram_chat_id == "100"
    assert redeem_invitation(db_session, invitation.code, "200", now=NOW) == (None, "used")
    again, outcome = redeem_invitation(db_session, invitation.code, "100", now=NOW)
    assert (again.id, outcome) == (user.id, "existing")

    old = create_invitation(db_session, owner, now=NOW - timedelta(days=30))
    assert redeem_invitation(db_session, old.code, "300", now=NOW) == (None, "expired")


def test_the_whole_conversation_ends_with_a_validated_profile_and_a_trial(db_session) -> None:
    _, user = new_user(db_session)

    assert "¿Aceptas?" in say(db_session, user, kind="text", text="hola")[0].text
    say(db_session, user, kind="press", data="ob:consent:yes")
    assert user.consent_at is not None and user.onboarding["step"] == "cv"
    assert "PDF" in say(db_session, user, kind="text", text="corto")[0].text  # too short to be a CV
    summary = say(db_session, user, kind="document", filename="cv.pdf", content=b"%PDF")[0]
    assert "Contable" in summary.text and user.onboarding["step"] == "confirm"

    say(db_session, user, kind="press", data="ob:confirm:fix")
    fixed = say(db_session, user, kind="text", text="llevo 3 años")[0]
    assert "3" in fixed.text
    say(db_session, user, kind="press", data="ob:confirm:yes")
    say(db_session, user, kind="press", data="ob:sector:finance")
    say(db_session, user, kind="text", text="Contable")
    say(db_session, user, kind="text", text="Madrid, Barcelona")
    say(db_session, user, kind="press", data="ob:reloc:no")
    say(db_session, user, kind="text", text="28k €")
    done = say(db_session, user, kind="press", data="ob:mode:hybrid")[0]

    assert "Perfil guardado" in done.text and user.status == "ACTIVE"
    assert user.trial_ends_at - user.trial_started_at == timedelta(days=7) and user.onboarding["step"] == "done"
    config = load_profile(db_session, user)
    assert config.preferences.sector == "finance" and config.preferences.preferred_roles == ["Contable"]
    assert config.preferences.acceptable_locations == ["Madrid", "Barcelona"]
    assert config.preferences.minimum_salary == 28000
    assert config.preferences.remote_preference.value == "HYBRID_OR_REMOTE"
    assert config.profile.years_of_experience == 3 and config.profile.languages == ["Spanish", "English"]


def test_refusing_consent_stores_nothing(db_session) -> None:
    _, user = new_user(db_session)
    reply = say(db_session, user, kind="press", data="ob:consent:no")
    assert "no guardo nada" in reply[0].text.lower()
    assert db_session.scalar(select(User).where(User.telegram_chat_id == "100")) is None


def test_a_failing_cv_reader_shows_a_safe_message_and_keeps_the_step(db_session) -> None:
    _, user = new_user(db_session)
    say(db_session, user, kind="press", data="ob:consent:yes")

    def broken(*args):
        raise RuntimeError("provider detail that must not leak")

    reply = handle(db_session, user, Event(kind="document", filename="cv.pdf", content=b"x"), broken, now=NOW)
    assert "no he podido leer" in reply[0].text.lower() and "must not leak" not in reply[0].text
    assert user.onboarding["step"] == "cv"


@pytest.mark.parametrize(
    "text,expected",
    [
        ("30000", ("30000", "EUR", "YEAR")),
        ("30k €", ("30000", "EUR", "YEAR")),
        ("2.500 € al mes", ("2500", "EUR", "MONTH")),
        ("40.000 USD", ("40000", "USD", "YEAR")),
        ("£45,000", ("45000", "GBP", "YEAR")),
    ],
)
def test_salary_is_read_from_free_text(text, expected) -> None:
    parsed = parse_salary(text)
    assert (parsed["amount"], parsed["currency"], parsed["period"]) == expected
    assert parse_salary("mucho") is None


def test_commands_pause_resume_show_data_and_erase_everything(db_session) -> None:
    owner, user = new_user(db_session)
    user.status = "ACTIVE"
    config = build_config({**CV_DRAFT, "sector": "finance"})
    db_session.add(UserProfile(user_id=user.id, sector="finance", config=config.model_dump(mode="json")))
    company = Company(name="Acme")
    job = Job(title="Accountant", company=company)
    db_session.add_all([company, job])
    db_session.flush()
    with acting_as(user.id):
        db_session.add_all([JobReview(job_id=job.id, state="SAVED"), JobFeedbackNote(job_id=job.id, text="me gusta")])
        db_session.flush()
    with acting_as(owner.id):
        db_session.add(JobReview(job_id=job.id, state="DISMISSED"))
        db_session.flush()

    assert "pausado" in handle_command(db_session, user, "/pausa")[0].text.lower() and user.status == "PAUSED"
    assert "reanudado" in handle_command(db_session, user, "/reanudar")[0].text.lower() and user.status == "ACTIVE"
    data = handle_command(db_session, user, "/mis_datos")[0].text
    assert "finance" in data and "votos 1" in data and "notas 1" in data and "No guardo tu CV" in data
    ask = handle_command(db_session, user, "/borrar")[0]
    assert [b.data for row in ask.buttons for b in row] == ["ob:erase:yes", "ob:erase:no"]
    assert "cancelado" in handle_erase_press(db_session, user, "ob:erase:no")[0].text.lower() and user.status == "ACTIVE"

    handle_erase_press(db_session, user, "ob:erase:yes")

    assert user.status == "DELETED" and user.telegram_chat_id is None and user.consent_at is None
    assert db_session.scalar(select(UserProfile).where(UserProfile.user_id == user.id)) is None
    remaining = db_session.scalars(select(JobReview).execution_options(skip_user_scope=True)).all()
    assert [row.user_id for row in remaining] == [owner.id]  # only the owner's vote is left
    assert db_session.scalar(select(JobFeedbackNote.id).execution_options(skip_user_scope=True)) is None
