from decimal import Decimal

from ai_job_hunter.application_prep.drafting import draft_answers
from ai_job_hunter.application_prep.models import (
    ApplicationAnswerStatus,
    ApplicationQuestion,
    ApplicationQuestionHandling,
    ApplicationQuestionType,
    CandidateWritingStyle,
)
from ai_job_hunter.candidates.profile import CandidateConfig
from ai_job_hunter.domain.normalized_job import SalaryPeriod
from ai_job_hunter.outreach.projects import CandidateProject


def _candidate(*, salary=True):
    preferences = {
        "relocation_willingness": True,
        "willing_to_learn_technologies": ["Kotlin"],
    }
    if salary:
        preferences.update(
            {
                "minimum_salary": Decimal("55000"),
                "target_salary": Decimal("70000"),
                "salary_currency": "EUR",
                "salary_period": SalaryPeriod.YEAR,
            }
        )
    return CandidateConfig.model_validate(
        {
            "profile": {
                "current_role": "Backend Engineer",
                "years_of_experience": Decimal("4"),
                "primary_skills": ["Python", "PostgreSQL"],
                "technologies": ["Docker"],
                "languages": ["English", "Spanish"],
                "education": "BSc in Computer Science",
                "current_country": "Spain",
                "work_authorization": ["Spain"],
            },
            "preferences": preferences,
        }
    )


def _question(identifier: str, label: str, **overrides) -> ApplicationQuestion:
    values = {
        "id": identifier,
        "label": label,
        "extracted_from": "fixture",
        "confidence": 1.0,
        "normalized_type": ApplicationQuestionType.TEXTAREA,
        "handling": ApplicationQuestionHandling.AUTO_ANSWERABLE,
    }
    values.update(overrides)
    return ApplicationQuestion(**values)


def _draft(questions, *, candidate=None, projects=(), writing_style=None):
    return draft_answers(
        questions,
        candidate=candidate or _candidate(),
        job_title="Backend Engineer",
        job_description="Build Python APIs and backend services.",
        projects=projects,
        writing_style=writing_style,
    )


def test_answers_direct_skill_question_only_from_explicit_candidate_fact():
    questions = [
        _question(
            "python",
            "Do you have experience with Python?",
            normalized_type=ApplicationQuestionType.YES_NO,
            options=("Yes", "No"),
        ),
        _question(
            "kotlin",
            "Do you have experience with Kotlin?",
            normalized_type=ApplicationQuestionType.YES_NO,
            options=("Yes", "No"),
        ),
    ]

    python, kotlin = _draft(questions)

    assert python.answer == "Yes"
    assert python.answer_status is ApplicationAnswerStatus.DRAFTED
    assert python.human_review_required is True
    assert any("Python" in evidence for evidence in python.answer_evidence)
    assert kotlin.answer is None
    assert kotlin.answer_status is ApplicationAnswerStatus.NEEDS_USER_INPUT


def test_profile_facts_can_produce_a_concise_about_me_answer():
    result = _draft([_question("about", "Tell us about yourself")])[0]

    assert result.answer == (
        "I currently work as Backend Engineer. I have 4 years of experience. "
        "My listed skills include Python, PostgreSQL, Docker."
    )
    assert result.answer_status is ApplicationAnswerStatus.DRAFTED
    assert result.human_review_required is True
    assert result.answer_evidence


def test_current_role_does_not_answer_a_generic_job_title_question():
    current_position, generic_title = _draft(
        [
            _question("current", "What is your current job title?"),
            _question("title", "What is your job title?"),
        ]
    )

    assert current_position.answer == "My current role is Backend Engineer."
    assert current_position.answer_status is ApplicationAnswerStatus.DRAFTED
    assert generic_title.answer is None
    assert generic_title.answer_status is ApplicationAnswerStatus.NEEDS_USER_INPUT


def test_salary_is_only_a_review_required_preference_suggestion():
    expected = _question("salary", "What are your salary expectations?", normalized_type=ApplicationQuestionType.NUMBER)
    current = _question("current", "What is your current salary?", normalized_type=ApplicationQuestionType.NUMBER)

    suggested, unanswered = _draft([expected, current])

    assert suggested.answer == "70000"
    assert suggested.answer_status is ApplicationAnswerStatus.REVIEW_REQUIRED
    assert suggested.human_review_required is True
    assert any("target_salary" in evidence for evidence in suggested.answer_evidence)
    assert unanswered.answer is None
    assert unanswered.answer_status is ApplicationAnswerStatus.NEEDS_USER_INPUT


def test_salary_without_preference_is_left_unanswered():
    result = _draft([_question("salary", "Expected compensation")], candidate=_candidate(salary=False))[0]

    assert result.answer is None
    assert result.answer_status is ApplicationAnswerStatus.NEEDS_USER_INPUT


def test_legal_work_authorization_and_sensitive_questions_are_never_answered():
    questions = [
        _question("auth", "Are you legally authorized to work in Spain?"),
        _question("sponsor", "Will you now or in the future require visa sponsorship?"),
        _question("gender", "Please self-identify your gender.", handling=ApplicationQuestionHandling.SENSITIVE),
        _question("veteran", "Are you a veteran?"),
    ]

    answers = _draft(questions)

    assert all(answer.answer is None for answer in answers)
    assert all(answer.answer_status is ApplicationAnswerStatus.NEEDS_USER_INPUT for answer in answers)
    assert all(answer.human_review_required for answer in answers)


def test_file_and_explicitly_unsupported_questions_remain_blank():
    questions = [
        _question("resume", "Upload your resume", normalized_type=ApplicationQuestionType.FILE),
        _question("unknown", "Complete this custom field", handling=ApplicationQuestionHandling.UNSUPPORTED),
    ]

    answers = _draft(questions)

    assert all(answer.answer is None for answer in answers)
    assert all(answer.answer_status is ApplicationAnswerStatus.UNSUPPORTED for answer in answers)


def test_motivation_and_company_knowledge_are_not_fabricated():
    questions = [
        _question("why", "Why are you interested in this role?"),
        _question("company", "What do you know about Example Corp?")
    ]

    answers = _draft(questions)

    assert all(answer.answer is None for answer in answers)
    assert all(answer.answer_status is ApplicationAnswerStatus.NEEDS_USER_INPUT for answer in answers)


def test_relevant_project_answer_uses_only_configured_project_facts():
    project = CandidateProject(
        name="Catalog API",
        url="https://example.test/catalog",
        short_description="A small API for catalog data.",
        technologies=("Python", "FastAPI"),
        tags=("backend",),
    )

    result = _draft(
        [_question("project", "Describe a relevant project")],
        projects=(project,),
    )[0]

    assert result.answer == "My project Catalog API is A small API for catalog data."
    assert result.answer_status is ApplicationAnswerStatus.DRAFTED
    assert any("Candidate project is Catalog API" in evidence for evidence in result.answer_evidence)


def test_existing_user_answer_is_preserved():
    question = _question(
        "existing",
        "Why are you interested in this role?",
        answer="I wrote this myself.",
        answer_status=ApplicationAnswerStatus.USER_PROVIDED,
        human_review_required=False,
    )

    result = _draft([question])[0]

    assert result == question


def test_writing_style_word_limit_keeps_fact_based_answers_concise():
    style = CandidateWritingStyle(max_words_short_answer=20)
    result = _draft(
        [_question("about", "Tell us about yourself")],
        writing_style=style,
    )[0]

    assert len(result.answer.split()) <= 20
    assert result.answer_status is ApplicationAnswerStatus.DRAFTED
