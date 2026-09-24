import io
from pathlib import Path
import sys

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
    assert "Senior Backend Engineer | COMPANY: Fictional Systems" in output
    assert "Lead Backend Engineer | COMPANY: Imaginary Cloud" in output
    assert "URL: https://remotive.com/" in output
    assert "ROLE MATCH:" in output
    assert "GEOGRAPHY:" in output
    assert "SALARY RESULT:" in output


def test_candidate_config_cli_rejects_ingestion_combination() -> None:
    with pytest.raises(SystemExit, match="2"):
        remotive_cli.main(
            ["--candidate-config", str(EXAMPLE_CONFIG), "--ingest"]
        )


def test_candidate_cli_reporting_does_not_crash_on_cp1252_unicode(monkeypatch) -> None:
    offer = NormalizedJob(
        provider="remotive",
        title="Développeur Backend – España 🚀",
        company_name="São Paulo",
        description="Expérience avec Kotlin; descripción con Łódź y 🚀.",
        location="Łódź",
        source_url="https://remotive.com/remote-jobs/software/unicode-303",
        remote_policy="REMOTE",
        remote_eligibility="COUNTRY_RESTRICTED",
    )
    monkeypatch.setattr(remotive_cli.RemotiveConnector, "fetch_jobs", lambda _self: [offer])
    raw_output = io.BytesIO()
    cp1252_stdout = io.TextIOWrapper(raw_output, encoding="cp1252", errors="strict")
    monkeypatch.setattr(sys, "stdout", cp1252_stdout)

    exit_code = remotive_cli.main(
        ["--candidate-config", str(EXAMPLE_CONFIG), "--limit", "1"]
    )
    cp1252_stdout.flush()
    output = raw_output.getvalue().decode("cp1252")

    assert exit_code == 0
    assert "Développeur Backend – España \\U0001f680" in output
    assert "São Paulo" in output
    assert "\\u0141ód\\u017a" in output
    assert "LOCATION:" in output
