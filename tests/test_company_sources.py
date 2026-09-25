from __future__ import annotations

from pathlib import Path

import httpx
import pytest

import ai_job_hunter.company_sources as company_sources
from ai_job_hunter.company_sources import (
    MANFRED_README,
    MANFRED_PUBLIC_SALARY,
    REMOTE_ES,
    SPANISH_TOP_TECH,
    CompanySourceError,
    parse_manfred_public_salary_readme,
    parse_spanish_top_tech_readme,
    refresh_company_source_snapshots,
)
from ai_job_hunter.domain.company_intelligence import CompanyEvidenceType

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_spanish_top_tech_aggregates_preserve_salary_context() -> None:
    text = (FIXTURES / "spanish_top_tech_readme.md").read_text(encoding="utf-8")

    records = parse_spanish_top_tech_readme(text)

    assert len(records) == 2
    high, lower = records
    assert high.evidence_type is CompanyEvidenceType.COMPENSATION
    assert high.company_name == "Example Systems"
    assert high.external_identifier == "https://www.linkedin.com/company/example-systems"
    assert high.structured_data["career_page_url"] == "https://boards.greenhouse.io/example-systems"
    assert high.structured_data["compensation"] == {
        "metric": "median",
        "base_annual_eur": 80000,
        "total_compensation_annual_eur": 105000,
        "currency": "EUR",
        "period": "year",
        "sample_size": 6,
        "observation_period": "2024-01 to 2026-08",
        "population": high.structured_data["compensation"]["population"],
        "high_compensation_evidence": True,
        "at_60k_share": 83.0,
        "at_60k_count": 5,
        "table_section": "Median pay, software engineers with 5+ years",
        "source_run_date": "2026-09-23",
        "source_evidence_urls": [
            "https://www.levels.fyi/companies/example-systems/salaries/software-engineer/locations/spain"
        ],
        "career_page_url": "https://boards.greenhouse.io/example-systems",
        "linkedin_url": "https://www.linkedin.com/company/example-systems",
    }
    assert "5+ years" in high.structured_data["compensation"]["population"]
    assert lower.structured_data["compensation"]["base_annual_eur"] == 55000
    assert lower.structured_data["compensation"]["high_compensation_evidence"] is False
    assert lower.structured_data["career_page_url"] is None


def test_spanish_top_tech_parser_accepts_mean_and_missing_optional_columns() -> None:
    text = """# Example list

Each row summarizes a population of experienced engineers.

| Company | Avg base | Engineers |
| --- | ---: | ---: |
| Example Cloud | 72.5k | 4 |
"""

    (record,) = parse_spanish_top_tech_readme(text)

    compensation = record.structured_data["compensation"]
    assert compensation["metric"] == "average"
    assert compensation["base_annual_eur"] == 72500
    assert compensation["total_compensation_annual_eur"] is None
    assert compensation["sample_size"] == 4
    assert compensation["observation_period"] is None
    assert compensation["source_run_date"] is None


def test_missing_salary_stays_unknown_instead_of_becoming_negative_evidence() -> None:
    text = """# Example list

| Company | Median base | Engineers |
| --- | ---: | ---: |
| Example Cloud | — | 4 |
"""

    (record,) = parse_spanish_top_tech_readme(text)

    assert record.structured_data["compensation"]["base_annual_eur"] is None
    assert record.structured_data["compensation"]["high_compensation_evidence"] is None


def test_spanish_top_tech_rejects_duplicate_normalized_company_rows() -> None:
    text = """# Example

| Company | Median base | Engineers |
| --- | ---: | ---: |
| Acme | 75k | 1 |
| ACME, Inc. | 80k | 2 |
"""

    with pytest.raises(CompanySourceError, match="duplicate normalized"):
        parse_spanish_top_tech_readme(text)


def test_parse_manfred_directory_records_public_salary_practice_and_career_ats() -> None:
    text = (FIXTURES / "manfred_public_salary_readme.md").read_text(encoding="utf-8")

    records = parse_manfred_public_salary_readme(text)

    assert len(records) == 2
    assert records[0].provider == MANFRED_PUBLIC_SALARY
    assert records[0].structured_data["public_salary"] is True
    assert records[0].structured_data["career_page_url"] == "https://jobs.lever.co/example-systems"
    assert "does not publish a numeric range" in records[0].structured_data["public_salary_context"]
    assert "compensation" not in records[0].structured_data
    assert records[1].structured_data["career_page_url"] == "https://jobs.ashbyhq.com/example-product"


def test_source_refresh_is_explicit_bounded_and_offline_replayable(tmp_path: Path) -> None:
    bodies = {
        "spanish-top-tech-companies": (FIXTURES / "spanish_top_tech_readme.md").read_text(encoding="utf-8"),
        "companies-with-public-salary": (FIXTURES / "manfred_public_salary_readme.md").read_text(encoding="utf-8"),
    }
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        body = (
            bodies["spanish-top-tech-companies"]
            if "pugarte7/spanish-top-tech-companies" in request.url.path
            else bodies["companies-with-public-salary"]
        )
        return httpx.Response(200, text=body, headers={"x-github-content-sha": "fixture-sha"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    try:
        batches, skipped = refresh_company_source_snapshots(snapshot_dir=tmp_path, client=client)
    finally:
        client.close()

    assert len(calls) == 2
    assert len(batches) == 2
    assert {batch.provider for batch in batches} == {SPANISH_TOP_TECH, MANFRED_PUBLIC_SALARY}
    assert batches[1].readme_url == MANFRED_README
    assert all(batch.snapshot_path.is_file() for batch in batches)
    assert [item.provider for item in skipped] == [REMOTE_ES]
    assert skipped[0].imported_records == 0

    replayed, replay_skipped = refresh_company_source_snapshots(snapshot_dir=tmp_path, offline=True)
    assert len(replayed) == 2
    assert replayed[0].body_sha256 == batches[0].body_sha256
    assert replay_skipped == skipped


def test_source_refresh_stops_when_a_readme_exceeds_the_size_limit(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(company_sources, "MAX_README_BYTES", 3)
    client = httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=b"large")))
    try:
        with pytest.raises(CompanySourceError, match="safety limit"):
            refresh_company_source_snapshots(snapshot_dir=tmp_path, client=client)
    finally:
        client.close()

    assert not list(tmp_path.glob("*.README.md"))
