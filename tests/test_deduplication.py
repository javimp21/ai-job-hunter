from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from ai_job_hunter.deduplication.matcher import (
    DeduplicationDecision,
    match_job,
)
from ai_job_hunter.deduplication.normalization import (
    extract_company_domain,
    is_job_specific_url,
    normalize_company_name,
    normalize_job_title,
    normalize_job_url,
)
from ai_job_hunter.domain.normalized_job import NormalizedJob
from ai_job_hunter.models import Company, Job, JobSource
from ai_job_hunter.services.ingestion import IngestionStatus, ingest_job


def make_offer(**overrides: object) -> NormalizedJob:
    values: dict[str, object] = {
        "provider": "first-board",
        "external_id": "role-1",
        "title": "Backend Engineer",
        "company_name": "Acme",
        "company_website": "https://acme.example.test",
        "location": "Madrid, Spain",
        "discovered_at": datetime(2026, 9, 24, 10, tzinfo=UTC),
    }
    values.update(overrides)
    return NormalizedJob.model_validate(values)


@pytest.mark.parametrize(
    "name",
    ["Acme", "ACME", "Acme Inc.", "Acme, Inc.", "Acme Ltd", "Acme S.L."],
)
def test_company_normalization_removes_only_known_terminal_legal_forms(name: str) -> None:
    assert normalize_company_name(name) == "acme"


def test_company_normalization_preserves_business_name_terms() -> None:
    assert normalize_company_name("Acme Technologies") == "acme technologies"
    assert normalize_company_name("Acme Technologies") != normalize_company_name("Acme")


def test_company_domain_is_exact_hostname_without_scheme_www_or_port() -> None:
    assert extract_company_domain("https://www.acme.example:443/careers") == "acme.example"
    assert extract_company_domain("jobs.acme.example") == "jobs.acme.example"


def test_title_normalization_removes_common_context_but_preserves_seniority() -> None:
    base = normalize_job_title("Backend Engineer")
    assert normalize_job_title("Backend Engineer (Remote)") == base
    assert normalize_job_title("Backend Engineer - Spain") == base
    assert normalize_job_title("Senior Backend Engineer").seniority == frozenset({"senior"})
    assert normalize_job_title("Backend Engineer").seniority != frozenset({"senior"})


def test_title_normalization_uses_small_developer_alias() -> None:
    assert normalize_job_title("Backend Developer") == normalize_job_title("Backend Engineer")


def test_job_url_normalization_drops_tracking_and_non_specific_pages() -> None:
    left = "http://www.greenhouse.io/acme/jobs/12345?utm_source=linkedin&gh_src=abc"
    right = "https://greenhouse.io/acme/jobs/12345"
    assert normalize_job_url(left) == normalize_job_url(right)
    assert is_job_specific_url(left)
    assert not is_job_specific_url("https://acme.example/careers")


def test_cross_source_strong_url_reuses_job_without_external_id(db_session) -> None:
    first = make_offer(
        provider="greenhouse",
        external_id=None,
        title="Backend Engineer",
        canonical_url="https://boards.greenhouse.io/acme/jobs/12345",
    )
    second = make_offer(
        provider="linkedin",
        external_id=None,
        source_url="https://www.linkedin.com/jobs/view/backend-engineer",
        title="Backend Software Engineer",
        company_name="ACME, Inc.",
        canonical_url="http://boards.greenhouse.io/acme/jobs/12345?utm_source=linkedin",
    )

    created = ingest_job(db_session, first)
    matched = ingest_job(db_session, second)

    assert created.status is IngestionStatus.CREATED
    assert matched.status is IngestionStatus.MATCHED_EXISTING
    assert matched.job_id == created.job_id
    assert matched.deduplication is not None
    assert matched.deduplication.decision is DeduplicationDecision.MATCH
    assert "same job-specific canonical_url" in matched.deduplication.reasons
    assert db_session.scalar(select(func.count()).select_from(Job)) == 1
    assert db_session.scalar(select(func.count()).select_from(JobSource)) == 2
    assert db_session.scalar(select(func.count()).select_from(Company)) == 1


def test_same_company_and_similar_title_without_strong_evidence_is_possible_only(db_session) -> None:
    created = ingest_job(db_session, make_offer())
    incoming = make_offer(
        provider="another-board",
        external_id="role-2",
        source_url="https://acme.example.test/careers",
        title="Backend Software Engineer",
    )

    result = ingest_job(db_session, incoming)

    assert result.status is IngestionStatus.POSSIBLE_MATCH
    assert result.job_id != created.job_id
    assert len(result.possible_matches) == 1
    assert result.possible_matches[0].decision is DeduplicationDecision.POSSIBLE_MATCH
    assert db_session.scalar(select(func.count()).select_from(Job)) == 2


def test_seniority_difference_is_no_match_and_never_auto_merges(db_session) -> None:
    created = ingest_job(db_session, make_offer())
    result = ingest_job(
        db_session,
        make_offer(provider="second-board", external_id="role-2", title="Senior Backend Engineer"),
    )

    assert result.status is IngestionStatus.CREATED
    assert not result.possible_matches
    assert result.job_id != created.job_id
    assert db_session.scalar(select(func.count()).select_from(Job)) == 2


def test_unrelated_roles_at_same_company_are_no_match(db_session) -> None:
    created = ingest_job(db_session, make_offer(title="Software Engineer"))
    incoming = make_offer(
        provider="second-board",
        external_id="role-2",
        title="Engineering Manager",
    )

    result = ingest_job(db_session, incoming)

    assert result.status is IngestionStatus.CREATED
    assert result.job_id != created.job_id
    assert db_session.scalar(select(func.count()).select_from(Job)) == 2


def test_different_job_specific_urls_prove_same_title_can_be_distinct(db_session) -> None:
    created = ingest_job(
        db_session,
        make_offer(canonical_url="https://jobs.acme.example/jobs/backend-1"),
    )
    result = ingest_job(
        db_session,
        make_offer(
            provider="second-board",
            external_id="role-2",
            canonical_url="https://jobs.acme.example/jobs/backend-2",
        ),
    )

    assert result.status is IngestionStatus.CREATED
    assert result.job_id != created.job_id
    assert db_session.scalar(select(func.count()).select_from(Job)) == 2


def test_different_companies_with_same_title_stay_separate(db_session) -> None:
    first = ingest_job(db_session, make_offer())
    second = ingest_job(
        db_session,
        make_offer(
            provider="second-board",
            external_id="role-2",
            company_name="Other Company",
            company_website="https://other.example.test",
        ),
    )

    assert first.job_id != second.job_id
    assert second.status is IngestionStatus.CREATED
    assert db_session.scalar(select(func.count()).select_from(Job)) == 2
    assert db_session.scalar(select(func.count()).select_from(Company)) == 2


def test_normalized_legal_company_names_reuse_company_but_not_job(db_session) -> None:
    first = ingest_job(db_session, make_offer())
    second = ingest_job(
        db_session,
        make_offer(provider="second-board", external_id="role-2", company_name="Acme Inc."),
    )

    assert first.company_id == second.company_id
    assert first.job_id != second.job_id
    assert db_session.scalar(select(func.count()).select_from(Company)) == 1


def test_matching_company_domain_is_explanatory_evidence(db_session) -> None:
    created = ingest_job(db_session, make_offer())
    candidate = db_session.scalar(select(Job).where(Job.id == created.job_id))
    assert candidate is not None

    result = match_job(
        make_offer(
            provider="second-board",
            external_id="role-2",
            company_name="Acme Holdings",
        ),
        candidate,
    )

    assert result.decision is DeduplicationDecision.POSSIBLE_MATCH
    assert result.signals.company_domain_match is True
    assert "same company website domain" in result.reasons


def test_known_canonical_fields_are_not_overwritten_by_secondary_source(db_session) -> None:
    first = ingest_job(
        db_session,
        make_offer(
            canonical_url="https://jobs.acme.example/jobs/backend-1",
            description="Complete description from the original posting.",
            remote_policy="REMOTE",
        ),
    )
    result = ingest_job(
        db_session,
        make_offer(
            provider="second-board",
            external_id="role-2",
            title="Backend Software Engineer",
            canonical_url="https://jobs.acme.example/jobs/backend-1",
            description="Short summary.",
        ),
    )

    assert result.status is IngestionStatus.MATCHED_EXISTING
    job = db_session.get(Job, first.job_id)
    assert job is not None
    assert job.title == "Backend Engineer"
    assert job.description == "Complete description from the original posting."
    assert job.location == "Madrid, Spain"
    assert job.remote_policy == "REMOTE"


def test_match_result_explains_seniority_conflict(db_session) -> None:
    created = ingest_job(db_session, make_offer())
    candidate = db_session.scalar(select(Job).where(Job.id == created.job_id))
    assert candidate is not None

    result = match_job(
        make_offer(provider="second-board", title="Senior Backend Engineer"),
        candidate,
    )

    assert result.decision is DeduplicationDecision.NO_MATCH
    assert "seniority differs (incoming: senior; existing: unspecified)" in result.reasons


def test_explicit_onsite_remote_conflict_blocks_strong_url_merge(db_session) -> None:
    created = ingest_job(
        db_session,
        make_offer(
            canonical_url="https://jobs.acme.example/jobs/backend-1",
            remote_policy="ONSITE",
        ),
    )
    candidate = db_session.scalar(select(Job).where(Job.id == created.job_id))
    assert candidate is not None

    result = match_job(
        make_offer(
            provider="second-board",
            external_id="role-2",
            canonical_url="https://jobs.acme.example/jobs/backend-1",
            remote_policy="REMOTE",
        ),
        candidate,
    )

    assert result.signals.stable_url_match == "canonical_url"
    assert result.signals.remote_policy_conflict is True
    assert result.decision is DeduplicationDecision.NO_MATCH
    assert "explicit onsite/remote policies conflict" in result.reasons


def test_publication_and_compatible_salary_are_secondary_explanation_signals(db_session) -> None:
    created = ingest_job(
        db_session,
        make_offer(
            published_at=datetime(2026, 9, 1, tzinfo=UTC),
            salary_min="50000",
            salary_max="70000",
            currency="EUR",
            salary_period="YEAR",
        ),
    )
    candidate = db_session.scalar(select(Job).where(Job.id == created.job_id))
    assert candidate is not None

    incoming = make_offer(
        provider="second-board",
        external_id="role-2",
        published_at=datetime(2026, 9, 15, tzinfo=UTC),
        salary_min="60000",
        salary_max="80000",
        currency="EUR",
        salary_period="YEAR",
    )
    result = match_job(incoming, candidate)

    assert result.signals.published_within_14_days is True
    assert result.signals.salary_ranges_overlap is True
    assert "publication dates are within 14 days" in result.reasons
    assert "salary ranges overlap" in result.reasons

    incompatible_salary = make_offer(
        provider="third-board",
        external_id="role-3",
        salary_min="60000",
        salary_max="80000",
        currency="USD",
        salary_period="YEAR",
    )
    assert match_job(incompatible_salary, candidate).signals.salary_ranges_overlap is None
