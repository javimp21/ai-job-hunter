import subprocess
from pathlib import Path
from uuid import uuid4

import pytest

from ai_job_hunter.application_prep.models import (
    ApplicationPackage,
    ApplicationPackageStatus,
    ApplicationQuestion,
    ApplicationQuestionType,
    QuestionSchemaStatus,
)
from ai_job_hunter.application_prep.browser.models import (
    ApplicationFormSnapshot,
    ApplicationSession,
    ApplicationSessionStatus,
    ATSProvider,
    FormField,
    FormFieldType,
    FieldMapping,
    CanonicalField,
    MappingConfidence,
    AnswerPolicy,
)
from ai_job_hunter.application_prep.browser.store import ApplicationSessionStore
from ai_job_hunter.application_prep.store import ApplicationPackageStore
from ai_job_hunter.cli import _parse_apply_command, _question_schema_state, main


def _package(*, job_id=None):
    return ApplicationPackage(
        job_id=job_id or uuid4(),
        fingerprint="a" * 64,
        candidate_profile_fingerprint="b" * 64,
        candidate_preferences_fingerprint="c" * 64,
        application_url="https://example.test/apply",
        question_schema_status=QuestionSchemaStatus.AVAILABLE,
        questions=[
            ApplicationQuestion(
                id="why",
                label="Why this company?",
                required=True,
                normalized_type=ApplicationQuestionType.TEXTAREA,
                extracted_from="fixture",
                confidence=1.0,
            )
        ],
    )


def test_nested_apply_commands_save_and_show_only_local_package(tmp_path, capsys):
    package = _package()
    path = tmp_path / "packages.local.json"
    ApplicationPackageStore(path).save(package)

    result = main(
        ["apply", "show", str(package.job_id), "--packages-path", str(path)]
    )

    assert result == 0
    output = capsys.readouterr().out
    assert f"Job ID: {package.job_id}" in output
    assert "Application URL: https://example.test/apply" in output


def test_cli_answer_saves_to_local_store_and_reports_no_send(tmp_path, capsys):
    package = _package()
    path = tmp_path / "packages.local.json"
    ApplicationPackageStore(path).save(package)

    result = main(
        [
            "apply",
            "answer",
            str(package.job_id),
            "why",
            "--packages-path",
            str(path),
            "--value",
            "The role matches my backend experience.",
        ]
    )

    assert result == 0
    assert "No data was sent" in capsys.readouterr().out
    saved = ApplicationPackageStore(path).get_by_job(package.job_id)
    assert saved is not None
    assert saved.questions[0].answer == "The role matches my backend experience."


def test_ready_requires_human_review_flag(tmp_path, capsys):
    package = _package()
    path = tmp_path / "packages.local.json"
    ApplicationPackageStore(path).save(package)

    result = main(
        ["apply", "ready", str(package.job_id), "--packages-path", str(path)]
    )

    assert result == 2
    assert "--confirm-reviewed" in capsys.readouterr().err
    assert ApplicationPackageStore(path).get_by_job(package.job_id).status is ApplicationPackageStatus.READY_FOR_REVIEW


def test_legacy_apply_uuid_remains_application_tracking_record():
    job_id = uuid4()
    parsed = _parse_apply_command([str(job_id), "--note", "manually applied"])

    assert parsed.action == "record"
    assert parsed.job_id == job_id
    assert parsed.note == "manually applied"


def test_fill_safe_accepts_an_explicit_dry_run_flag():
    parsed = _parse_apply_command(["fill-safe", str(uuid4()), "--dry-run"])

    assert parsed.action == "fill-safe"
    assert parsed.dry_run is True


def test_apply_without_subcommand_prints_help_without_opening_store(capsys):
    assert main(["apply"]) == 0
    output = capsys.readouterr().out
    assert "apply prepare JOB_ID" in output
    assert "no application submission" in output


def test_submit_is_not_a_supported_command(capsys):
    with pytest.raises(SystemExit) as error:
        main(["apply", "submit", str(uuid4())])

    assert error.value.code == 2
    assert "invalid choice" in capsys.readouterr().err


def test_browser_inspect_cli_reads_redacted_saved_session(tmp_path, capsys):
    package = _package()
    packages_path = tmp_path / "packages.local.json"
    sessions_path = tmp_path / "sessions.local.json"
    ApplicationPackageStore(packages_path).save(package)
    snapshot = ApplicationFormSnapshot(
        url="https://jobs.eu.lever.co/example/job/apply?candidate=private",
        ats=ATSProvider.LEVER,
        fields=(FormField(id="email", label="Email address", field_type=FormFieldType.EMAIL, required=True),),
    )
    session = ApplicationSession(
        job_id=package.job_id,
        application_package_id=package.id,
        url=snapshot.url,
        ats=ATSProvider.LEVER,
        snapshot=snapshot,
        snapshots=(snapshot,),
        mappings=(FieldMapping(
            field_id="email",
            canonical_field=CanonicalField.EMAIL,
            confidence=MappingConfidence.HIGH,
            evidence=("Exact visible label.",),
            source_label="Email address",
            answer_policy=AnswerPolicy.NEEDS_USER_INPUT,
        ),),
        pending_field_ids=("email",),
        status=ApplicationSessionStatus.NEEDS_INPUT,
    )
    ApplicationSessionStore(sessions_path).save(session)

    result = main([
        "apply", "inspect", str(package.job_id),
        "--packages-path", str(packages_path),
        "--sessions-path", str(sessions_path),
    ])

    assert result == 0
    output = capsys.readouterr().out
    assert "Email address" in output
    assert "candidate=private" not in output


def test_question_schema_detection_requires_structured_application_field():
    from ai_job_hunter.application_prep.models import QuestionSchemaStatus

    unrelated = _question_schema_state(
        "greenhouse", {"metadata": {"questions": ["about the company"]}}, "123"
    )
    structured = _question_schema_state(
        "greenhouse",
        {"questions": [{"label": "Experience with Java?", "fields": [{"name": "java", "type": "input_text"}]}]},
        "123",
    )

    assert unrelated[0] is QuestionSchemaStatus.NOT_CHECKED
    assert structured[0] is QuestionSchemaStatus.AVAILABLE


def test_private_application_preparation_paths_are_git_ignored_and_untracked():
    root = Path(__file__).resolve().parents[1]
    private_paths = (
        "candidate.local.json",
        "candidate_application.local.json",
        "candidate_projects.local.json",
        "candidate_documents.local.json",
        "candidate_writing.local.json",
        "data/local/application-packages.local.json",
        "data/local/application-sessions.local.json",
    )

    for private_path in private_paths:
        ignored = subprocess.run(
            ["git", "-c", f"safe.directory={root}", "check-ignore", "--quiet", private_path],
            cwd=root,
            check=False,
        )
        tracked = subprocess.run(
            ["git", "-c", f"safe.directory={root}", "ls-files", "--error-unmatch", private_path],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        assert ignored.returncode == 0, private_path
        assert tracked.returncode != 0, private_path
