import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ai_job_hunter import remotive_cli
from ai_job_hunter.candidates import load_candidate_config
from ai_job_hunter.domain.normalized_job import NormalizedJob
from ai_job_hunter.snapshots import (
    RemotiveSnapshotError,
    load_remotive_snapshot,
    save_remotive_snapshot,
)

EXAMPLE_CONFIG = Path(__file__).parents[1] / "config" / "examples" / "candidate.example.json"


def sample_offer(**overrides: object) -> NormalizedJob:
    values: dict[str, object] = {
        "provider": "remotive",
        "external_id": "snapshot-1",
        "source_url": "https://remotive.com/remote-jobs/software/backend-1",
        "title": "Junior Backend Engineer",
        "company_name": "Snapshot Example",
        "description": "Build backend APIs with Python.",
        "location": "Spain",
        "remote_policy": "REMOTE",
        "remote_eligibility": "SPAIN_ONLY",
        "salary_min": 55000,
        "salary_max": 65000,
        "currency": "EUR",
        "salary_period": "YEAR",
        "employment_type": "FULL_TIME",
        "published_at": datetime(2026, 9, 20, tzinfo=UTC),
        "discovered_at": datetime(2026, 9, 24, tzinfo=UTC),
        "raw_metadata": {
            "description": "Build <p>backend APIs</p> with Python.",
            "company_name": "Snapshot Example",
        },
    }
    values.update(overrides)
    return NormalizedJob.model_validate(values)


def test_save_and_load_normalized_snapshot_round_trip(tmp_path: Path) -> None:
    offer = sample_offer(title="Développeur Backend – España 🚀", location="Łódź")
    snapshot_path = tmp_path / "data" / "local" / "jobs.local.json"

    saved_path = save_remotive_snapshot(snapshot_path, [offer])
    loaded = load_remotive_snapshot(saved_path)
    payload = json.loads(saved_path.read_text(encoding="utf-8"))

    assert payload["format"] == "ai-job-hunter.remotive-snapshot"
    assert payload["version"] == 1
    assert payload["offers"][0]["title"] == "Développeur Backend – España 🚀"
    assert loaded == [offer]


@pytest.mark.parametrize(
    ("contents", "message"),
    [
        ("not json", "not valid JSON"),
        (json.dumps({"format": "other", "version": 1, "offers": []}), "Invalid Remotive snapshot"),
        (
            json.dumps(
                {
                    "format": "ai-job-hunter.remotive-snapshot",
                    "version": 1,
                    "captured_at": "2026-09-24T10:00:00Z",
                    "offers": [
                        {"provider": "remotive", "title": "Invalid salary", "salary_min": -1}
                    ],
                }
            ),
            "Invalid Remotive snapshot",
        ),
    ],
)
def test_invalid_snapshot_has_clear_error(tmp_path: Path, contents: str, message: str) -> None:
    path = tmp_path / "invalid.json"
    path.write_text(contents, encoding="utf-8")

    with pytest.raises(RemotiveSnapshotError, match=message):
        load_remotive_snapshot(path)


def test_snapshot_with_invalid_utf8_has_clear_error(tmp_path: Path) -> None:
    path = tmp_path / "invalid-encoding.json"
    path.write_bytes(b"\xff\xfe")

    with pytest.raises(RemotiveSnapshotError, match="not valid UTF-8"):
        load_remotive_snapshot(path)


def test_cli_saves_the_fetched_normalized_offers(monkeypatch, tmp_path: Path) -> None:
    offers = [sample_offer()]
    calls = 0

    def fetch(_self):
        nonlocal calls
        calls += 1
        return offers

    monkeypatch.setattr(remotive_cli.RemotiveConnector, "fetch_jobs", fetch)
    snapshot_path = tmp_path / "data" / "local" / "jobs.local.json"

    exit_code = remotive_cli.main(
        [
            "--candidate-config",
            str(EXAMPLE_CONFIG),
            "--save-snapshot",
            str(snapshot_path),
            "--show",
            "0",
        ]
    )

    assert exit_code == 0
    assert calls == 1
    assert load_remotive_snapshot(snapshot_path) == offers


def test_snapshot_replay_runs_offline_and_reports_all_signal_fields(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    snapshot_path = tmp_path / "jobs.local.json"
    save_remotive_snapshot(snapshot_path, [sample_offer()])

    def unexpected_network_call(_self):
        pytest.fail("snapshot replay attempted to access Remotive")

    monkeypatch.setattr(remotive_cli.RemotiveConnector, "fetch_jobs", unexpected_network_call)
    exit_code = remotive_cli.main(
        ["--candidate-config", str(EXAMPLE_CONFIG), "--snapshot", str(snapshot_path)]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "TOTAL: 1" in output
    assert "TITLE: Junior Backend Engineer | COMPANY: Snapshot Example" in output
    assert "ROLE MATCH:" in output
    assert "GEOGRAPHY:" in output
    assert "SALARY RESULT:" in output
    assert "https://remotive.com/remote-jobs/software/backend-1" in output


def test_replaying_a_snapshot_produces_the_same_full_evaluation_report(
    tmp_path: Path,
) -> None:
    offer = sample_offer()
    snapshot_path = tmp_path / "jobs.local.json"
    save_remotive_snapshot(snapshot_path, [offer])
    candidate = load_candidate_config(EXAMPLE_CONFIG)

    first = remotive_cli._build_evaluation_report(load_remotive_snapshot(snapshot_path), candidate)
    second = remotive_cli._build_evaluation_report(load_remotive_snapshot(snapshot_path), candidate)

    assert first == second
    assert set(first[0]) == {
        "title",
        "company",
        "source_url",
        "location",
        "remote_policy",
        "remote_eligibility",
        "salary",
        "inferred_seniority",
        "technologies",
        "role_match",
        "geographic_result",
        "salary_result",
        "decision",
        "reasons",
    }
    assert first[0]["reasons"]
