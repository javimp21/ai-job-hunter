import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from pydantic import ValidationError

from ai_job_hunter.candidates import (
    CandidateConfig,
    CandidateConfigError,
    load_candidate_config,
)

EXAMPLE_CONFIG = Path(__file__).parents[1] / "config" / "examples" / "candidate.example.json"


def test_public_example_loads_as_separate_profile_and_preferences() -> None:
    config = load_candidate_config(EXAMPLE_CONFIG)

    assert config.profile.current_role == "Backend Engineer"
    assert config.profile.current_salary == 60000
    assert config.preferences.minimum_salary == 50000
    assert config.preferences.remote_preference.value == "REMOTE_ONLY"
    assert config.profile.current_country == "Spain"


def test_invalid_json_has_a_clear_path_and_location() -> None:
    with TemporaryDirectory(dir=Path(__file__).parent) as temp_dir:
        config_path = Path(temp_dir) / "candidate.local.json"
        config_path.write_text('{"profile": ', encoding="utf-8")

        with pytest.raises(CandidateConfigError, match=r"candidate\.local\.json.*line 1"):
            load_candidate_config(config_path)


def test_invalid_profile_configuration_has_clear_field_errors() -> None:
    with TemporaryDirectory(dir=Path(__file__).parent) as temp_dir:
        config_path = Path(temp_dir) / "candidate.local.json"
        config_path.write_text(
            json.dumps(
                {
                    "profile": {"unknown_personal_field": "should not be accepted"},
                    "preferences": {"minimum_salary": 50000},
                }
            ),
            encoding="utf-8",
        )

        with pytest.raises(CandidateConfigError) as error:
            load_candidate_config(config_path)

        assert "unknown_personal_field" in str(error.value)
        assert "salary_currency and salary_period" in str(error.value)


def test_candidate_profile_rejects_current_salary_without_currency() -> None:
    with pytest.raises(ValidationError, match="salary_currency"):
        CandidateConfig.model_validate({"profile": {"current_salary": 50000}})


def test_preferences_reject_minimum_above_target() -> None:
    with pytest.raises(ValidationError, match="minimum_salary must not exceed target_salary"):
        CandidateConfig.model_validate(
            {
                "profile": {},
                "preferences": {
                    "minimum_salary": 70000,
                    "target_salary": 65000,
                    "salary_currency": "EUR",
                    "salary_period": "YEAR",
                },
            }
        )
