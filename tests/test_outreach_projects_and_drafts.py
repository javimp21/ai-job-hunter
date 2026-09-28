import json
from decimal import Decimal

import pytest

from ai_job_hunter.candidates.profile import CandidateProfile
from ai_job_hunter.outreach.drafts import (
    DraftChannel,
    DraftTemplate,
    generate_draft,
)
from ai_job_hunter.outreach.projects import (
    CandidateProject,
    CandidateProjectsConfigError,
    load_candidate_projects,
    select_relevant_project,
)


@pytest.fixture
def projects():
    return [
        CandidateProject(
            name="Backend agents demo",
            url="https://example.test/backend-agents",
            short_description="A small backend API with agent workflows.",
            technologies=("Python", "FastAPI"),
            tags=("backend", "agents", "api"),
        ),
        CandidateProject(
            name="Garden journal",
            url="https://example.test/garden",
            short_description="A personal gardening journal.",
            technologies=("React",),
            tags=("frontend",),
        ),
    ]


@pytest.fixture
def candidate_profile():
    return CandidateProfile(
        current_role="Backend Engineer",
        years_of_experience=Decimal("4"),
        technologies=["Python", "PostgreSQL"],
    )


def test_optional_project_config_missing_file_returns_empty(tmp_path):
    assert load_candidate_projects(tmp_path / "candidate_projects.local.json") == []


def test_candidate_projects_loads_supported_local_json(tmp_path):
    path = tmp_path / "candidate_projects.local.json"
    path.write_text(
        json.dumps(
            {
                "projects": [
                    {
                        "name": "Example API",
                        "url": "https://example.test/api",
                        "short_description": "A small API project.",
                        "technologies": ["Python"],
                        "tags": ["backend"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    assert load_candidate_projects(path)[0].name == "Example API"


def test_candidate_project_rejects_non_public_or_non_http_url():
    with pytest.raises(ValueError, match=r"HTTP\(S\)"):
        CandidateProject(
            name="Unsafe", url="javascript:alert(1)", short_description="A project"
        )


def test_project_selection_picks_one_relevant_project_and_none_for_irrelevant_role(projects):
    selection = select_relevant_project("Backend AI Engineer", ("Python",), projects)
    assert selection.project is not None
    assert selection.project.name == "Backend agents demo"
    assert len(selection.reasons) >= 1

    unrelated = select_relevant_project("Finance Analyst", ("Excel",), projects)
    assert unrelated.project is None


@pytest.mark.parametrize("template", list(DraftTemplate))
@pytest.mark.parametrize("channel,minimum,maximum", [(DraftChannel.LINKEDIN, 40, 80), (DraftChannel.EMAIL, 80, 130)])
def test_all_five_templates_render_within_channel_word_limits(
    template, channel, minimum, maximum, candidate_profile, projects
):
    if template is DraftTemplate.COLD_OUTREACH:
        draft = generate_draft(
            template,
            channel,
            "Example Company",
            candidate_profile=candidate_profile,
            contact_name=None,
            contact_role=None,
            candidate_projects=projects,
        )
    else:
        draft = generate_draft(
            template,
            channel,
            "Example Company",
            job_title="Backend Engineer",
            job_technologies=("Python", "Kafka"),
            candidate_profile=candidate_profile,
            contact_name=None,
            contact_role=None,
            candidate_projects=projects,
        )
    assert minimum <= draft.word_count <= maximum
    assert draft.body.startswith("Hello,")
    assert draft.channel is channel
    if channel is DraftChannel.EMAIL:
        assert draft.subject
    else:
        assert draft.subject is None


def test_draft_uses_only_supplied_candidate_facts_and_generic_greeting(candidate_profile):
    draft = generate_draft(
        DraftTemplate.RECRUITER_INTRO,
        DraftChannel.LINKEDIN,
        "Example Company",
        job_title="Backend Engineer",
        job_technologies=("Python", "Kafka"),
        candidate_profile=candidate_profile,
    )
    assert "Hello," in draft.body
    assert "Backend Engineer" in draft.body
    assert "4 years of experience" in draft.body
    assert "Python" in draft.body
    assert "Kafka" not in draft.body
    for fabricated in ("I've been following", "I love your product", "your team and I", "Hi Alex"):
        assert fabricated.casefold() not in draft.body.casefold()


def test_draft_uses_singular_year_for_one_year_of_experience():
    profile = CandidateProfile(years_of_experience=Decimal("1"))
    draft = generate_draft(
        DraftTemplate.RECRUITER_INTRO,
        DraftChannel.LINKEDIN,
        "Example Company",
        job_title="Backend Engineer",
        candidate_profile=profile,
    )

    assert "I have 1 year of experience." in draft.body
    assert "1 years of experience" not in draft.body


def test_draft_uses_complete_primary_role_label_without_ellipsis():
    profile = CandidateProfile(
        current_role="Backend Software Engineer / Java Backend Developer",
        years_of_experience=Decimal("1"),
    )
    draft = generate_draft(
        DraftTemplate.RECRUITER_INTRO,
        DraftChannel.LINKEDIN,
        "Example Company",
        job_title="Backend Engineer",
        candidate_profile=profile,
    )

    assert "My current role is Backend Software Engineer." in draft.body
    assert "Develo…" not in draft.body
    assert "…" not in draft.body


def test_draft_omits_overlong_single_role_instead_of_cutting_it():
    profile = CandidateProfile(
        current_role="Lead Backend Platform Infrastructure Engineer with Distributed Systems Specialization",
        years_of_experience=Decimal("1"),
    )
    draft = generate_draft(
        DraftTemplate.RECRUITER_INTRO,
        DraftChannel.LINKEDIN,
        "Example Company",
        job_title="Backend Engineer",
        candidate_profile=profile,
    )

    assert "My current role is" not in draft.body
    assert "Distributed Systems Specialization" not in draft.body
    assert "…" not in draft.body


def test_draft_never_adds_an_irrelevant_project(projects):
    draft = generate_draft(
        DraftTemplate.RECRUITER_INTRO,
        DraftChannel.LINKEDIN,
        "Example Company",
        job_title="Finance Analyst",
        job_technologies=("Excel",),
        candidate_projects=projects,
    )
    assert draft.project is None
    assert "Backend agents demo" not in draft.body
    assert "Garden journal" not in draft.body


def test_cold_outreach_can_be_generated_without_a_job(candidate_profile):
    draft = generate_draft(
        DraftTemplate.COLD_OUTREACH,
        DraftChannel.LINKEDIN,
        "Example Company",
        candidate_profile=candidate_profile,
    )
    assert "I don’t have a specific" not in draft.body
    assert "specific open position" not in draft.body
    assert "Example Company" in draft.body


def test_job_templates_require_a_job_and_cold_outreach_omits_one():
    with pytest.raises(ValueError, match="job_title is required"):
        generate_draft(
            DraftTemplate.RECRUITER_INTRO, DraftChannel.LINKEDIN, "Example Company"
        )


def test_malformed_candidate_projects_reports_configuration_error(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not valid", encoding="utf-8")
    with pytest.raises(CandidateProjectsConfigError, match="invalid JSON"):
        load_candidate_projects(path)
