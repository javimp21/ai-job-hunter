"""Write src/ai_job_hunter/sectors/templates/software.json from the vocabulary and cascade currently hard-coded in prefilter.py.

One-off migration helper: the word sets are dumped straight from the existing constants (no retyping) and the cascade of
``_clearly_non_technical_role`` / ``_classify_role_family`` is written as ordered rules. The equivalence test compares the
template with the old functions on a golden corpus of real titles.
"""

from __future__ import annotations

import json
from pathlib import Path

from ai_job_hunter.candidates import prefilter as p

ROOT = Path(__file__).resolve().parents[1]

# Markers of the non-technical families, in the order the old code checked them.
MARKERS = (
    "sales", "ventas", "support", "success", "designer", "legal", "counsel", "attorney",
    "lawyer", "marketing", "marketer", "recruiter", "recruiting", "recruitment",
    "hr", "hrbp", "finance", "accountant", "accounting", "community", "producer",
    "copywriter", "writer", "rrhh", "reclutador", "reclutadora", "abogado",
    "abogada", "contable", "disenador", "disenadora", "nurse", "physician",
    "doctor", "clinician", "pharmacist", "therapist", "dentist",
)

SOFTWARE_FOCUS = "mainly software/backend engineering"
NON_TARGET_REASON = "Title belongs to the non-target {family} role family."
POTENTIAL_REASON = "Role family '{family}' is only potentially relevant; review whether the work is {focus}."


def words(*parts: str) -> dict:
    return {"tokens_any": list(parts)}


def rule(rule_id: str, when: dict, fit: str, family: str, reason: str, focus: str = "") -> dict:
    return {"id": rule_id, "when": when, "fit": fit, "family": family, "reason": reason, "focus": focus}


def non_target(rule_id: str, when: dict, family: str) -> dict:
    return rule(rule_id, when, "NON_TARGET", family, NON_TARGET_REASON)


def build() -> dict:
    sets = {
        "engineering_job": p._ENGINEERING_JOB_TOKENS,
        "technical_markers": p._TECHNICAL_ROLE_MARKERS,
        "technical_context": p._TECHNICAL_ROLE_MARKERS - {"engineer", "engineering"},
        "hardware": p._HARDWARE_TOKENS,
        "core_software": p._CORE_SOFTWARE_TOKENS,
        "platform": p._PLATFORM_TOKENS,
        "core_or_platform": p._CORE_SOFTWARE_TOKENS | p._PLATFORM_TOKENS,
        "governance": p._GOVERNANCE_TOKENS,
        "analyst": p._ANALYST_TOKENS,
        "science": p._SCIENCE_TOKENS,
        "ai": p._AI_TOKENS,
        "ml_specialty": p._ML_SPECIALTY_TOKENS,
        "ai_or_ml_specialty": p._AI_TOKENS | p._ML_SPECIALTY_TOKENS,
        "data": p._DATA_TOKENS,
        "customer_facing": p._CUSTOMER_FACING_ENGINEERING_TOKENS,
        "engineering_or_technical": p._ENGINEERING_JOB_TOKENS | p._TECHNICAL_ROLE_MARKERS,
    }
    not_engineering = {"not": words("@engineering_job")}
    not_technical = {"not": words("@technical_markers")}
    rules: list[dict] = []

    # --- clearly non-technical families, in the order of the old cascade ---------------------------------------
    for marker in MARKERS:
        when = words(marker)
        if marker in {"sales", "ventas"}:
            # "Sales engineer" with technical words stays technical unless the legacy sales pattern says otherwise.
            when = {"all": [when, {"not": {"all": [words("@technical_markers"), {"not": {"regex": "legacy_unrelated"}}]}}]}
        rules.append(non_target(f"marker_{marker}", when, p._NON_TECHNICAL_ROLE_MARKERS[marker]))
    rules += [
        non_target("hardware", {"all": [words("@hardware"), {"not": words("@core_software")}]}, "hardware engineering"),
        non_target("governance", {"all": [not_engineering, words("@governance")]}, "governance / risk / compliance"),
        non_target("non_engineering_analyst", {"all": [not_engineering, words("@analyst")]}, "non-engineering analyst"),
        non_target("science", {"all": [not_engineering, words("@science")]}, "science / research"),
        non_target("comercial", {"all": [not_engineering, words("comercial")]}, "sales"),
        non_target(
            "go_to_market",
            {"all": [not_engineering, {"any": [words("gtm"), {"tokens_all": ["go", "market"]}]}]},
            "go-to-market",
        ),
        non_target("ml_research", {"all": [words("research"), words("@ai_or_ml_specialty")]}, "ML research"),
        non_target("product_management", {"tokens_all": ["product", "manager"]}, "product management"),
        non_target("business_development", {"regex": "business_development"}, "business development"),
        non_target("account_sales", {"all": [words("account"), words("executive", "manager")]}, "sales"),
        non_target(
            "unscoped_application_pool",
            {
                "any": [
                    {"tokens_all": ["talent", "pool"]},
                    {"all": [words("spontaneous", "espontanea", "unsolicited"), words("application", "candidatura")]},
                ]
            },
            "unscoped application",
        ),
        non_target(
            "no_technical_term", {"not": words("@engineering_or_technical")}, "non-technical (no technical term in title)"
        ),
        non_target("product", {"all": [not_technical, words("product")]}, "product"),
        non_target("analyst_without_technical", {"all": [not_technical, words("analyst")]}, "non-engineering analyst"),
        non_target(
            "open_application",
            {"all": [not_technical, words("open", "general"), words("application")]},
            "unscoped application",
        ),
        non_target(
            "solutions_consulting",
            {"all": [not_technical, words("solution", "solutions"), words("consultant")]},
            "solutions consulting",
        ),
        non_target(
            "operations", {"all": [{"not": words("@technical_context")}, words("operations")]}, "operations"
        ),
        non_target("growth", {"all": [{"not": words("@technical_context")}, words("growth")]}, "growth"),
        non_target(
            "commercial_head",
            {"all": [not_technical, words("commercial"), words("head", "director", "manager")]},
            "commercial",
        ),
        non_target(
            "administrative_support",
            {
                "all": [
                    not_technical,
                    {"any": [{"tokens_all": ["office", "assistant"]}, {"tokens_all": ["administrative", "assistant"]}]},
                ]
            },
            "administrative support",
        ),
        non_target(
            "legacy_unrelated", {"regex": "legacy_unrelated"}, "sales / customer service / administrative support"
        ),
    ]

    # --- families of engineering titles --------------------------------------------------------------------
    rules += [
        rule(
            "unclassified", {"not": words("@engineering_job")}, "UNKNOWN", "unclassified",
            "Title does not name a recognized engineering role family.",
        ),
        rule(
            "ml_specialist", {"all": [words("@ai_or_ml_specialty"), words("@ml_specialty")]}, "POTENTIALLY_RELEVANT",
            "ML specialist (vision/NLP/deep learning)", POTENTIAL_REASON, SOFTWARE_FOCUS,
        ),
        rule(
            "ai_software", {"all": [words("@ai_or_ml_specialty"), words("@core_software")]}, "TARGET",
            "software/backend engineering (AI domain)",
            "Title names a software/backend engineering role in an AI domain.",
        ),
        rule(
            "ai_platform", {"all": [words("@ai_or_ml_specialty"), words("@platform")]}, "POTENTIALLY_RELEVANT",
            "AI/ML platform engineering", POTENTIAL_REASON, "platform, serving or tooling engineering",
        ),
        rule(
            "ml_engineering",
            {"all": [words("@ai_or_ml_specialty"), words("ml"), {"not": words("ai", "genai", "llm", "llms")}]},
            "POTENTIALLY_RELEVANT", "machine learning engineering", POTENTIAL_REASON,
            "software-heavy rather than model research",
        ),
        rule(
            "ai_engineering", words("@ai_or_ml_specialty"), "TARGET", "AI engineering",
            "Title names an AI engineering role (software around models).",
        ),
        rule(
            "analytics_engineering", {"all": [words("@data"), words("analytics")]}, "POTENTIALLY_RELEVANT",
            "analytics engineering", POTENTIAL_REASON, "software-heavy (pipelines, data platform, distributed systems)",
        ),
        rule(
            "data_engineering", words("@data"), "POTENTIALLY_RELEVANT", "data engineering", POTENTIAL_REASON,
            "software-heavy (pipelines, data platform, distributed systems)",
        ),
        rule(
            "forward_deployed", {"any": [{"tokens_all": ["forward", "deployed"]}, words("fde")]}, "TARGET",
            "forward deployed engineering", "Title names a forward deployed engineering role.",
        ),
        rule(
            "customer_facing", words("@customer_facing"), "POTENTIALLY_RELEVANT", "customer-facing engineering",
            POTENTIAL_REASON, SOFTWARE_FOCUS,
        ),
        rule("research_engineering", words("research"), "POTENTIALLY_RELEVANT", "research engineering", POTENTIAL_REASON, SOFTWARE_FOCUS),
        rule(
            "software_platform", words("@core_or_platform"), "TARGET", "software/backend/platform engineering",
            "Title names a software, backend or platform engineering role.",
        ),
        rule(
            "other_engineering", {"true": True}, "UNKNOWN", "other engineering",
            "Title names an engineering role outside the recognized target families.",
        ),
    ]
    return {
        "id": "software",
        "label": "Software y datos",
        "sets": {name: sorted(values) for name, values in sets.items()},
        "regexes": {
            "legacy_unrelated": p._LEGACY_UNRELATED_ROLE.pattern,
            "business_development": p._BUSINESS_DEVELOPMENT.pattern,
        },
        "compounds": [
            {"parts": sorted(parts), "word": word, "expand_back": word not in {"ml", "ai"}}
            for parts, word in p._TITLE_COMPOUNDS
        ],
        "rules": rules,
    }


if __name__ == "__main__":
    target = ROOT / "src" / "ai_job_hunter" / "sectors" / "templates" / "software.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(build(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {target}")
