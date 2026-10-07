from datetime import UTC, datetime, timedelta

import pytest
from company_hunter_support import BASE_CV, add_company, add_contact, scripted_client, write_private
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ai_job_hunter.company_hunter.queue import (
    DAILY_LIMIT,
    ConnectionQueueError,
    build_follow_up,
    local_day,
    mark_accepted,
    mark_sent,
    mark_skipped,
    regenerate_note_from_post,
    requests_today,
    contact_relevance,
    suggest_connections,
)
from ai_job_hunter.company_hunter.ranking import rank_companies
from ai_job_hunter.db.base import Base
from ai_job_hunter.models import ConnectionRequest, ConnectionRequestStatus

MONDAY = datetime(2026, 10, 5, 8, 0, tzinfo=UTC)  # 10:00 in Madrid
SATURDAY = datetime(2026, 10, 3, 8, 0, tzinfo=UTC)
NOTE = "Hola, vi lo que hacéis en Acme Pay con Java y Kafka; yo trabajo con Java y Spring Boot en banca. Encantado de conectar."


def setup_people(session, companies=2, per_company=3):
    out = []
    for index in range(companies):
        company = add_company(session, f"Company {index}", website=f"https://c{index}.example.test")
        people = []
        for number in range(per_company):
            people.append(
                add_contact(
                    session, company, f"Person{number} Name{index}", "Backend Engineer", "ENGINEER",
                    source_url=f"https://c{index}.example.test/team",
                )
            )
        out.append((company, people))
    session.commit()
    return out


def run(session, tmp_path, *, now=MONDAY, target=5, note=NOTE, **kwargs):
    cv_dir, style = write_private(tmp_path)
    client, messages = scripted_client(note)
    ranked = rank_companies(session).ranked
    result = suggest_connections(
        session, ranked, client=client, now=now, target=target, cv_dir=cv_dir, style_guide_path=style, **kwargs
    )
    session.commit()
    return result, messages


def test_suggestions_follow_rank_role_priority_and_limits(db_session, tmp_path):
    company = add_company(db_session, "Top Co")
    engineer = add_contact(db_session, company, "Eng Ineer", "Backend Engineer", "ENGINEER")
    lead = add_contact(db_session, company, "Tech Lead", "Tech Lead", "ENGINEER")
    manager = add_contact(db_session, company, "Em Manager", "Engineering Manager", "ENGINEERING_MANAGER")
    add_contact(db_session, company, "Fay Founder", "Founder", "FOUNDER")
    add_contact(db_session, company, "Tal Ent", "Talent Partner", "TALENT")
    db_session.commit()

    result, messages = run(db_session, tmp_path)

    assert [r.contact.name for r in result.new] == ["Tal Ent"]  # recruiter first; 1 per company per day; never the founder
    assert engineer.id not in [r.contact_id for r in result.new] and lead.id not in [r.contact_id for r in result.new]
    assert all(len(r.note) <= 300 and r.status == "SUGGESTED" for r in result.new)
    assert [contact_relevance(c, small_known=False) for c in (manager, lead, engineer)] == [85, 80, 65]


def test_never_more_than_five_per_day_and_second_call_is_idempotent(db_session, tmp_path):
    setup_people(db_session, companies=6, per_company=3)

    first, messages = run(db_session, tmp_path, target=99)
    again, again_messages = run(db_session, tmp_path, target=5, now=MONDAY + timedelta(hours=2))

    assert len(first.new) == DAILY_LIMIT == 5
    assert again.new == [] and len(again.today) == 5 and again_messages.requests == []
    assert "already 5" in again.reason
    assert len(requests_today(db_session, MONDAY)) == 5


def test_weekend_gives_no_suggestions_unless_allowed(db_session, tmp_path):
    setup_people(db_session)

    result, messages = run(db_session, tmp_path, now=SATURDAY)
    assert result.new == [] and "weekend" in result.reason and messages.requests == []

    allowed, _ = run(db_session, tmp_path, now=SATURDAY, allow_weekend=True)
    assert allowed.new


def test_company_is_dropped_after_two_people_were_contacted(db_session, tmp_path):
    (company_a, people_a), (company_b, _people_b) = setup_people(db_session, per_company=4)
    sent = []
    for day in range(2):  # one person per company per day
        batch, _ = run(db_session, tmp_path, now=MONDAY + timedelta(days=day), target=4)
        assert len(batch.new) == 2
        for request in batch.new:
            mark_sent(db_session, request.id, now=MONDAY + timedelta(days=day))
        db_session.commit()
        sent.extend(batch.new)

    third, _ = run(db_session, tmp_path, now=MONDAY + timedelta(days=2), target=5)

    assert {r.company_id for r in sent} == {company_a.id, company_b.id}
    assert third.new == []  # both companies already have 2 contacted people


def test_skip_blocks_a_person_for_sixty_days_then_allows_again(db_session, tmp_path):
    company = add_company(db_session, "Solo Co")
    person = add_contact(db_session, company, "Only One", "Backend Engineer", "ENGINEER")
    db_session.commit()
    first, _ = run(db_session, tmp_path)
    skipped = mark_skipped(db_session, first.new[0].id, now=MONDAY)
    db_session.commit()

    assert skipped.status == "SKIPPED" and skipped.skip_until.replace(tzinfo=UTC) == MONDAY + timedelta(days=60)
    soon, _ = run(db_session, tmp_path, now=MONDAY + timedelta(days=59))
    assert soon.new == []
    later, _ = run(db_session, tmp_path, now=MONDAY + timedelta(days=63))
    assert [r.contact_id for r in later.new] == [person.id]


def test_unanswered_suggestion_is_not_repeated_for_two_weeks(db_session, tmp_path):
    company = add_company(db_session, "Solo Co")
    add_contact(db_session, company, "Only One", "Backend Engineer", "ENGINEER")
    db_session.commit()
    run(db_session, tmp_path)

    assert run(db_session, tmp_path, now=MONDAY + timedelta(days=7))[0].new == []
    assert len(run(db_session, tmp_path, now=MONDAY + timedelta(days=15))[0].new) == 1


def test_excluded_companies_and_contactless_companies_yield_nothing(db_session, tmp_path):
    from ai_job_hunter.models import Application, ApplicationStatus, Job

    company = add_company(db_session, "Applied Co")
    add_contact(db_session, company, "Some One", "Backend Engineer", "ENGINEER")
    job = db_session.query(Job).first()
    db_session.add(Application(job_id=job.id, status=ApplicationStatus.APPLIED.value))
    add_company(db_session, "No Contacts Co")
    db_session.commit()

    result, messages = run(db_session, tmp_path)

    assert result.new == [] and messages.requests == []
    assert "no eligible verified contact" in result.reason


def test_note_failures_skip_the_person_and_are_reported(db_session, tmp_path):
    setup_people(db_session, companies=1, per_company=2)

    result, _ = run(db_session, tmp_path, note="Hola " * 100)

    assert result.new == [] and result.failures and "characters" in result.failures[0]
    assert db_session.query(ConnectionRequest).count() == 0


def test_language_follows_the_contact_and_cv_is_used(db_session, tmp_path):
    company = add_company(db_session, "Lang Co")
    add_contact(db_session, company, "Ana Lopez", "Backend Engineer", "ENGINEER", language="es")
    db_session.commit()

    result, messages = run(db_session, tmp_path)

    assert result.new[0].language == "es"
    assert "Spanish" in messages.requests[0]["system"][0]["text"]
    assert BASE_CV.splitlines()[0] in messages.requests[0]["messages"][0]["content"][0]["text"]


def test_status_flow_sent_accepted_follow_up_and_idempotency(db_session, tmp_path):
    setup_people(db_session, companies=1, per_company=1)
    result, _ = run(db_session, tmp_path)
    request = result.new[0]
    cv_dir, style = write_private(tmp_path)

    sent = mark_sent(db_session, request.id, now=MONDAY)
    assert (sent.status, sent.sent_at) == ("SENT", MONDAY)
    assert mark_sent(db_session, request.id, now=MONDAY + timedelta(days=3)).sent_at == MONDAY  # double tap
    with pytest.raises(ConnectionQueueError):
        mark_skipped(db_session, request.id)

    accepted = mark_accepted(db_session, request.id, now=MONDAY + timedelta(days=2))
    assert accepted.status == "ACCEPTED" and accepted.accepted_at.date() == (MONDAY + timedelta(days=2)).date()

    client, messages = scripted_client("Gracias por aceptar! Me gustó lo de Acme Pay con Java.")
    first = build_follow_up(db_session, request.id, client=client, cv_dir=cv_dir, style_guide_path=style)
    second = build_follow_up(db_session, request.id, client=client, cv_dir=cv_dir, style_guide_path=style)
    assert first == second and len(messages.requests) == 1  # generated once
    assert "ONE line" in messages.requests[0]["system"][0]["text"]
    assert db_session.get(ConnectionRequest, request.id).follow_up_draft == first


def test_post_reply_regenerates_the_note_grounded_in_the_post(db_session, tmp_path):
    setup_people(db_session, companies=1, per_company=1)
    result, _ = run(db_session, tmp_path)
    request = result.new[0]
    cv_dir, style = write_private(tmp_path)
    client, messages = scripted_client("Hola, tu post sobre Kafka y Java en Acme Pay me encantó; trabajo con ambos en banca.")

    updated = regenerate_note_from_post(
        db_session, request.id, "Hoy hablamos de Kafka y Java.", client=client, cv_dir=cv_dir, style_guide_path=style
    )

    assert "post" in updated.note and updated.grounding_post == "Hoy hablamos de Kafka y Java."
    assert "Hoy hablamos de Kafka y Java." in messages.requests[0]["messages"][0]["content"][0]["text"]
    mark_sent(db_session, request.id)
    with pytest.raises(ConnectionQueueError):
        regenerate_note_from_post(db_session, request.id, "x", client=client, cv_dir=cv_dir, style_guide_path=style)


def test_database_rejects_a_note_over_300_characters(db_session):
    company = add_company(db_session)
    contact = add_contact(db_session, company)
    db_session.add(
        ConnectionRequest(
            contact_id=contact.id, company_id=company.id, language="en", note="x" * 301,
            status=ConnectionRequestStatus.SUGGESTED.value, suggested_at=MONDAY,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.flush()


def test_pipeline_survives_a_restart(tmp_path):
    database = tmp_path / "hunter.sqlite3"
    engine = create_engine(f"sqlite+pysqlite:///{database.as_posix()}")
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        setup_people(session, companies=1, per_company=1)
        result, _ = run(session, tmp_path)
        request_id = result.new[0].id
        mark_sent(session, request_id, now=MONDAY)
        session.commit()
    engine.dispose()

    reopened = create_engine(f"sqlite+pysqlite:///{database.as_posix()}")
    with Session(reopened) as session:
        row = session.get(ConnectionRequest, request_id)
        assert (row.status, row.note, row.suggested_at.date()) == ("SENT", NOTE, MONDAY.date())
        assert row.sent_at is not None and row.contact.name.startswith("Person0")
        assert local_day(row.suggested_at) == "2026-10-05"
        second, messages = run(session, tmp_path, now=MONDAY + timedelta(hours=3))
        assert second.new == [] and messages.requests == []
    reopened.dispose()


def test_skipping_one_person_pauses_the_whole_company_for_two_weeks(db_session, tmp_path):
    company = add_company(db_session, "Twin Co")
    add_contact(db_session, company, "First Person", "Backend Engineer", "ENGINEER")
    add_contact(db_session, company, "Second Person", "Engineering Manager", "ENGINEERING_MANAGER")
    db_session.commit()
    first, _ = run(db_session, tmp_path)
    mark_skipped(db_session, first.new[0].id, now=MONDAY)
    db_session.commit()

    assert run(db_session, tmp_path, now=MONDAY + timedelta(days=1))[0].new == []
    assert run(db_session, tmp_path, now=MONDAY + timedelta(days=13))[0].new == []
    later, _ = run(db_session, tmp_path, now=MONDAY + timedelta(days=15))
    assert len(later.new) == 1 and later.new[0].contact_id != first.new[0].contact_id
