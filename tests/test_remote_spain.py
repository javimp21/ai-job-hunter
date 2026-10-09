from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from ai_job_hunter.candidates import CandidateConfig, CandidateProfile
from ai_job_hunter.models import Company, HumanReviewStatus, Job, JobReview, JobSource
from ai_job_hunter.services import remote_spain
from ai_job_hunter.services.notifications import TelegramSendResult

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)


def add_offer(session, title, *, eligibility="WORLDWIDE", remote="REMOTE", company="Acme", description="", salary=None,
              found=NOW - timedelta(days=1), closed=None, url="https://example.test/job"):
    row = Company(name=company)
    job = Job(title=title, company=row, description=description)
    session.add_all([row, job])
    session.flush()
    low, high = salary or (None, None)
    session.add(JobSource(
        job_id=job.id, provider="greenhouse", external_id=f"{company}-{title}", source_title=title, source_description=description,
        remote_policy=remote, remote_eligibility=eligibility, salary_min=low, salary_max=high, salary_currency="USD" if low else None,
        salary_period="YEAR" if low else None, discovered_at=found, closed_at=closed, apply_url=url,
    ))
    session.flush()
    return job


def candidate(**preferences):
    return CandidateConfig(profile=CandidateProfile(), preferences=preferences)


def test_only_open_remote_offers_that_accept_spain_in_the_role_family_are_listed_best_paid_first(db_session) -> None:
    add_offer(db_session, "Senior Backend Engineer", description="We need 5+ years of experience.", salary=(Decimal("120000"), Decimal("160000")))
    add_offer(db_session, "Backend Developer", eligibility="SPAIN_ONLY", description="1 years", company="Beta")
    add_offer(db_session, "Backend Engineer", eligibility="COUNTRY_RESTRICTED", company="Gamma")  # not open to Spain
    add_offer(db_session, "Backend Engineer", eligibility="UNKNOWN", company="Delta")  # unknown stays out
    add_offer(db_session, "Backend Engineer", remote="ONSITE", company="Eps")
    add_offer(db_session, "Backend Engineer", closed=NOW - timedelta(hours=2), company="Closed")
    add_offer(db_session, "Backend Engineer", found=NOW - timedelta(days=30), company="Old")
    add_offer(db_session, "Account Executive", company="Sales")  # another role family

    lines = remote_spain.collect(db_session, candidate(), now=NOW)

    assert [(line.title, line.company) for line in lines] == [("Senior Backend Engineer", "Acme"), ("Backend Developer", "Beta")]
    first = lines[0]
    assert first.years == 5 and first.salary == "120k–160k USD" and first.worldwide
    assert lines[1].years == 1 and not lines[1].worldwide and lines[1].salary is None


def test_dismissed_and_excluded_offers_are_left_out(db_session) -> None:
    dismissed = add_offer(db_session, "Backend Engineer", company="Seen")
    db_session.add(JobReview(job_id=dismissed.id, state=HumanReviewStatus.DISMISSED.value))
    add_offer(db_session, "Full Stack Engineer", company="Fullco")
    add_offer(db_session, "Backend Engineer", company="Blocked")
    add_offer(db_session, "Platform Engineer", company="Fine")

    lines = remote_spain.collect(
        db_session, candidate(excluded_title_terms=["full stack"], excluded_companies=["Blocked"]), now=NOW
    )

    assert [line.company for line in lines] == ["Fine"]


def test_the_message_escapes_text_and_is_sent_at_most_every_six_days(db_session) -> None:
    add_offer(db_session, "Backend <Engineer> & Co", company="A&B", url="https://example.test/a?x=1&y=2")
    sent: list[str] = []
    provider = SimpleNamespace(send_message=lambda text, **kw: sent.append(text) or TelegramSendResult(message_id="9"))

    assert remote_spain.send(db_session, candidate(), provider, now=NOW) == "sent"
    assert "&lt;Engineer&gt; &amp; Co" in sent[0] and "A&amp;B" in sent[0] and 'href="https://example.test/a"' in sent[0]  # the link keeps no query string
    assert remote_spain.send(db_session, candidate(), provider, now=NOW + timedelta(days=2)) == "too_soon"
    add_offer(db_session, "Backend Engineer", company="Later", found=NOW + timedelta(days=6))
    assert remote_spain.send(db_session, candidate(), provider, now=NOW + timedelta(days=7)) == "sent" and len(sent) == 2


def test_nothing_is_sent_when_there_is_nothing_new(db_session) -> None:
    provider = SimpleNamespace(send_message=lambda text, **kw: (_ for _ in ()).throw(AssertionError("no message expected")))
    assert remote_spain.send(db_session, candidate(), provider, now=NOW) == "empty"
