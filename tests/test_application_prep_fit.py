from decimal import Decimal

import pytest

from ai_job_hunter.application_prep.fit import map_candidate_fit
from ai_job_hunter.application_prep.models import (
    CandidateFitStatus,
    JobApplicationRequirement,
    RequirementCategory,
)
from ai_job_hunter.candidates.profile import CandidateConfig
from ai_job_hunter.outreach.projects import CandidateProject


def _candidate(*, skills=(), years=None, willing_to_learn=()):
    return CandidateConfig.model_validate(
        {
            "profile": {
                "primary_skills": list(skills),
                "years_of_experience": years,
            },
            "preferences": {"willing_to_learn_technologies": list(willing_to_learn)},
        }
    )


def _requirement(identifier: str, text: str) -> JobApplicationRequirement:
    return JobApplicationRequirement(
        id=identifier,
        text=text,
        category=RequirementCategory.MUST_HAVE,
        extracted_from="job_description",
        evidence=text,
        confidence=0.95,
    )


def test_skill_matching_is_explicit_and_absence_is_unknown():
    candidate = _candidate(skills=("Java",))
    requirements = [
        _requirement("java", "Experience with Java"),
        _requirement("kotlin", "Experience with Kotlin"),
        _requirement("both", "Experience with Java and Kotlin"),
    ]

    fits = map_candidate_fit(requirements, candidate)

    assert [fit.status for fit in fits] == [
        CandidateFitStatus.MATCH,
        CandidateFitStatus.UNKNOWN,
        CandidateFitStatus.PARTIAL_MATCH,
    ]
    assert fits[0].candidate_skills == ("Java",)
    assert any("explicitly lists Java" in item for item in fits[0].evidence)


def test_learnable_gap_requires_an_explicit_willingness_to_learn():
    requirement = _requirement("kotlin", "Kotlin experience is preferred")

    without_preference = map_candidate_fit([requirement], _candidate())[0]
    with_preference = map_candidate_fit(
        [requirement], _candidate(skills=("Java",), willing_to_learn=("Kotlin",))
    )[0]

    assert without_preference.status is CandidateFitStatus.UNKNOWN
    assert with_preference.status is CandidateFitStatus.LEARNABLE_GAP
    assert any("willingness to learn Kotlin" in item for item in with_preference.evidence)


@pytest.mark.parametrize(
    "years,expected",
    [
        (Decimal("5"), CandidateFitStatus.MATCH),
        (Decimal("3"), CandidateFitStatus.MISSING),
    ],
)
def test_explicit_minimum_years_uses_known_experience(years, expected):
    fit = map_candidate_fit(
        [_requirement("experience", "At least 5 years of experience")],
        _candidate(years=years),
    )[0]

    assert fit.status is expected
    assert fit.candidate_experience == f"{format(years.normalize(), 'f')} years of experience"
    assert any("requirement states at least 5 years" in item for item in fit.evidence)


def test_project_technology_can_support_fit_with_named_evidence():
    project = CandidateProject(
        name="API service",
        url="https://example.test/api",
        short_description="A small service for catalog data.",
        technologies=("Kotlin",),
        tags=("backend",),
    )

    fit = map_candidate_fit(
        [_requirement("kotlin", "Experience with Kotlin")],
        _candidate(),
        projects=(project,),
    )[0]

    assert fit.status is CandidateFitStatus.MATCH
    assert fit.candidate_skills == ("Kotlin",)
    assert fit.candidate_project == "API service"
    assert any("API service" in item and "Kotlin" in item for item in fit.evidence)


def test_unrelated_project_does_not_change_unknown_skill_status():
    project = CandidateProject(
        name="Garden journal",
        url="https://example.test/garden",
        short_description="A personal gardening journal.",
        technologies=("React",),
        tags=("frontend",),
    )

    fit = map_candidate_fit(
        [_requirement("kotlin", "Experience with Kotlin")],
        _candidate(),
        projects=(project,),
    )[0]

    assert fit.status is CandidateFitStatus.UNKNOWN
    assert fit.candidate_project is None


def test_common_lowercase_go_verb_is_not_matched_as_go_language():
    fit = map_candidate_fit(
        [_requirement("copy", "Join OLX and see how far you can go.")],
        _candidate(willing_to_learn=("Go",)),
    )[0]

    assert fit.status is CandidateFitStatus.UNKNOWN
    assert fit.candidate_skills == ()
    assert fit.evidence == ()


def test_generic_software_company_copy_is_not_role_family_evidence():
    candidate = CandidateConfig.model_validate(
        {"profile": {"current_role": "Backend Software Engineer"}, "preferences": {}}
    )
    fit = map_candidate_fit(
        [_requirement("culture", "We are a fast-growing software company that cares about culture.")],
        candidate,
    )[0]

    assert fit.status is CandidateFitStatus.UNKNOWN
