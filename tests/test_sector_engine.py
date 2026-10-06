import json
from pathlib import Path

import pytest

from ai_job_hunter.candidates.prefilter import _classify_role_family_legacy as _classify_role_family
from ai_job_hunter.sectors.engine import (
    CompiledTemplate,
    SectorTemplate,
    SectorTemplateError,
    classify_role_family,
)

GOLDEN = Path(__file__).parent / "fixtures" / "role_family_golden.json"


def template(**changes):
    base = {
        "id": "toy",
        "label": "Toy",
        "sets": {"nouns": ["engineer", "developer"], "bad": ["sales"]},
        "regexes": {"bizdev": r"\bbusiness\s+develop"},
        "compounds": [{"parts": ["back", "end"], "word": "backend"}],
        "rules": [
            {"id": "bad", "when": {"all": [{"tokens_any": ["@bad"]}, {"not": {"tokens_any": ["@nouns"]}}]},
             "fit": "NON_TARGET", "family": "sales", "reason": "non target {family}"},
            {"id": "biz", "when": {"regex": "bizdev"}, "fit": "NON_TARGET", "family": "biz", "reason": "{family}"},
            {"id": "backend", "when": {"tokens_any": ["backend"]}, "fit": "TARGET", "family": "backend",
             "reason": "backend role"},
            {"id": "rest", "when": {"true": True}, "fit": "UNKNOWN", "family": "other", "reason": "other {family} {focus}",
             "focus": "x"},
        ],
    }
    base.update(changes)
    return CompiledTemplate(SectorTemplate.model_validate(base))


def test_rules_are_evaluated_in_order_with_sets_regexes_negation_and_compounds():
    toy = template()

    assert toy.classify("Sales Manager").family == "sales"
    assert toy.classify("Sales Engineer").family == "other"  # the "not nouns" guard of the first rule
    assert toy.classify("Business Development Lead").family == "biz"
    assert toy.classify("Back End Developer").fit == "TARGET"  # "back end" is expanded to "backend"
    assert toy.classify("Accountant").reason == "other other x"  # the catch-all rule, with focus


def test_a_malformed_template_fails_loudly_and_a_missing_catch_all_is_reported():
    with pytest.raises(SectorTemplateError, match="unknown set"):
        template(rules=[{"id": "r", "when": {"tokens_any": ["@missing"]}, "fit": "TARGET", "family": "f", "reason": "r"}])
    with pytest.raises(SectorTemplateError, match="unknown fit"):
        template(rules=[{"id": "r", "when": {"true": True}, "fit": "MAYBE", "family": "f", "reason": "r"}])
    with pytest.raises(SectorTemplateError, match="exactly one key"):
        template(rules=[{"id": "r", "when": {"true": True, "not": {}}, "fit": "TARGET", "family": "f", "reason": "r"}])
    with pytest.raises(SectorTemplateError, match="no rule matched"):
        template(rules=[{"id": "r", "when": {"tokens_any": ["nothing"]}, "fit": "TARGET", "family": "f", "reason": "r"}]).classify("x")


def test_the_software_template_classifies_real_titles_exactly_like_the_original_cascade():
    rows = json.loads(GOLDEN.read_text(encoding="utf-8"))
    assert len(rows) > 5000

    for row in rows:
        result = classify_role_family(row["title"])
        assert (result.fit, result.family) == (row["fit"], row["family"]), row["title"]
        old = _classify_role_family(row["title"])
        assert (result.fit, result.family, result.reason) == (old.fit.value, old.family, old.reason), row["title"]


def test_templates_ship_inside_the_package_so_an_installed_release_finds_them():
    import ai_job_hunter.sectors.engine as engine

    assert engine.SECTORS_DIR.parent == Path(engine.__file__).resolve().parent
    assert (engine.SECTORS_DIR / "software.json").is_file()


def test_the_software_template_carries_the_stack_and_the_jev_rubric():
    from ai_job_hunter.rubric import RUBRIC_SPEC, RUBRIC_VERSION
    from ai_job_hunter.sectors.engine import get_template

    spec = get_template("software").template
    assert spec.stack is not None and {"java", "spring boot", "kotlin"} <= set(spec.stack.core)
    assert spec.stack.penalized and not set(spec.stack.penalized) & set(spec.stack.core)
    assert spec.rubric is not None and RUBRIC_VERSION == spec.rubric.version == "job_decision_v1"
    assert set(RUBRIC_SPEC["questions"]) == set(RUBRIC_SPEC["question_types"])
