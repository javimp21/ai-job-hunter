from decimal import Decimal

import pytest

from ai_job_hunter.candidates import CandidateConfig, JobFacts, evaluate_job
from ai_job_hunter.candidates.experience import (
    ExperienceExpressionKind, ExperienceOutcome, ExperienceStrength,
    assess_experience, extract_experience_requirements,
)
from ai_job_hunter.decision_engine import (
    DecisionCache, DecisionEvidence, FinalDecision, JevAnswers, JevSignal,
    apply_decision_policy, apply_decision_policy_v2, build_decision_contexts,
    evaluate_job_decision,
)
from ai_job_hunter.domain.normalized_job import NormalizedJob


def candidate(years=1, **preferences):
    return CandidateConfig.model_validate({
        "profile": {"years_of_experience": years, "current_country": "Spain", "technologies": ["Java"]},
        "preferences": preferences,
    })


def offer(description):
    return NormalizedJob(
        provider="fixture", title="Backend Engineer", description=description,
        location="Spain", remote_policy="REMOTE", remote_eligibility="SPAIN_ONLY",
    )


def assessment(text, years=1, **preferences):
    return evaluate_job(JobFacts.from_normalized_job(offer(text)), candidate(years, **preferences)).signals.experience


@pytest.mark.parametrize("text,outcome", [
    ("At least 1 year of professional experience required.", "MEETS"),
    ("2 years of experience required.", "STRETCH"),
    ("3 years of experience required.", "STRETCH"),
    ("3+ years of experience required.", "STRETCH"),
    ("3-5 years of experience required.", "INCOMPATIBLE"),
    ("3–5+ years of experience required.", "INCOMPATIBLE"),
    ("3 to 5+ years as a backend engineer at a modern tech company", "INCOMPATIBLE"),
    ("4+ years of experience required.", "INCOMPATIBLE"),
    ("At least 4 years of experience required.", "INCOMPATIBLE"),
    ("Minimum 4 years of experience required.", "INCOMPATIBLE"),
    ("5 years of experience required.", "INCOMPATIBLE"),
    ("You have less than two years of engineering experience.", "MEETS"),
    ("At most one year of professional experience.", "MEETS"),
    ("Up to 3 years of professional experience.", "MEETS"),
    ("Al menos tres años de experiencia profesional.", "STRETCH"),
    ("Entre 3 y 5 años de experiencia.", "INCOMPATIBLE"),
    ("Entre 2 años y 4 años de experiencia.", "STRETCH"),
    ("2 years - 4 years of experience", "STRETCH"),
    ("2 years to 4 years of experience", "STRETCH"),
    ("3 years to 5+ years of experience", "INCOMPATIBLE"),
    ("Experiencia requerida: de 3 a 5 años de experiencia.", "INCOMPATIBLE"),
    ("Más de 3 años de experiencia.", "INCOMPATIBLE"),
    (">=3 years of experience", "STRETCH"),
    (">3 years of experience", "INCOMPATIBLE"),
    ("Less than one year of experience.", "INCOMPATIBLE"),
    ("We build Java services.", "UNKNOWN"),
    ("5 years of experience or equivalent education.", "UNKNOWN"),
    ("3 years of experience or 1 year of experience and a degree.", "UNKNOWN"),
    ("2 years of experience in Java.", "STRETCH"),
    ("1 year of experience in Java.", "UNKNOWN"),
    ("1 year of Java experience required.", "UNKNOWN"),
    ("1 año de experiencia en Java.", "UNKNOWN"),
    ("5–3 years of experience.", "UNKNOWN"),
])
def test_candidate_relative_experience_policy(text, outcome):
    result = assessment(text)
    assert result.outcome.value == outcome
    assert result.shortfall_years is None or result.shortfall_years >= 0


@pytest.mark.parametrize("text", [
    "Nice to have:\n5+ years of experience.",
    "Preferred qualifications\n5 years of experience.\nResponsibilities\nBuild Java services.",
    "Requisitos deseables:\n5 años de experiencia.",
    "5 years of experience is a plus.",
    "<h3>Nice to have</h3><ul><li>5+ years of experience</li></ul>",
])
def test_preferred_experience_never_hard_rejects(text):
    result = assessment(text)
    assert result.outcome is ExperienceOutcome.UNKNOWN
    assert not result.mandatory
    assert result.preferred
    assert evaluate_job(JobFacts.from_normalized_job(offer(text)), candidate()).decision.value != "REJECT"


def test_preferred_section_resets_and_html_preserves_provenance():
    result = assessment("<h3>Nice to have</h3><p>8 years of experience.</p><h3>Requirements</h3><p>1 year of professional experience.</p>")
    assert result.outcome is ExperienceOutcome.MEETS
    assert result.mandatory[0].minimum_years == 1
    assert result.preferred[0].minimum_years == 8
    assert result.evidence and "line " in result.evidence[0]


def test_up_to_experience_is_an_inclusive_upper_bound_not_a_minimum():
    requirements = extract_experience_requirements("Up to 3 years of professional experience.")
    assert len(requirements) == 1
    requirement = requirements[0]
    assert requirement.kind is ExperienceExpressionKind.UPPER_BOUND
    assert requirement.strength is ExperienceStrength.MANDATORY
    assert requirement.minimum_years is None
    assert requirement.maximum_years == Decimal("3")
    assert assess_experience(requirements, Decimal("3")).outcome is ExperienceOutcome.MEETS
    assert assess_experience(requirements, Decimal("4")).outcome is ExperienceOutcome.INCOMPATIBLE


def test_bare_year_count_stays_ambiguous_and_no_requirement_stays_unknown():
    bare = assess_experience(extract_experience_requirements("3 years"), Decimal("0"))
    assert bare.outcome is ExperienceOutcome.UNKNOWN
    assert bare.ambiguous and not bare.mandatory
    assert assessment("Experience depends on the project scope.").outcome is ExperienceOutcome.UNKNOWN


def test_explicit_section_and_optional_heading_provenance_controls_strength():
    required = extract_experience_requirements("Requirements:\n4+ years")
    assert len(required) == 1
    assert required[0].strength is ExperienceStrength.MANDATORY
    assert required[0].minimum_years == Decimal("4")
    required_experience = extract_experience_requirements("Required experience\n4+ years")
    assert len(required_experience) == 1
    assert required_experience[0].strength is ExperienceStrength.MANDATORY

    for heading in ("Desired qualifications", "Additional qualifications"):
        optional = extract_experience_requirements(f"{heading}\n5 years of experience")
        assert len(optional) == 1
        assert optional[0].strength is ExperienceStrength.PREFERRED


def test_company_requirement_is_not_discarded_as_company_history():
    for text in (
        "The company requires candidates with 5 years of experience.",
        "La empresa requiere candidatos con 5 años de experiencia.",
    ):
        requirements = extract_experience_requirements(text)
        assert len(requirements) == 1
        assert requirements[0].strength is ExperienceStrength.MANDATORY
        assert assessment(text).outcome is ExperienceOutcome.INCOMPATIBLE


@pytest.mark.parametrize(
    "text,kind,minimum,maximum,plus,strength",
    [
        ("3 years of experience", ExperienceExpressionKind.FLOOR, 3, None, False, ExperienceStrength.MANDATORY),
        ("3+ years of experience", ExperienceExpressionKind.FLOOR, 3, None, True, ExperienceStrength.MANDATORY),
        ("3-5 years of experience", ExperienceExpressionKind.RANGE, 3, 5, False, ExperienceStrength.MANDATORY),
        ("3–5+ years of experience", ExperienceExpressionKind.RANGE, 3, 5, True, ExperienceStrength.MANDATORY),
        ("At least 4 years of experience", ExperienceExpressionKind.FLOOR, 4, None, False, ExperienceStrength.MANDATORY),
        ("Minimum 4 years of experience", ExperienceExpressionKind.FLOOR, 4, None, False, ExperienceStrength.MANDATORY),
        ("3 years preferred", ExperienceExpressionKind.FLOOR, 3, None, False, ExperienceStrength.PREFERRED),
        ("3 years nice to have", ExperienceExpressionKind.FLOOR, 3, None, False, ExperienceStrength.PREFERRED),
        ("Up to 3 years of experience", ExperienceExpressionKind.UPPER_BOUND, None, 3, False, ExperienceStrength.MANDATORY),
    ],
)
def test_explicit_experience_expressions_preserve_bounds_and_preference(
    text, kind, minimum, maximum, plus, strength
):
    requirements = extract_experience_requirements(text)
    assert len(requirements) == 1
    requirement = requirements[0]
    assert requirement.kind is kind
    assert requirement.minimum_years == (Decimal(minimum) if minimum is not None else None)
    assert requirement.maximum_years == (Decimal(maximum) if maximum is not None else None)
    assert requirement.upper_plus is plus
    assert requirement.strength is strength


@pytest.mark.parametrize("text", [
    "Our company has 15 years of experience building software.",
    "Our team has 20 years of combined experience.",
    "Founded 10 years ago, we value experience.",
    "We have 15 years of experience delivering products.",
    "Con más de 20 años de experiencia en el sector, somos líderes en pagos.",
    "With over 20 years of experience, Acme is a leader in fintech.",
    "Somos una empresa con más de 15 años de experiencia en pagos.",
    "We are a business with 20 years of experience.",
    "20 years as a market leader.",
    "Nuestra empresa fue fundada hace 10 años.",
    "5 years of product history.",
])
def test_incidental_years_cannot_be_mandatory(text):
    assert assessment(text).outcome is ExperienceOutcome.UNKNOWN


@pytest.mark.parametrize("heading", ["About us", "About the company", "Benefits", "What we offer", "Sobre nosotros", "Beneficios"])
def test_company_sections_cannot_be_mandatory_and_reset_at_requirements(heading):
    result = assessment(f"{heading}\nOver 20 years of experience in payments.\nRequirements\n1 year of professional experience required.")
    assert all(item.minimum_years != 20 for item in result.mandatory)
    assert result.outcome is ExperienceOutcome.MEETS
    assert result.mandatory[0].minimum_years == 1
    assert not result.ambiguous


def test_applicant_years_in_industry_are_not_mistaken_for_company_history():
    assert assessment("You need 5 years of experience in the payments industry.").outcome is ExperienceOutcome.INCOMPATIBLE
    assert assessment("We are looking for candidates with 5 years of experience.").outcome is ExperienceOutcome.INCOMPATIBLE


@pytest.mark.parametrize("heading", ["What you'll bring", "Your profile", "Who you are", "Your qualifications", "The role", "Job description", "Tu perfil", "Lo que buscamos", "Qué buscamos"])
def test_applicant_headings_end_company_section(heading):
    text = f"About us\nAcme builds payments.\n{heading}\n5+ years of experience."
    assert assessment(text).outcome is ExperienceOutcome.INCOMPATIBLE


def test_engineering_leadership_duration_is_not_company_market_history():
    assert assessment("5 years as a leader of engineering teams").outcome is ExperienceOutcome.INCOMPATIBLE


def test_range_is_not_a_second_floor_or_an_exclusive_maximum():
    requirements = extract_experience_requirements("3 to 5+ years of experience required.")
    assert len(requirements) == 1
    assert requirements[0].kind is ExperienceExpressionKind.RANGE
    assert requirements[0].minimum_years == 3 and requirements[0].maximum_years == 5
    assert requirements[0].upper_plus
    assert assess_experience(requirements, Decimal(8)).outcome is ExperienceOutcome.MEETS


def test_tolerances_are_configurable_and_candidate_aware():
    assert assessment("3 years of experience", 3).outcome is ExperienceOutcome.MEETS
    assert assessment("3-5 years of experience", 2).outcome is ExperienceOutcome.STRETCH
    assert assessment("3 years of experience", 1, experience_floor_shortfall_tolerance=0).outcome is ExperienceOutcome.INCOMPATIBLE
    assert assessment("3-5 years of experience", 1, experience_range_shortfall_tolerance=2).outcome is ExperienceOutcome.STRETCH
    assert assessment("1 year of experience", None).outcome is ExperienceOutcome.UNKNOWN
    assert assessment("More than 3 years of experience", 3, experience_floor_shortfall_tolerance=0).outcome is ExperienceOutcome.INCOMPATIBLE


def test_negative_tolerance_is_invalid():
    with pytest.raises(ValueError):
        candidate(experience_floor_shortfall_tolerance=-1)
    with pytest.raises(ValueError):
        candidate(experience_range_shortfall_tolerance=-1)


def evidence():
    names = ("role_relevance", "experience_accessibility", "backend_relevance", "stack_transferability", "requirements_flexibility", "career_value", "observable_role_quality")
    scores = {"backend_relevance", "career_value", "observable_role_quality"}
    return DecisionEvidence(
        answers=JevAnswers(**{name: JevSignal(question_type="score" if name in scores else "noul", value=1, confidence=1) for name in names}),
        model_version="fake", engine_configuration="fake",
    )


@pytest.mark.parametrize("policy", [apply_decision_policy, apply_decision_policy_v2])
@pytest.mark.parametrize("text,expected", [("3 years of experience", "REVIEW"), ("No numeric requirement.", "REVIEW"), ("3-5 years of experience", "SKIP")])
def test_maximal_jev_cannot_override_explicit_experience(policy, text, expected):
    context = build_decision_contexts([offer(text + "\n" + "Build Java services. " * 100)], candidate())[0]
    assert policy(context, evidence()).final_decision.value == expected


def test_cached_result_without_jev_evidence_cannot_bypass_unknown_ceiling(tmp_path):
    context = build_decision_contexts([offer("No numeric requirement.")], candidate())[0]
    class Engine:
        cache_identity = "fake"
        def evaluate(self, context):
            pytest.fail("Must use the already-cached entry without an external evaluation")
    cache = DecisionCache(tmp_path / "cache.json")
    # Simulate a stored final recommendation which has no replayable evidence.
    result = apply_decision_policy(context, evidence()).model_copy(update={"final_decision": FinalDecision.APPLY, "jev_answers": None})
    cache.set(cache.key_for(context, Engine.cache_identity), result)
    assert evaluate_job_decision(context, Engine(), cache=cache).final_decision is FinalDecision.REVIEW


def test_incompatible_experience_skips_jev_and_cache(tmp_path):
    class NeverEngine:
        cache_identity = "fake"
        def evaluate(self, context):
            pytest.fail("Hard experience mismatch must not call Jev")
    context = build_decision_contexts([offer("3 to 5+ years as a backend engineer at a modern tech company")], candidate())[0]
    cache = DecisionCache(tmp_path / "cache.json")
    result = evaluate_job_decision(context, NeverEngine(), cache=cache)
    assert result.final_decision is FinalDecision.SKIP
    assert not cache.path.exists()
