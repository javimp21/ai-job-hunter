from datetime import UTC, datetime
from pathlib import Path
import subprocess

import pytest

from ai_job_hunter.candidates import load_candidate_config
from ai_job_hunter.decision_engine import POLICY_VERSION_V2, RUBRIC_VERSION, FinalDecision
from ai_job_hunter.models import (
    Application,
    ApplicationStatus,
    Company,
    EvaluationStatus,
    Job,
    JobEvaluation,
    JobSource,
    OutreachChannel,
    OutreachPurpose,
    OutreachStatus,
)
from ai_job_hunter.outreach import OutreachRecommendation
from ai_job_hunter.outreach.projects import CandidateProject
from ai_job_hunter.services import opportunities
from ai_job_hunter.services.opportunities import list_opportunities
from ai_job_hunter.services.outreach_persistence import (
    create_outreach,
    transition_outreach,
)
from ai_job_hunter.services.outreach_workflow import create_initial_outreach_drafts


ROOT = Path(__file__).parents[1]
CANDIDATE = ROOT / "config" / "examples" / "candidate.example.json"


def _persist_evaluated_job(session, *, decision: FinalDecision, role: float = 0.9):
    candidate = load_candidate_config(CANDIDATE)
    company = Company(name="Acme", website_url="https://acme.example.test")
    job = Job(
        company=company,
        title="Backend Engineer",
        description="Minimum 0 years of professional experience required. Build backend APIs using Python and PostgreSQL.",
        location="Madrid, Spain",
        remote_policy="REMOTE",
    )
    source = JobSource(
        job=job,
        provider="greenhouse",
        external_id="backend-role",
        original_url="https://boards.greenhouse.io/acme/jobs/backend-role",
        canonical_url="https://boards.greenhouse.io/acme/jobs/backend-role",
        apply_url="https://boards.greenhouse.io/acme/jobs/backend-role/apply",
        company_website=company.website_url,
        source_title=job.title,
        source_description=job.description,
        source_location=job.location,
        remote_policy="REMOTE",
        remote_eligibility="SPAIN_ONLY",
        employment_type="FULL_TIME",
    )
    session.add(source)
    session.flush()

    identity = opportunities._engine_identity(None)
    prepared = opportunities._prepare_from_source(job, source, candidate, identity)
    assert prepared is not None
    values = {
        "role_relevance": role,
        "backend_relevance": 0.85,
        "stack_transferability": 0.8,
        "experience_accessibility": 0.8,
        "requirements_flexibility": 0.8,
        "career_value": 0.8,
    }
    session.add(
        JobEvaluation(
            job=job,
            evaluation_fingerprint=prepared.fingerprint,
            status=EvaluationStatus.EVALUATED.value,
            decision=decision.value,
            rubric_version=RUBRIC_VERSION,
            policy_version=POLICY_VERSION_V2,
            engine_name="offline-fixture",
            config_fingerprint=opportunities._config_fingerprint(candidate, identity),
            deterministic_result={
                "decision": "PASS",
                "signals": {"technology": {"critical_mismatches": []}},
            },
            jev_signals={name: {"value": value} for name, value in values.items()},
            jev_reasons={},
            evaluated_at=datetime(2026, 9, 1, tzinfo=UTC),
        )
    )
    session.flush()
    return candidate, company, job


def test_opportunity_feed_adds_recommendation_and_suppresses_application_or_active_outreach(
    db_session,
) -> None:
    candidate, company, job = _persist_evaluated_job(db_session, decision=FinalDecision.APPLY)

    row = list_opportunities(db_session, candidate)[0]
    assert row.outreach_recommendation is OutreachRecommendation.OUTREACH_RECOMMENDED

    duplicate = create_outreach(
        db_session,
        company_id=company.id,
        job_id=job.id,
        purpose=OutreachPurpose.RECRUITER_INTRO,
        channel=OutreachChannel.LINKEDIN,
        recipient_contact_type="RECRUITER",
        body="Example local draft body.",
    )
    assert duplicate.created
    db_session.flush()
    with_active_outreach = list_opportunities(db_session, candidate)[0]
    assert with_active_outreach.outreach_recommendation is OutreachRecommendation.NO_OUTREACH

    transition_outreach(
        db_session,
        duplicate.outreach.id,
        OutreachStatus.CANCELLED,
    )
    db_session.flush()
    db_session.add(Application(job=job, status=ApplicationStatus.APPLIED.value))
    db_session.flush()
    with_application = list_opportunities(db_session, candidate, include_applied=True)[0]
    assert with_application.outreach_recommendation is OutreachRecommendation.NO_OUTREACH


def test_high_priority_review_has_no_outreach_recommendation_in_feed(db_session) -> None:
    candidate, _company, _job = _persist_evaluated_job(
        db_session,
        decision=FinalDecision.REVIEW,
        role=0.8,
    )

    row = list_opportunities(db_session, candidate)[0]
    assert row.priority >= 70
    assert row.outreach_recommendation is OutreachRecommendation.NO_OUTREACH


def test_job_draft_workflow_creates_placeholder_drafts_and_reuses_them(
    db_session, tmp_path
) -> None:
    candidate, _company, job = _persist_evaluated_job(db_session, decision=FinalDecision.APPLY)

    first = create_initial_outreach_drafts(
        db_session,
        job.id,
        candidate,
        projects_path=tmp_path / "missing-projects.local.json",
    )
    assert len(first) == 2
    assert all(result.created for result in first)
    assert all(result.outreach.status == OutreachStatus.DRAFT.value for result in first)
    assert all(result.outreach.contact_id is None for result in first)
    assert {result.outreach.recipient_contact_type for result in first} == {
        "RECRUITER",
        "ENGINEER",
    }

    second = create_initial_outreach_drafts(
        db_session,
        job.id,
        candidate,
        projects_path=tmp_path / "missing-projects.local.json",
    )
    assert len(second) == 2
    assert all(not result.created for result in second)
    assert {result.outreach.id for result in first} == {result.outreach.id for result in second}


def test_no_send_command_is_registered(capsys) -> None:
    from ai_job_hunter.cli import main

    with pytest.raises(SystemExit) as error:
        main(["outreach", "send"])

    assert error.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


def test_candidate_projects_local_path_is_ignored_by_git() -> None:
    result = subprocess.run(
        [
            "git",
            "-c",
            f"safe.directory={ROOT.as_posix()}",
            "check-ignore",
            "--no-index",
            "candidate_projects.local.json",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "candidate_projects.local.json"


def test_project_urls_drop_query_and_fragment_and_reject_credentials() -> None:
    project = CandidateProject(
        name="Sample",
        url="https://example.test/project?token=not-a-secret#readme",
        short_description="A sample public project.",
        technologies=("Python",),
    )
    assert project.url == "https://example.test/project"

    with pytest.raises(ValueError, match=r"absolute HTTP\(S\) URL"):
        CandidateProject(
            name="Sample",
            url="https://user:pass@example.test/project",
            short_description="A sample public project.",
        )
