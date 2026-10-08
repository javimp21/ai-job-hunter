from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from ai_job_hunter.models import Company, Job
from ai_job_hunter.services.feedback_notes import add_note
from ai_job_hunter.services.feedback_review import build_request, collect_notes, mark_reviewed, review_notes


class FakeClaude:
    def __init__(self, text="Lo que se repite: stack Angular (2 notas).", fail=False):
        self.requests = []
        self.messages = SimpleNamespace(create=self._create)
        self._text, self._fail = text, fail

    def _create(self, **request):
        self.requests.append(request)
        if self._fail:
            raise RuntimeError("provider detail that must not leak")
        return SimpleNamespace(content=[SimpleNamespace(type="text", text=self._text)])


def _jobs(session, count):
    company = Company(name="Acme")
    jobs = [Job(title=f"Backend Engineer {i}", company=company, location="Madrid", description="Java and Angular.") for i in range(count)]
    session.add_all([company, *jobs])
    session.flush()
    return jobs


def test_too_few_notes_spend_nothing(db_session) -> None:
    jobs = _jobs(db_session, 2)
    for job in jobs:
        add_note(db_session, job.id, "Demasiado Angular")
    client = FakeClaude()

    result = review_notes(db_session, tuning_summary="x", min_notes=5, client=client)

    assert result.status == "not_enough_notes" and result.notes == 2 and client.requests == []


def test_the_notes_with_their_offers_go_to_claude_and_nothing_is_recorded_until_delivery(db_session) -> None:
    jobs = _jobs(db_session, 5)
    for index, job in enumerate(jobs):
        add_note(db_session, job.id, f"Piden Angular, no me gusta {index}")
    client = FakeClaude()

    result = review_notes(db_session, tuning_summary="alert bar 80", min_notes=5, client=client)

    assert result.status == "reviewed" and result.notes == 5
    assert "5 notas" in result.message and "No he cambiado nada" in result.message
    request = client.requests[0]
    body = request["messages"][0]["content"]
    assert "Piden Angular, no me gusta 0" in body and "Backend Engineer 3 @ Acme" in body and "alert bar 80" in body
    assert "never invent" in request["system"].lower() or "Never invent" in request["system"]
    # not marked yet: the same notes would be evaluated again if delivery failed
    assert review_notes(db_session, tuning_summary="x", min_notes=5, client=FakeClaude()).status == "reviewed"

    mark_reviewed(db_session, now=datetime.now(UTC) + timedelta(seconds=5))
    assert review_notes(db_session, tuning_summary="x", min_notes=5, client=FakeClaude()).status == "not_enough_notes"


def test_a_failing_provider_is_reported_without_its_details(db_session) -> None:
    for job in _jobs(db_session, 5):
        add_note(db_session, job.id, "opinión")

    result = review_notes(db_session, tuning_summary="x", min_notes=5, client=FakeClaude(fail=True))

    assert result.status == "failed" and result.message is None


def test_collect_notes_caps_the_batch_and_orders_newest_first(db_session) -> None:
    for job in _jobs(db_session, 3):
        add_note(db_session, job.id, "n")
    assert len(collect_notes(db_session, since=None, limit=2)) == 2
    assert "Notes: 3" in build_request(collect_notes(db_session, since=None), "t")["messages"][0]["content"]
