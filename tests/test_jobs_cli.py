import json
from datetime import UTC, datetime

import pytest

from ai_job_hunter import jobs_cli
from ai_job_hunter.domain.normalized_job import NormalizedJob
from ai_job_hunter.snapshots import load_job_snapshot, save_job_snapshot


def make_offer(provider: str, title: str, company: str, url_id: str) -> NormalizedJob:
    return NormalizedJob(
        provider=provider,
        external_id=url_id,
        source_url=f"https://jobs.example.test/{provider}/{url_id}",
        canonical_url=f"https://jobs.example.test/{provider}/{url_id}",
        title=title,
        company_name=company,
        description="Build backend services with Python and PostgreSQL.",
        location="Barcelona, Spain",
        discovered_at=datetime(2026, 9, 24, tzinfo=UTC),
        raw_metadata={"sample": True},
    )


def candidate_config(tmp_path):
    path = tmp_path / "candidate.example.json"
    path.write_text(
        json.dumps(
            {
                "profile": {
                    "years_of_experience": 2,
                    "primary_skills": ["Python", "Backend engineering"],
                    "technologies": ["Python", "PostgreSQL"],
                    "current_country": "Spain",
                    "eligible_countries": ["Spain"],
                    "remote_work_capability": True,
                },
                "preferences": {
                    "preferred_roles": ["Backend Engineer", "Platform Engineer"],
                    "preferred_locations": ["Spain"],
                    "remote_preference": "ANY",
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def test_source_runner_fetches_two_greenhouse_boards_and_lever_together(monkeypatch, tmp_path, capsys):
    sources_path = tmp_path / "job_sources.local.json"
    sources_path.write_text(
        json.dumps(
            {
                "sources": [
                    {"provider": "greenhouse", "identifier": "company-a", "company_name": "Company A"},
                    {"provider": "greenhouse", "identifier": "company-b", "company_name": "Company B"},
                    {"provider": "lever", "identifier": "startup-x", "company_name": "Startup X"},
                ]
            }
        ),
        encoding="utf-8",
    )
    offers = [
        make_offer("greenhouse", "Junior Backend Engineer", "Company A", "gh-a"),
        make_offer("greenhouse", "Platform Engineer", "Company B", "gh-b"),
        make_offer("lever", "Backend Engineer", "Startup X", "lv-x"),
    ]
    calls = []

    class StubConnector:
        def __init__(self, jobs):
            self.jobs = jobs

        def fetch_jobs(self):
            calls.append(self.jobs[0].provider)
            return self.jobs

        def close(self):
            pass

    monkeypatch.setattr(
        jobs_cli,
        "build_job_connectors",
        lambda config, **_kwargs: [StubConnector([offer]) for offer in offers],
    )
    snapshot = tmp_path / "mixed.local.json"
    exit_code = jobs_cli.main(
        [
            "--sources", str(sources_path),
            "--candidate-config", str(candidate_config(tmp_path)),
            "--save-snapshot", str(snapshot),
        ]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert calls == ["greenhouse", "greenhouse", "lever"]
    assert [job.provider for job in load_job_snapshot(snapshot)] == [
        "greenhouse", "greenhouse", "lever"
    ]
    assert "TOTAL: 3" in output
    assert "HARD SKIP:" in output
    assert "JEV ELIGIBLE:" in output
    assert "PROVIDER: greenhouse" in output
    assert "PROVIDER: lever" in output
    assert "DETERMINISTIC REASONS:" in output


def test_snapshot_replay_runs_offline_and_never_calls_jev(monkeypatch, tmp_path, capsys):
    import ai_job_hunter.decision_engine as decision_engine

    def unexpected_jev(*_args, **_kwargs):
        pytest.fail("Jev evaluation was called by deterministic source replay")

    monkeypatch.setattr(decision_engine, "evaluate_job_decision", unexpected_jev)
    snapshot = tmp_path / "mixed.local.json"
    save_job_snapshot(
        snapshot,
        [make_offer("greenhouse", "Junior Backend Engineer", "Company A", "gh-a")],
    )
    exit_code = jobs_cli.main(
        ["--snapshot", str(snapshot), "--candidate-config", str(candidate_config(tmp_path))]
    )
    output = capsys.readouterr().out

    assert exit_code == 0
    assert "TOTAL: 1" in output
    assert "JEV ELIGIBLE: 1" in output
    assert "PROVIDER: greenhouse" in output
    assert "DETERMINISTIC DECISION: REVIEW" in output or "DETERMINISTIC DECISION: PASS" in output


def test_snapshot_replay_does_not_call_source_connectors(monkeypatch, tmp_path):
    def unexpected_fetch(*_args, **_kwargs):
        pytest.fail("network source was called during snapshot replay")

    monkeypatch.setattr(jobs_cli, "build_job_connectors", unexpected_fetch)
    snapshot = tmp_path / "mixed.local.json"
    save_job_snapshot(snapshot, [make_offer("lever", "Backend Engineer", "Company", "1")])
    assert jobs_cli.main(["--snapshot", str(snapshot)]) == 0
