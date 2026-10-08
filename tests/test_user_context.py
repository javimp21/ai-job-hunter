import pytest

from ai_job_hunter.db.user_context import SKIP_USER_SCOPE, UserContextError, acting_as, current_user_id
from ai_job_hunter.models import Company, Job, JobFeedbackNote, JobReview, User
from sqlalchemy import select


def _user(session, *, owner=False, chat=None) -> User:
    user = User(telegram_chat_id=chat, language="es", timezone="Europe/Madrid", status="ACTIVE", is_owner=owner)
    session.add(user)
    session.flush()
    return user


def _job(session) -> Job:
    company = Company(name="Acme")
    job = Job(title="Backend Engineer", company=company)
    session.add_all([company, job])
    session.flush()
    return job


def test_a_new_row_goes_to_the_only_user_and_stays_unowned_when_there_is_none(db_session) -> None:
    job = _job(db_session)
    first = JobFeedbackNote(job_id=job.id, text="sin usuarios")
    db_session.add(first)
    db_session.flush()
    assert first.user_id is None

    owner = _user(db_session, owner=True)
    second = JobFeedbackNote(job_id=job.id, text="con propietario")
    db_session.add(second)
    db_session.flush()
    assert second.user_id == owner.id


def test_with_several_users_an_unnamed_actor_is_refused_and_a_named_one_owns_its_rows(db_session) -> None:
    job = _job(db_session)
    first, second = _user(db_session, owner=True), _user(db_session, chat="2")
    db_session.add(JobFeedbackNote(job_id=job.id, text="nadie dijo quién"))
    with pytest.raises(UserContextError):
        db_session.flush()
    db_session.rollback()

    job = _job(db_session)
    first, second = _user(db_session, owner=True), _user(db_session, chat="3")
    with acting_as(second.id):
        assert current_user_id() == second.id
        note = JobFeedbackNote(job_id=job.id, text="mía")
        db_session.add(note)
        db_session.flush()
        assert note.user_id == second.id
    assert current_user_id() is None


def test_reads_only_see_the_acting_users_rows_and_maintenance_can_see_all(db_session) -> None:
    job = _job(db_session)
    one, two = _user(db_session, owner=True), _user(db_session, chat="9")
    for user, text in ((one, "de uno"), (two, "de dos")):
        with acting_as(user.id):
            db_session.add(JobFeedbackNote(job_id=job.id, text=text))
            db_session.flush()

    with acting_as(one.id):
        assert [n.text for n in db_session.scalars(select(JobFeedbackNote))] == ["de uno"]
        # joins and counts are scoped too
        assert db_session.scalar(select(JobFeedbackNote.id).join(Job).limit(1)) is not None
    with acting_as(two.id):
        assert [n.text for n in db_session.scalars(select(JobFeedbackNote))] == ["de dos"]
        everything = db_session.scalars(select(JobFeedbackNote).execution_options(**{SKIP_USER_SCOPE: True}))
        assert {n.text for n in everything} == {"de uno", "de dos"}
    assert {n.text for n in db_session.scalars(select(JobFeedbackNote))} == {"de uno", "de dos"}  # nobody acting


def test_shared_tables_are_not_scoped(db_session) -> None:
    owner = _user(db_session, owner=True)
    _job(db_session)
    with acting_as(owner.id):
        assert db_session.scalar(select(Job.id)) is not None
        assert db_session.scalar(select(Company.id)) is not None
        assert db_session.scalar(select(JobReview.id)) is None


def test_activating_the_owner_tolerates_a_database_without_users(tmp_path) -> None:
    from sqlalchemy import create_engine

    from ai_job_hunter.db.user_context import activate_owner

    assert activate_owner(create_engine(f"sqlite+pysqlite:///{(tmp_path / 'empty.sqlite3').as_posix()}")) is None
    assert activate_owner(object()) is None  # not even an engine
    assert current_user_id() is None
