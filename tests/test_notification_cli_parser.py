import argparse
from pathlib import Path

from ai_job_hunter.cli import (
    DEFAULT_CANDIDATE_CONFIG,
    _add_notification_and_run_parsers,
)


def _parser():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    _add_notification_and_run_parsers(commands)
    return parser


def test_notify_send_dry_run_is_explicit_and_candidate_configurable():
    args = _parser().parse_args(["notify", "send", "--dry-run"])

    assert args.command == "notify"
    assert args.notification_command == "send"
    assert args.dry_run is True
    assert args.candidate_config == DEFAULT_CANDIDATE_CONFIG


def test_notify_read_commands_have_bounded_limit_and_candidate_config():
    args = _parser().parse_args(
        ["notify", "history", "--limit", "7", "--candidate-config", "candidate.test.json"]
    )

    assert args.notification_command == "history"
    assert args.limit == 7
    assert args.candidate_config == Path("candidate.test.json")


def test_run_exposes_bounded_refresh_notification_and_safety_controls():
    args = _parser().parse_args(
        [
            "run",
            "--limit-companies",
            "3",
            "--max-jobs-per-company",
            "30",
            "--max-jev-jobs",
            "5",
            "--max-notifications",
            "8",
            "--no-notifications",
            "--dry-run",
            "--candidate-config",
            "candidate.local.json",
        ]
    )

    assert args.command == "run"
    assert args.limit_companies == 3
    assert args.max_jobs_per_company == 30
    assert args.max_jev_jobs == 5
    assert args.max_notifications == 8
    assert args.no_notifications is True
    assert args.dry_run is True
    assert args.candidate_config == DEFAULT_CANDIDATE_CONFIG
