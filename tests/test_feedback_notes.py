from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from ai_job_hunter.models import Company, Job, JobReview, OpportunityNotification
from ai_job_hunter.services.feedback_notes import MAX_NOTE_CHARS, add_note, job_for_alert_message, list_notes


def _job(session) -> Job:
    company = Company(name="Acme")
    job = Job(title="Backend Engineer", company=company)
    session.add_all([company, job])
    session.flush()
    return job


def test_a_note_keeps_the_vote_the_job_had_and_is_capped(db_session) -> None:
    job = _job(db_session)
    first = add_note(db_session, job.id, "  Me gusta el stack, pero piden demasiada experiencia.  ")
    assert first is not None and first.vote is None and first.text.startswith("Me gusta")

    db_session.add(JobReview(job_id=job.id, state="DISMISSED"))
    db_session.flush()
    second = add_note(db_session, job.id, "x" * (MAX_NOTE_CHARS + 500))
    assert second.vote == "DISMISSED" and len(second.text) == MAX_NOTE_CHARS
    assert add_note(db_session, job.id, "   ") is None
    assert {note.id for note in list_notes(db_session)} == {first.id, second.id}


def test_an_alert_is_found_by_its_telegram_message_id(db_session) -> None:
    job = _job(db_session)
    db_session.add(
        OpportunityNotification(
            job_id=job.id, evaluation_fingerprint="f", channel="TELEGRAM", decision="REVIEW", priority=80,
            status="SENT", message="m", provider_message_id="4321",
        )
    )
    db_session.flush()

    assert job_for_alert_message(db_session, 4321) == job.id
    assert job_for_alert_message(db_session, 1) is None


def test_migration_0016_creates_the_notes_table_and_can_be_undone(tmp_path: Path, monkeypatch, keep_logging_state) -> None:
    repo_root = Path(__file__).parents[1]
    url = f"sqlite+pysqlite:///{(tmp_path / 'notes.sqlite3').as_posix()}"
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config(str(repo_root / "alembic.ini"))
    config.set_main_option("script_location", str(repo_root / "alembic"))
    command.upgrade(config, "head")
    assert {"job_id", "text", "vote"} <= {c["name"] for c in inspect(create_engine(url)).get_columns("job_feedback_notes")}
    command.downgrade(config, "0015_users_and_profiles")
    assert "job_feedback_notes" not in inspect(create_engine(url)).get_table_names()


def test_the_bots_question_after_a_vote_is_remembered_in_the_database_per_person(db_session) -> None:
    from ai_job_hunter.db.user_context import acting_as
    from ai_job_hunter.models import Company, Job, User
    from ai_job_hunter.services.feedback_notes import DbPrompts

    job = Job(title="Backend Engineer", company=Company(name="Acme"))
    one, two = User(telegram_chat_id="1", status="ACTIVE", is_owner=True), User(telegram_chat_id="2", status="ACTIVE")
    db_session.add_all([job, one, two])
    db_session.flush()
    job_id, one_id, two_id = job.id, one.id, two.id  # the store closes its session, which detaches these objects

    with acting_as(one_id):
        DbPrompts(lambda: db_session)[500] = job_id
        DbPrompts(lambda: db_session)[500] = job_id  # asking twice never duplicates the row
        assert DbPrompts(lambda: db_session).get(500) == job_id  # a new object: what a restart looks like
        assert DbPrompts(lambda: db_session).get(501) is None
    with acting_as(two_id):
        assert DbPrompts(lambda: db_session).get(500) is None  # somebody else's question
