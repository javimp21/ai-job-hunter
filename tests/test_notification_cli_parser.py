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


def test_notify_system_requires_text(capsys):
    import pytest

    from ai_job_hunter.cli import main

    with pytest.raises(SystemExit) as error:
        main(["notify", "system"])
    assert error.value.code == 2
    capsys.readouterr()


def test_notify_system_reports_missing_telegram_without_crashing(monkeypatch, capsys):
    from ai_job_hunter import cli
    from ai_job_hunter.config import Settings

    monkeypatch.setattr(cli, "get_settings", lambda: Settings(telegram_bot_token=None, telegram_chat_id=None))
    monkeypatch.setattr(cli, "create_database_engine", lambda settings: type("E", (), {"dispose": lambda self: None})())
    monkeypatch.setattr(cli, "create_session_factory", lambda engine: (lambda: __import__("contextlib").nullcontext(None)))

    assert cli.main(["notify", "system", "--text", "hello"]) == 1
    assert "not configured" in capsys.readouterr().err
