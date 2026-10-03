import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from ai_job_hunter.candidates import (
    CandidateConfig,
    JobFacts,
    PreFilterDecision,
    evaluate_job,
    load_candidate_config,
)
from ai_job_hunter.candidates.prefilter import (
    SalaryEvaluation,
    SignalStatus,
)
from ai_job_hunter.candidates.technologies import extract_job_technologies
from ai_job_hunter.connectors.remotive import RemotiveConnector
from ai_job_hunter.domain.normalized_job import NormalizedJob

EXAMPLE_CONFIG = Path(__file__).parents[1] / "config" / "examples" / "candidate.example.json"
REMOTIVE_FIXTURE = Path(__file__).parent / "fixtures" / "remotive_response.json"


def make_config(
    *,
    profile: dict[str, object] | None = None,
    preferences: dict[str, object] | None = None,
) -> CandidateConfig:
    config = {
        "profile": {
            "current_role": "Backend Engineer",
            "current_country": "Spain",
            "primary_skills": ["Python", "Backend engineering"],
            "technologies": ["Python"],
        },
        "preferences": {
            "minimum_salary": 50000,
            "target_salary": 70000,
            "salary_currency": "EUR",
            "salary_period": "YEAR",
            "remote_preference": "REMOTE_ONLY",
            "acceptable_employment_types": ["FULL_TIME"],
            "maximum_seniority": "SENIOR",
            "willing_to_learn_technologies": [],
        },
    }
    config["profile"].update(profile or {})
    config["preferences"].update(preferences or {})
    return CandidateConfig.model_validate(config)


def make_offer(**changes: object) -> NormalizedJob:
    values: dict[str, object] = {
        "provider": "fixture",
        "external_id": "role-1",
        "title": "Mid Backend Engineer",
        "description": "Build APIs with Python.",
        "location": "Spain",
        "remote_policy": "REMOTE",
        "remote_eligibility": "SPAIN_ONLY",
        "salary_min": Decimal("70000"),
        "salary_max": Decimal("80000"),
        "currency": "EUR",
        "salary_period": "YEAR",
        "employment_type": "FULL_TIME",
        "discovered_at": datetime(2026, 9, 24, tzinfo=UTC),
    }
    values.update(changes)
    return NormalizedJob.model_validate(values)


def facts_for(**changes: object) -> JobFacts:
    return JobFacts.from_normalized_job(make_offer(**changes))


def test_skills_are_matched_case_insensitively_and_split_by_profile_group() -> None:
    candidate = make_config(
        profile={
            "primary_skills": ["python"],
            "secondary_skills": ["Postgres"],
            "technologies": ["Docker"],
        }
    )
    facts = facts_for(description="Python, PostgreSQL, and Docker are used.")

    result = evaluate_job(facts, candidate)

    assert result.signals.technology.matching_primary_skills == ("python",)
    assert result.signals.technology.matching_secondary_skills == ("postgresql",)
    assert result.signals.technology.matching_candidate_technologies == ("docker",)
    assert result.signals.technology.missing_technologies == ()


def test_title_seniority_wins_over_description_and_reuses_dedup_normalization() -> None:
    facts = facts_for(
        title="Jr. Backend Engineer (Remote)",
        description="Level: Senior. Uses Python.",
    )

    assert facts.inferred_seniority.value == "JUNIOR"
    assert facts.normalized_title == "backend engineer"


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("(Senior/Staff) Backend Engineer", "STAFF"),
        ("Principal Backend Engineer", "PRINCIPAL"),
        ("Lead Backend Engineer", "LEAD"),
        ("Engineering Manager", "MANAGER"),
        ("Director of Engineering", "DIRECTOR"),
        ("Head of Engineering", "HEAD"),
    ],
)
def test_explicit_elevated_seniority_is_inferred_from_composite_and_title_markers(
    title: str,
    expected: str,
) -> None:
    assert facts_for(title=title).inferred_seniority.value == expected


def test_seniority_is_inferred_from_a_labeled_description_only_when_title_is_unknown() -> None:
    labeled = facts_for(title="Backend Engineer", description="Seniority: Senior\nUses Python.")
    weak = facts_for(title="Backend Engineer", description="A senior engineer will mentor peers.")

    assert labeled.inferred_seniority.value == "SENIOR"
    assert weak.inferred_seniority.value == "UNKNOWN"


def test_technology_extraction_uses_explicit_names_and_aliases_without_unlabeled_go_verb() -> None:
    technologies, required = extract_job_technologies(
        "Go Backend Engineer",
        "Must have Python, Node.js and AWS. Kotlin is nice to have. Go and build services.",
    )

    assert set(technologies) == {"aws", "go", "kotlin", "node.js", "python"}
    assert set(required) == {"aws", "node.js", "python"}


def test_go_is_detected_when_context_is_explicit_but_not_as_an_ordinary_verb() -> None:
    explicit, required = extract_job_technologies(
        "Backend Engineer",
        "Must have Go experience. Please go and build reliable services.",
    )
    prose, _ = extract_job_technologies(
        "Backend Engineer",
        "Please go and build reliable services.",
    )
    ambiguous_title, _ = extract_job_technologies("Go-to-Market Engineer", None)

    assert explicit == ("go",)
    assert required == ("go",)
    assert prose == ()
    assert ambiguous_title == ()


def test_node_and_node_js_are_one_canonical_technology() -> None:
    technologies, required = extract_job_technologies(
        "Backend Engineer",
        "Must have Node, Node.js, and Python experience.",
    )

    assert technologies == ("node.js", "python")
    assert required == ("node.js", "python")


def test_scala_is_detected_as_a_language_and_required_cue() -> None:
    technologies, required = extract_job_technologies(
        "Backend Engineer",
        "Scala is required; Kotlin is nice to have.",
    )

    assert technologies == ("kotlin", "scala")
    assert required == ("scala",)


@pytest.mark.parametrize(
    ("eligibility", "location", "expected"),
    [
        ("WORLDWIDE", "Worldwide", SignalStatus.COMPATIBLE),
        ("EU_REMOTE", "European Union", SignalStatus.COMPATIBLE),
        ("SPAIN_ONLY", "Spain", SignalStatus.COMPATIBLE),
        ("COUNTRY_RESTRICTED", "US only", SignalStatus.INCOMPATIBLE),
        ("UNKNOWN", None, SignalStatus.UNKNOWN),
    ],
)
def test_geographic_eligibility_conservative_cases(eligibility, location, expected) -> None:
    facts = facts_for(remote_eligibility=eligibility, location=location)

    result = evaluate_job(facts, make_config())

    assert result.signals.geography.status is expected
    if expected is SignalStatus.UNKNOWN:
        assert result.decision is not PreFilterDecision.REJECT


@pytest.mark.parametrize("location", ["Europe", "Europe, Israel", "USA, Canada, Europe", "EU", "EMEA"])
def test_remote_regional_restrictions_include_a_candidate_in_spain(location: str) -> None:
    result = evaluate_job(
        facts_for(remote_eligibility="COUNTRY_RESTRICTED", location=location),
        make_config(),
    )

    assert result.signals.geography.status is SignalStatus.COMPATIBLE


def test_eu_remote_works_for_a_candidate_in_spain() -> None:
    result = evaluate_job(facts_for(remote_eligibility="EU_REMOTE", location=None), make_config())

    assert result.signals.geography.status is SignalStatus.COMPATIBLE


def test_onsite_location_in_another_country_is_incompatible() -> None:
    result = evaluate_job(
        facts_for(
            remote_policy="ONSITE",
            remote_eligibility="UNKNOWN",
            location="New York, US",
        ),
        make_config(),
    )

    assert result.signals.geography.status is SignalStatus.INCOMPATIBLE
    assert result.decision is PreFilterDecision.REJECT


@pytest.mark.parametrize(
    ("location", "expected"),
    [
        ("Remote Spain", SignalStatus.COMPATIBLE),
        ("Remote Europe", SignalStatus.COMPATIBLE),
        ("Remote EU", SignalStatus.COMPATIBLE),
        ("Remote EMEA", SignalStatus.COMPATIBLE),
        ("Remote - Global", SignalStatus.COMPATIBLE),
        ("Remote Worldwide", SignalStatus.COMPATIBLE),
        ("Remote UK", SignalStatus.INCOMPATIBLE),
        ("Remote Poland", SignalStatus.INCOMPATIBLE),
        ("Remote US", SignalStatus.INCOMPATIBLE),
        ("Remote APAC", SignalStatus.INCOMPATIBLE),
        ("Remote Asia-Pacific", SignalStatus.INCOMPATIBLE),
        ("Remote", SignalStatus.UNKNOWN),
    ],
)
def test_explicit_remote_location_restrictions_are_parsed_without_ats_flags(
    location: str,
    expected: SignalStatus,
) -> None:
    result = evaluate_job(
        facts_for(
            location=location,
            remote_policy=None,
            remote_eligibility="UNKNOWN",
        ),
        make_config(),
    )

    assert result.signals.geography.status is expected
    if expected is SignalStatus.INCOMPATIBLE:
        assert result.decision is PreFilterDecision.REJECT
    elif expected is SignalStatus.UNKNOWN:
        assert result.decision is PreFilterDecision.REVIEW


@pytest.mark.parametrize(
    "eligibility",
    ["COUNTRY_RESTRICTED", "EU_REMOTE", "WORLDWIDE"],
)
def test_explicit_remote_country_restriction_wins_over_global_wording(
    eligibility: str,
) -> None:
    result = evaluate_job(
        facts_for(
            location="Remote US — Global team",
            remote_policy="REMOTE",
            remote_eligibility=eligibility,
        ),
        make_config(),
    )

    assert result.signals.geography.status is SignalStatus.INCOMPATIBLE
    assert result.decision is PreFilterDecision.REJECT


def test_country_restricted_remote_global_without_a_country_remains_unknown() -> None:
    result = evaluate_job(
        facts_for(
            location="Remote Global",
            remote_policy="REMOTE",
            remote_eligibility="COUNTRY_RESTRICTED",
        ),
        make_config(),
    )

    assert result.signals.geography.status is SignalStatus.UNKNOWN
    assert result.decision is PreFilterDecision.REVIEW


@pytest.mark.parametrize("eligibility", ["WORLDWIDE", "SPAIN_ONLY", "EU_REMOTE", "EMEA_REMOTE"])
def test_unqualified_remote_location_keeps_known_structured_eligibility(eligibility: str) -> None:
    result = evaluate_job(
        facts_for(
            location="Remote",
            remote_policy="REMOTE",
            remote_eligibility=eligibility,
        ),
        make_config(),
    )

    assert result.signals.geography.status is SignalStatus.COMPATIBLE


@pytest.mark.parametrize("location", ["Paris, France", "San Francisco", "SF Office"])
def test_specific_non_remote_location_outside_spain_is_rejected_when_work_mode_is_missing(
    location: str,
) -> None:
    result = evaluate_job(
        facts_for(
            location=location,
            remote_policy=None,
            remote_eligibility="UNKNOWN",
        ),
        make_config(),
    )

    assert result.signals.geography.status is SignalStatus.INCOMPATIBLE
    assert result.decision is PreFilterDecision.REJECT


def test_specific_non_remote_location_in_spain_is_compatible_when_work_mode_is_missing() -> None:
    result = evaluate_job(
        facts_for(
            location="Madrid, Spain",
            remote_policy=None,
            remote_eligibility="UNKNOWN",
        ),
        make_config(),
    )

    assert result.signals.geography.status is SignalStatus.COMPATIBLE


def test_acceptable_eu_location_matches_a_listed_eu_country() -> None:
    result = evaluate_job(
        facts_for(remote_policy="ONSITE", location="Madrid, Spain"),
        make_config(
            preferences={
                "acceptable_locations": ["EU"],
                "remote_preference": "ONSITE_ONLY",
            }
        ),
    )

    assert result.signals.geography.status is SignalStatus.COMPATIBLE


@pytest.mark.parametrize(
    ("salary_min", "salary_max", "expected"),
    [
        ("30000", "45000", SalaryEvaluation.BELOW_MINIMUM),
        ("50000", "65000", SalaryEvaluation.BETWEEN_MINIMUM_AND_TARGET),
        ("70000", "80000", SalaryEvaluation.MEETS_TARGET),
        (None, None, SalaryEvaluation.UNKNOWN),
    ],
)
def test_salary_evaluation(salary_min, salary_max, expected) -> None:
    result = evaluate_job(
        facts_for(salary_min=salary_min, salary_max=salary_max),
        make_config(),
    )

    assert result.signals.salary.evaluation is expected


def test_salary_currency_or_period_mismatch_is_unknown_without_conversion() -> None:
    result = evaluate_job(facts_for(currency="USD"), make_config())

    assert result.signals.salary.evaluation is SalaryEvaluation.UNKNOWN
    assert "no conversion" in result.signals.salary.reason


def test_missing_but_learnable_stack_is_review_not_reject() -> None:
    candidate = make_config(preferences={"willing_to_learn_technologies": ["k8s"]})
    result = evaluate_job(facts_for(description="We use Kubernetes."), candidate)

    assert result.signals.technology.missing_technologies == ("kubernetes",)
    assert result.signals.technology.learnable_technologies == ("kubernetes",)
    assert result.decision is PreFilterDecision.REVIEW


def test_related_language_is_transferable_and_not_a_critical_mismatch() -> None:
    result = evaluate_job(
        facts_for(description="Must have Kotlin experience."),
        make_config(),
    )

    assert result.signals.technology.transferable_technologies == ("kotlin",)
    assert result.signals.technology.critical_mismatches == ()
    assert result.decision is PreFilterDecision.REVIEW


def test_explicit_mandatory_unmatched_stack_can_be_a_critical_mismatch() -> None:
    candidate = make_config(profile={"primary_skills": [], "secondary_skills": [], "technologies": []})
    result = evaluate_job(facts_for(description="AWS is required."), candidate)

    assert result.signals.technology.critical_mismatches == ("aws",)
    assert result.decision is PreFilterDecision.REJECT


def test_seniority_above_configured_maximum_is_rejected() -> None:
    result = evaluate_job(facts_for(title="Staff Backend Engineer"), make_config())

    assert result.signals.seniority.status is SignalStatus.INCOMPATIBLE
    assert result.decision is PreFilterDecision.REJECT


def test_unknown_seniority_with_a_boundary_is_review_not_reject() -> None:
    result = evaluate_job(facts_for(title="Backend Engineer", description="Uses Python."), make_config())

    assert result.signals.seniority.status is SignalStatus.UNKNOWN
    assert result.decision is PreFilterDecision.REVIEW


@pytest.mark.parametrize(
    "title",
    [
        "Product Designer",
        "Brand Designer",
        "Head of Commercial Legal",
        "Creative Producer",
        "Solutions Marketer",
        "Product Manager",
        "Talent Recruiter",
        "Finance Operations Manager",
        "Community Manager",
        "Growth Manager",
    ],
)
def test_explicit_non_technical_role_families_are_hard_rejected(title: str) -> None:
    result = evaluate_job(facts_for(title=title), make_config())

    assert result.decision is PreFilterDecision.REJECT
    assert any("non-target" in reason for reason in result.reasons)


@pytest.mark.parametrize(
    "title",
    [
        "Associate HRBP",
        "Product",
        "Analyst",
        "Analyst II, Credit",
        "Solutions Consultant, Commercial, France",
        "GTM Operations Engineer",
        "Open Application",
        "General Application",
    ],
)
def test_unscoped_or_non_engineering_role_families_are_hard_rejected(title: str) -> None:
    result = evaluate_job(facts_for(title=title), make_config())

    assert result.decision is PreFilterDecision.REJECT
    assert any("non-target" in reason for reason in result.reasons)


@pytest.mark.parametrize(
    "title",
    [
        "Data Analyst",
        "Solutions Engineer",
        "Field Engineer / FDE",
        "Analytics Engineer",
        "Product Engineer",
        "Backend Engineer",
        "Platform Engineer",
        "Infrastructure Engineer",
    ],
)
def test_technical_and_potentially_relevant_role_families_are_not_hard_rejected(
    title: str,
) -> None:
    result = evaluate_job(facts_for(title=title), make_config())

    assert result.decision is not PreFilterDecision.REJECT


@pytest.mark.parametrize(
    "title",
    [
        "Backend Engineer",
        "Platform Engineer",
        "Infrastructure Engineer",
        "Developer Tools Engineer",
        "AI Platform Engineer",
        "Full Stack Software Engineer",
    ],
)
def test_target_technical_role_families_are_not_rejected(title: str) -> None:
    result = evaluate_job(facts_for(title=title), make_config())

    assert result.decision is not PreFilterDecision.REJECT


def test_us_city_without_remote_eligibility_is_not_compatible() -> None:
    result = evaluate_job(
        facts_for(
            title="Software Engineer, Early Career",
            location="San Francisco",
            remote_policy=None,
            remote_eligibility="UNKNOWN",
        ),
        make_config(),
    )

    assert result.signals.geography.status is SignalStatus.INCOMPATIBLE
    assert result.decision is PreFilterDecision.REJECT


def test_role_match_does_not_match_only_on_generic_engineer_token() -> None:
    candidate = make_config(
        preferences={
            "preferred_roles": [
                "Backend Engineer",
                "Backend Developer",
                "Software Engineer",
                "Software Developer",
                "Platform Engineer",
                "Full Stack Engineer",
            ]
        }
    )

    service_desk = evaluate_job(
        facts_for(title="Tier III Service Desk Engineer"),
        candidate,
    )
    backend = evaluate_job(facts_for(title="Junior Backend Engineer"), candidate)
    generic_software = evaluate_job(facts_for(title="Software Engineer"), candidate)

    assert service_desk.signals.preferred_role.status is SignalStatus.UNKNOWN
    assert backend.signals.preferred_role.status is SignalStatus.COMPATIBLE
    assert generic_software.signals.preferred_role.status is SignalStatus.COMPATIBLE


def test_pass_review_and_reject_decisions_are_explainable() -> None:
    candidate = make_config(profile={"years_of_experience": 1}, preferences={"preferred_roles": ["Backend Engineer"]})
    passed = evaluate_job(facts_for(description="1 year of professional experience required. Build APIs with Python."), candidate)
    reviewed = evaluate_job(
        facts_for(remote_eligibility="UNKNOWN", location=None, salary_min=None, salary_max=None),
        candidate,
    )
    rejected = evaluate_job(facts_for(salary_min="30000", salary_max="40000"), candidate)

    assert passed.decision is PreFilterDecision.PASS
    assert passed.reasons
    assert reviewed.decision is PreFilterDecision.REVIEW
    assert rejected.decision is PreFilterDecision.REJECT
    assert any("below the configured floor" in reason for reason in rejected.reasons)


def test_job_facts_can_be_built_from_a_persisted_job_and_source() -> None:
    job = SimpleNamespace(
        title="Senior Backend Engineer",
        description="Python is required.",
        location="Spain",
        remote_policy="REMOTE",
    )
    source = SimpleNamespace(
        remote_policy="REMOTE",
        remote_eligibility="SPAIN_ONLY",
        salary_min=Decimal("50000"),
        salary_max=Decimal("70000"),
        salary_currency="EUR",
        salary_period="YEAR",
        employment_type="FULL_TIME",
    )

    facts = JobFacts.from_job_source(job, source)

    assert facts.inferred_seniority.value == "SENIOR"
    assert facts.required_technologies == ("python",)
    assert facts.currency == "EUR"


def test_remotive_fixture_flows_through_job_facts_and_prefilter_without_network() -> None:
    payload = json.loads(REMOTIVE_FIXTURE.read_text(encoding="utf-8"))
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    client = httpx.Client(transport=transport)
    candidate = load_candidate_config(EXAMPLE_CONFIG)
    try:
        connector = RemotiveConnector(client=client, limit=2)
        offers = connector.fetch_jobs()
    finally:
        client.close()

    facts = [JobFacts.from_normalized_job(offer) for offer in offers]
    results = [evaluate_job(job_facts, candidate) for job_facts in facts]

    assert facts[0].inferred_seniority.value == "LEAD"
    assert facts[0].salary_min == Decimal("50000")
    assert results[0].signals.geography.status is SignalStatus.COMPATIBLE
    assert results[0].decision is PreFilterDecision.REJECT
    assert results[1].signals.geography.status is SignalStatus.COMPATIBLE
    assert results[1].decision is PreFilterDecision.REJECT
