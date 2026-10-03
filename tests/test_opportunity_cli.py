import pytest

from ai_job_hunter.cli import _print_prefilter_signals, _print_reevaluation_summary, _print_refresh_summary, main
from ai_job_hunter.services.opportunities import RefreshSummary


def test_unified_cli_help_lists_workflow_commands(capsys) -> None:
    with pytest.raises(SystemExit) as error:
        main(["--help"])

    assert error.value.code == 0
    output = capsys.readouterr().out
    assert "refresh" in output
    assert "opportunities" in output
    assert "show" in output
    assert "application" in output
    assert "apply" in output


def test_refresh_help_exposes_budget_dry_run_and_no_jev_without_side_effects(capsys) -> None:
    with pytest.raises(SystemExit) as error:
        main(["refresh", "--help"])

    assert error.value.code == 0
    output = capsys.readouterr().out
    assert "--max-jev-jobs" in output
    assert "--no-jev" in output
    assert "--retry-pending" in output
    assert "--dry-run" in output


def test_refresh_summary_reports_each_pending_reason(capsys) -> None:
    _print_refresh_summary(
        RefreshSummary(
            pending=5,
            pending_budget=2,
            pending_no_jev=1,
            pending_errors=2,
        )
    )

    output = capsys.readouterr().out
    assert "Pending: 5" in output
    assert "Pending: Jev budget: 2" in output
    assert "Pending: Jev disabled: 1" in output
    assert "Pending: errors: 2" in output


def test_prefilter_output_shows_assessment_and_stack_signals(capsys) -> None:
    _print_prefilter_signals(
        {
            "signals": {
                "geography": {"status": "UNKNOWN"},
                "salary": {"evaluation": "UNKNOWN"},
                "technology": {
                    "matching_primary_skills": ["Java"],
                    "missing_technologies": ["Kafka"],
                },
            }
        }
    )

    output = capsys.readouterr().out
    assert "geography=UNKNOWN" in output
    assert "salary=UNKNOWN" in output
    assert "matched primary: Java" in output
    assert "missing: Kafka" in output


def test_refresh_rejects_negative_budget_before_loading_candidate_or_database() -> None:
    with pytest.raises(SystemExit) as error:
        main(
            [
                "refresh",
                "--candidate-config",
                "does-not-exist.json",
                "--max-jev-jobs",
                "-1",
            ]
        )

    assert error.value.code == 2


def test_reevaluate_requires_explicit_job_ids_and_budget(capsys) -> None:
    job_id = "22e0ab77-6132-4050-b96e-770c2aff9225"
    for argv in (
        ["reevaluate", "--max-jev-jobs", "1"],
        ["reevaluate", "--job-id", job_id],
        ["reevaluate", "--job-id", "not-a-uuid", "--max-jev-jobs", "1"],
        ["reevaluate", "--job-id", job_id, "--max-jev-jobs", "-1", "--candidate-config", "does-not-exist.json"],
    ):
        with pytest.raises(SystemExit) as error:
            main(argv)
        assert error.value.code == 2
    capsys.readouterr()


def test_reevaluate_summary_reports_planned_calls_for_dry_run(capsys) -> None:
    from uuid import UUID

    from ai_job_hunter.services.opportunities import EvaluationItemResult, EvaluationOutcome, ReevaluationSummary

    job_id = UUID("22e0ab77-6132-4050-b96e-770c2aff9225")
    summary = ReevaluationSummary(
        dry_run=True,
        jobs_selected=2,
        items=[
            EvaluationItemResult(job_id, "Acme", "Backend Engineer", EvaluationOutcome.JEV_CALL),
            EvaluationItemResult(job_id, "Acme", "Data Analyst", EvaluationOutcome.DETERMINISTIC_SKIP, "SKIP"),
        ],
    )

    _print_reevaluation_summary(summary)

    output = capsys.readouterr().out
    assert "REEVALUATE DRY RUN (no writes, no Jev calls)" in output
    assert "Jev calls planned: 1" in output
    assert "Jev calls attempted: 0" in output
    assert "Data Analyst | DETERMINISTIC_SKIP -> SKIP" in output


def test_sources_commands_validate_arguments_before_database(capsys) -> None:
    for argv in (["sources"], ["sources", "activate", "not-a-uuid"], ["sources", "list", "--state", "bogus"]):
        with pytest.raises(SystemExit) as error:
            main(argv)
        assert error.value.code == 2
    capsys.readouterr()
