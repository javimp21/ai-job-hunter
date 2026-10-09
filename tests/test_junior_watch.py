from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from test_remote_spain import add_offer  # noqa: F401

from ai_job_hunter.candidates import CandidateConfig, CandidateProfile
from ai_job_hunter.models import HumanReviewStatus, JobReview
from ai_job_hunter.services import junior_watch
from ai_job_hunter.services.notifications import TelegramSendResult

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)


def candidate(*countries, **preferences):
    return CandidateConfig(
        profile=CandidateProfile(), preferences=preferences, tuning={"junior_watch_countries": list(countries)}
    )


def offer(session, title, location, **kwargs):
    job = add_offer(session, title, **kwargs)
    for source in job.sources:
        source.source_location = location
    session.flush()
    return job


def test_new_junior_postings_in_the_watched_countries_are_listed_without_students_or_local_language(db_session, tmp_path) -> None:
    offer(db_session, "Junior Software Engineer", "Dublin, Ireland", company="Alpha")
    offer(db_session, "Graduate Backend Developer", "Amsterdam, NL", company="Beta")
    offer(db_session, "Junior Software Developer", "Berlin", company="Gamma", description="Fluent German is required.")
    offer(db_session, "Working Student Software Engineer", "Berlin", company="Delta")
    offer(db_session, "Junior Software Engineer", "Madrid, Spain", company="Spain")  # not a watched country
    offer(db_session, "Senior Software Engineer", "Dublin", company="Senior")  # not junior
    offer(db_session, "Junior Account Executive", "Dublin", company="Sales")  # not technical
    offer(db_session, "Junior Software Engineer", "Dublin", company="Old", found=NOW - timedelta(days=30))

    lines = junior_watch.collect(
        db_session, candidate("Ireland", "Netherlands", "Germany"), now=NOW, state_path=tmp_path / "seen.json"
    )

    assert sorted(line.company for line in lines) == ["Alpha", "Beta"]


def test_each_posting_is_announced_once_and_a_failed_send_remembers_nothing(db_session, tmp_path) -> None:
    offer(db_session, "Junior Software Engineer", "Dublin, Ireland", company="Alpha", url="https://example.test/a?utm=1")
    sent: list[str] = []
    state = tmp_path / "seen.json"
    good = SimpleNamespace(send_message=lambda text, **kw: sent.append(text) or TelegramSendResult(message_id="1"))
    bad = SimpleNamespace(send_message=lambda text, **kw: (_ for _ in ()).throw(RuntimeError("down")))

    assert junior_watch.send(db_session, candidate("Ireland"), bad, now=NOW, state_path=state) == "failed"
    assert junior_watch.send(db_session, candidate("Ireland"), good, now=NOW, state_path=state) == "sent"
    assert junior_watch.send(db_session, candidate("Ireland"), good, now=NOW, state_path=state) == "empty"
    assert len(sent) == 1 and "Junior Software Engineer" in sent[0] and "Alpha" in sent[0] and "Irlanda" not in sent[0]
    assert junior_watch.send(db_session, candidate(), good, now=NOW, state_path=state) == "off"


def test_dismissed_and_excluded_postings_are_left_out(db_session, tmp_path) -> None:
    job = offer(db_session, "Junior Software Engineer", "Dublin", company="Seen")
    db_session.add(JobReview(job_id=job.id, state=HumanReviewStatus.DISMISSED.value))
    offer(db_session, "Junior Full Stack Developer", "Dublin", company="Fullco")
    offer(db_session, "Junior Software Engineer", "Dublin", company="Fine")

    lines = junior_watch.collect(
        db_session, candidate("Ireland", excluded_title_terms=["full stack"]), now=NOW, state_path=tmp_path / "s.json"
    )

    assert [line.company for line in lines] == ["Fine"]
