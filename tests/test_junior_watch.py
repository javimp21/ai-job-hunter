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
    offer(db_session, "Associate Solutions Engineer", "Dublin", company="Presales")  # technical but not one of the roles
    offer(db_session, "Junior Data Analyst", "Amsterdam", company="Analyst")
    offer(db_session, "Junior Java Backend Developer (m/w/d)", "Zurich", company="Swiss")
    offer(db_session, "Graduate Full-Stack Engineer", "Stockholm", company="Nordic")
    offer(db_session, "Junior Software Engineer", "Dublin", company="Old", found=NOW - timedelta(days=30))

    lines = junior_watch.collect(
        db_session, candidate("Ireland", "Netherlands", "Germany", "Switzerland", "Sweden"), now=NOW,
        state_path=tmp_path / "seen.json",
    )

    assert sorted(line.company for line in lines) == ["Alpha", "Beta", "Nordic", "Swiss"]


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


def qa_candidate(*countries):
    return CandidateConfig(profile=CandidateProfile(), tuning={"qa_watch_countries": list(countries)})


def test_qa_and_test_automation_postings_are_listed_for_any_level_but_senior_in_the_qa_countries(db_session, tmp_path) -> None:
    offer(db_session, "QA Automation Engineer", "Madrid, Spain", company="Mad")
    offer(db_session, "Test Automation Engineer (Java)", "Barcelona", company="Bcn")
    offer(db_session, "Software Development Engineer in Test", "Dublin", company="Dub")
    offer(db_session, "Senior QA Automation Engineer", "Madrid", company="Senior")
    offer(db_session, "QA Engineer", "Madrid", company="Years", description="Requires 5+ years of experience in testing.")
    offer(db_session, "QA Automation Engineer", "Paris, France", company="Elsewhere")  # not a QA country
    offer(db_session, "Quality Assurance Intern", "Madrid", company="Intern")
    offer(db_session, "QA Engineer", "Berlin", company="German", description="Fluent German is required.")

    lines = junior_watch.collect(db_session, qa_candidate("Spain", "Ireland", "Germany"), now=NOW, state_path=tmp_path / "s.json")

    assert sorted(line.company for line in lines) == ["Bcn", "Dub", "Mad"] and {line.kind for line in lines} == {"qa"}


def test_one_message_lists_both_kinds_under_their_own_headings(db_session, tmp_path) -> None:
    offer(db_session, "Junior Software Engineer", "Dublin", company="Alpha")
    offer(db_session, "QA Automation Engineer", "Madrid", company="Beta")
    both = CandidateConfig(
        profile=CandidateProfile(), tuning={"junior_watch_countries": ["Ireland"], "qa_watch_countries": ["Spain"]}
    )
    sent: list[str] = []
    provider = SimpleNamespace(send_message=lambda text, **kw: sent.append(text) or TelegramSendResult(message_id="1"))

    assert junior_watch.send(db_session, both, provider, now=NOW, state_path=tmp_path / "s.json") == "sent"

    assert "Nivel junior nuevo en Ireland: 1" in sent[0] and "QA / automatización de pruebas nuevo: 1" in sent[0]
    assert sent[0].index("Alpha") < sent[0].index("Beta")
