import json

import pytest

from ai_job_hunter.connectors import (
    AshbyConnector,
    GreenhouseConnector,
    LeverConnector,
    build_job_connectors,
)
from ai_job_hunter.job_sources import (
    JobSourcesConfig,
    JobSourcesConfigError,
    load_job_sources,
)


def test_config_loads_multiple_companies_across_supported_ats(tmp_path):
    path = tmp_path / "job_sources.local.json"
    path.write_text(
        json.dumps(
            {
                "sources": [
                    {"provider": "greenhouse", "identifier": "company-a", "company_name": "Company A"},
                    {"provider": "greenhouse", "identifier": "company-b"},
                    {"provider": "lever", "identifier": "startup-x", "region": "eu", "max_jobs": 35},
                    {"provider": "ashby", "identifier": "product-y", "company_name": "Product Y"},
                ]
            }
        ),
        encoding="utf-8",
    )

    config = load_job_sources(path)
    connectors = build_job_connectors(config)
    try:
        assert len(connectors) == 4
        assert isinstance(connectors[0], GreenhouseConnector)
        assert isinstance(connectors[1], GreenhouseConnector)
        assert connectors[0].board_token == "company-a"
        assert connectors[1].board_token == "company-b"
        assert isinstance(connectors[2], LeverConnector)
        assert connectors[2].site == "startup-x"
        assert connectors[2].region == "eu"
        assert connectors[2].max_jobs == 35
        assert isinstance(connectors[3], AshbyConnector)
        assert connectors[3].job_board_name == "product-y"
    finally:
        for connector in connectors:
            connector.close()


def test_unknown_provider_is_rejected_with_clear_error():
    with pytest.raises(ValueError, match="provider must be one of: greenhouse, lever, ashby"):
        JobSourcesConfig.model_validate(
            {"sources": [{"provider": "remotive", "identifier": "sample"}]}
        )


def test_duplicate_sources_and_invalid_provider_options_are_rejected():
    with pytest.raises(ValueError, match="duplicate provider"):
        JobSourcesConfig.model_validate(
            {
                "sources": [
                    {"provider": "greenhouse", "identifier": "same"},
                    {"provider": "GREENHOUSE", "identifier": "Same"},
                ]
            }
        )
    with pytest.raises(ValueError, match="Lever region"):
        JobSourcesConfig.model_validate(
            {"sources": [{"provider": "lever", "identifier": "site", "region": "private"}]}
        )
    with pytest.raises(ValueError, match="only supported by Lever"):
        JobSourcesConfig.model_validate(
            {"sources": [{"provider": "greenhouse", "identifier": "site", "region": "eu"}]}
        )
    with pytest.raises(ValueError, match="only supported by Lever"):
        JobSourcesConfig.model_validate(
            {"sources": [{"provider": "ashby", "identifier": "site", "region": "eu"}]}
        )


def test_invalid_or_missing_source_config_has_readable_error(tmp_path):
    with pytest.raises(JobSourcesConfigError, match="not valid JSON"):
        path = tmp_path / "invalid.json"
        path.write_text("{", encoding="utf-8")
        load_job_sources(path)
    with pytest.raises(JobSourcesConfigError, match="Cannot read"):
        load_job_sources(tmp_path / "missing.json")


def test_workable_and_personio_sources_build_connectors():
    from ai_job_hunter.connectors import PersonioConnector, WorkableConnector

    config = JobSourcesConfig.model_validate(
        {
            "sources": [
                {"provider": "Workable", "identifier": "idoven", "company_name": "Idoven", "max_jobs": 3},
                {"provider": "personio", "identifier": "acme", "region": "COM"},
                {"provider": "personio", "identifier": "other"},
            ]
        }
    )
    connectors = build_job_connectors(config)
    try:
        assert isinstance(connectors[0], WorkableConnector)
        assert connectors[0].account == "idoven" and connectors[0].max_jobs == 3
        assert isinstance(connectors[1], PersonioConnector) and connectors[1].region == "com"
        assert connectors[2].region == "de"
    finally:
        for connector in connectors:
            connector.close()
    with pytest.raises(ValueError, match="Personio region"):
        JobSourcesConfig.model_validate({"sources": [{"provider": "personio", "identifier": "a", "region": "eu"}]})
    with pytest.raises(ValueError, match="only supported by"):
        JobSourcesConfig.model_validate({"sources": [{"provider": "workable", "identifier": "a", "region": "eu"}]})


def test_teamtailor_and_smartrecruiters_sources_build_connectors():
    from ai_job_hunter.connectors import SmartRecruitersConnector, TeamtailorConnector

    config = JobSourcesConfig.model_validate(
        {
            "sources": [
                {"provider": "Teamtailor", "identifier": "acme", "company_name": "Acme", "max_jobs": 5},
                {"provider": "smartrecruiters", "identifier": "AcmeCo", "max_jobs": 7},
            ]
        }
    )
    connectors = build_job_connectors(config)
    try:
        assert isinstance(connectors[0], TeamtailorConnector)
        assert connectors[0].company == "acme"
        assert connectors[0].company_name == "Acme"
        assert connectors[0].max_jobs == 5
        assert isinstance(connectors[1], SmartRecruitersConnector)
        assert connectors[1].company_id == "AcmeCo"
        assert connectors[1].max_jobs == 7
    finally:
        for connector in connectors:
            connector.close()
    with pytest.raises(ValueError, match="only supported by Lever"):
        JobSourcesConfig.model_validate(
            {"sources": [{"provider": "teamtailor", "identifier": "acme", "region": "eu"}]}
        )
