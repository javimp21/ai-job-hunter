from pathlib import Path

import pytest

from ai_job_hunter import remotive_cli
from ai_job_hunter.domain.normalized_job import NormalizedJob

EXAMPLE_CONFIG = Path(__file__).parents[1] / "config" / "examples" / "candidate.example.json"


def test_candidate_config_cli_prints_a_prefilter_summary_offline(monkeypatch, capsys) -> None:
    offers = [
        NormalizedJob(
            provider="remotive",
            title="Senior Backend Engineer",
            company_name="Fictional Systems",
            description="Must have Python experience.",
            location="Spain",
            source_url="https://remotive.com/remote-jobs/software/fictional-101",
            remote_policy="REMOTE",
            remote_eligibility="SPAIN_ONLY",
            salary_min=65000,
            salary_max=75000,
            currency="EUR",
            salary_period="YEAR",
            employment_type="FULL_TIME",
        ),
        NormalizedJob(
            provider="remotive",
            title="Lead Backend Engineer",
            company_name="Imaginary Cloud",
            description="Uses Python.",
            location="Spain",
            source_url="https://remotive.com/remote-jobs/software/imaginary-102",
            remote_policy="REMOTE",
            remote_eligibility="SPAIN_ONLY",
            salary_min=65000,
            salary_max=75000,
            currency="EUR",
            salary_period="YEAR",
            employment_type="FULL_TIME",
        ),
    ]
    monkeypatch.setattr(remotive_cli.RemotiveConnector, "fetch_jobs", lambda self: offers)

    exit_code = remotive_cli.main(
        ["--candidate-config", str(EXAMPLE_CONFIG), "--limit", "2", "--show", "2"]
    )

    output = capsys.readouterr().out
    assert exit_code == 0
    assert "Fetched: 2" in output
    assert "PASS: 1" in output
    assert "REJECT: 1" in output
    assert "Fictional Systems | PASS" in output
    assert "Imaginary Cloud | REJECT" in output
    assert "Source: Remotive (https://remotive.com/" in output


def test_candidate_config_cli_rejects_ingestion_combination() -> None:
    with pytest.raises(SystemExit, match="2"):
        remotive_cli.main(
            ["--candidate-config", str(EXAMPLE_CONFIG), "--ingest"]
        )
