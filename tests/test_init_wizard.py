import json

import pytest

from ai_job_hunter import init_wizard
from ai_job_hunter.candidates import load_candidate_config

ANSWERS = {
    "current_country": "Germany",
    "current_city": "Berlin",
    "years_of_experience": "2",
    "current_role": "Data Analyst",
    "languages": "German (native), English (C1)",
    "preferred_roles": "Data Analyst, BI Developer",
    "primary_skills": "SQL, Power BI",
    "technologies": "SQL, Python",
    "preferred_locations": "Berlin, Hamburg",
    "relocation": "yes",
    "relocation_destinations": "Netherlands, Ireland",
    "remote_preference": "HYBRID_OR_REMOTE",
    "salary_currency": "eur",
    "minimum_salary": "45000",
    "target_salary": "55000",
    "timezone": "Europe/Berlin",
    "salary_guide": "Germany: 45000-52000-58000 EUR; Netherlands: 48000-55000-62000 EUR",
}


def test_answers_become_a_valid_config_with_the_places_merged_and_a_salary_guide():
    config = init_wizard.build_config(ANSWERS)

    assert config.profile.languages == ["German (native)", "English (C1)"]  # a level's parentheses survive
    assert config.profile.current_country == "Germany" and config.profile.work_authorization == ["Germany"]
    preferences = config.preferences
    assert preferences.relocation_willingness is True and preferences.relocation_preferred_locations == ["Netherlands", "Ireland"]
    assert preferences.acceptable_locations == ["Berlin", "Hamburg", "Netherlands", "Ireland"]
    assert (preferences.salary_currency, preferences.target_salary) == ("EUR", 55000)
    guide = config.tuning.salary_guide
    assert guide["Germany"].answer == 52000 and guide["Netherlands"].currency == "EUR"


def test_missing_or_unreadable_answers_are_explained():
    with pytest.raises(init_wizard.WizardError, match="current_country"):
        init_wizard.build_config({**ANSWERS, "current_country": ""})
    with pytest.raises(init_wizard.WizardError, match="salary guide"):
        init_wizard.build_config({**ANSWERS, "salary_guide": "Germany 45000"})
    with pytest.raises(init_wizard.WizardError):
        init_wizard.build_config({**ANSWERS, "minimum_salary": "60000", "target_salary": "50000"})


def test_interactive_questions_use_defaults_and_ask_again_on_bad_choices():
    scripted = {key: str(value) for key, value in ANSWERS.items()}
    scripted["remote_preference"] = ""  # default ANY
    asked = []

    def fake_input(prompt):
        asked.append(prompt)
        for key, question, _kind, _default in init_wizard.QUESTIONS:
            if prompt.startswith(question):
                if key == "minimum_seniority" and not any("Please" in p for p in asked):
                    asked.append("Please")
                    return "WIZARD"  # not an option: asked again
                return scripted.get(key, "")
        raise AssertionError(prompt)

    answers = init_wizard.ask(fake_input, lambda *a, **k: None)

    assert answers["remote_preference"] == "ANY" and answers["minimum_seniority"] == "JUNIOR"
    assert init_wizard.build_config(answers).preferences.remote_preference.value == "ANY"


def test_main_writes_a_file_the_hunter_can_load_and_never_overwrites_silently(tmp_path, capsys):
    answers_file = tmp_path / "answers.json"
    answers_file.write_text(json.dumps(ANSWERS), encoding="utf-8")
    output = tmp_path / "candidate.local.json"

    assert init_wizard.main(["--answers", str(answers_file), "--output", str(output)]) == 0
    loaded = load_candidate_config(output)
    assert loaded.profile.current_city == "Berlin" and "Germany" in loaded.tuning.salary_guide
    assert "SCHEDULE_TIMEZONE=Europe/Berlin" in capsys.readouterr().out

    assert init_wizard.main(["--answers", str(answers_file), "--output", str(output)]) == 1  # exists
    assert init_wizard.main(["--answers", str(answers_file), "--output", str(output), "--force"]) == 0
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert init_wizard.main(["--answers", str(bad), "--output", str(tmp_path / "x.json")]) == 2
