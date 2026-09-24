import json

import pytest

from ai_job_hunter.connectors import (
    GreenhouseConnector,
    LeverConnector,
    build_job_connectors,
)
from ai_job_hunter.job_sources import (
    JobSourcesConfig,
    JobSourcesConfigError,
    load_job_sources,
)


def test_config_loads_multiple_companies_across_both_ats(tmp_path):
    path = tmp_path / "job_sources.local.json"
    path.write_text(
        json.dumps(
            {
                "sources": [
                    {"provider": "greenhouse", "identifier": "company-a", "company_name": "Company A"},
                    {"provider": "greenhouse", "identifier": "company-b"},
                    {"provider": "lever", "identifier": "startup-x", "region": "eu", "max_jobs": 35},
                ]
            }
        ),
        encoding="utf-8",
    )

    config = load_job_sources(path)
    connectors = build_job_connectors(config)
    try:
        assert len(connectors) == 3
        assert isinstance(connectors[0], GreenhouseConnector)
        assert isinstance(connectors[1], GreenhouseConnector)
        assert connectors[0].board_token == "company-a"
        assert connectors[1].board_token == "company-b"
        assert isinstance(connectors[2], LeverConnector)
        assert connectors[2].site == "startup-x"
        assert connectors[2].region == "eu"
        assert connectors[2].max_jobs == 35
    finally:
        for connector in connectors:
            connector.close()


def test_unknown_provider_is_rejected_with_clear_error():
    with pytest.raises(ValueError, match="provider must be one of: greenhouse, lever"):
        JobSourcesConfig.model_validate(
            {"sources": [{"provider": "ashby", "identifier": "sample"}]}
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


def test_invalid_or_missing_source_config_has_readable_error(tmp_path):
    with pytest.raises(JobSourcesConfigError, match="not valid JSON"):
        path = tmp_path / "invalid.json"
        path.write_text("{", encoding="utf-8")
        load_job_sources(path)
    with pytest.raises(JobSourcesConfigError, match="Cannot read"):
        load_job_sources(tmp_path / "missing.json")
