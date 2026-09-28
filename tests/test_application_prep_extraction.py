from __future__ import annotations

from ai_job_hunter.application_prep.extraction import (
    extract_application_questions,
    extract_job_requirements,
)
from ai_job_hunter.application_prep.models import (
    ApplicationQuestionHandling,
    ApplicationQuestionType,
    RequirementCategory,
)


def test_questions_only_come_from_structured_form_data() -> None:
    assert extract_application_questions(None, provider="greenhouse") == []
    assert extract_application_questions({"description": "Are you legally authorized to work?"}, provider="greenhouse") == []
    assert extract_application_questions(
        {"description": "Tell us about yourself", "questions": []}, provider="greenhouse"
    ) == []


def test_greenhouse_question_preserves_label_options_id_type_and_evidence() -> None:
    questions = extract_application_questions(
        {
            "questions": [
                {
                    "id": 4812,
                    "label": "Which languages do you use?",
                    "type": "multi_value_multi_select",
                    "required": True,
                    "options": [{"label": "Python"}, {"label": "Go"}],
                }
            ],
            "description": "This prose must not become a question.",
        },
        provider="greenhouse",
    )

    assert len(questions) == 1
    question = questions[0]
    assert question.label == "Which languages do you use?"
    assert question.source_field_name == "4812"
    assert question.options == ("Python", "Go")
    assert question.normalized_type is ApplicationQuestionType.MULTISELECT
    assert question.required is True
    assert question.confidence > 0.8
    assert "greenhouse.questions[0]" in (question.evidence or "")
    assert "4812" in (question.evidence or "")


def test_greenhouse_documented_nested_field_types_map_without_guessing() -> None:
    questions = extract_application_questions(
        {
            "questions": [
                {
                    "label": "Attach your resume",
                    "required": True,
                    "fields": [{"name": "resume_file", "type": "input_file"}],
                },
                {
                    "label": "How should we contact you?",
                    "required": False,
                    "fields": [
                        {"name": "contact_text", "type": "input_text"},
                        {"name": "contact_notes", "type": "textarea"},
                        {
                            "name": "contact_method",
                            "type": "input_select",
                            "values": [{"value": "email", "label": "Email"}, {"value": "phone", "label": "Phone"}],
                        },
                    ],
                },
                {
                    "label": "Which areas interest you?",
                    "required": False,
                    "fields": [
                        {
                            "name": "interest_areas",
                            "type": "multi_value_multi_select",
                            "values": [{"value": 1, "label": "Platform"}, {"value": 2, "label": "Data"}],
                        }
                    ],
                },
                {
                    "label": "Internal routing field",
                    "fields": [{"name": "hidden", "type": "input_hidden"}],
                },
            ]
        },
        provider="greenhouse",
    )

    assert [question.normalized_type for question in questions] == [
        ApplicationQuestionType.FILE,
        ApplicationQuestionType.TEXT,
        ApplicationQuestionType.TEXTAREA,
        ApplicationQuestionType.SELECT,
        ApplicationQuestionType.MULTISELECT,
        ApplicationQuestionType.UNKNOWN,
    ]
    assert [question.label for question in questions[:2]] == ["Attach your resume", "How should we contact you?"]
    assert questions[1].label == questions[2].label
    assert [question.source_field_name for question in questions] == [
        "resume_file",
        "contact_text",
        "contact_notes",
        "contact_method",
        "interest_areas",
        "hidden",
    ]
    assert [question.required for question in questions[:4]] == [True, False, False, False]
    assert questions[3].options == ("Email", "Phone")
    assert questions[4].options == ("Platform", "Data")
    assert questions[5].handling is ApplicationQuestionHandling.UNSUPPORTED


def test_ashby_application_form_maps_known_types_and_keeps_unknown_unknown() -> None:
    questions = extract_application_questions(
        {
            "applicationFormDefinition": {
                "sections": [
                    {
                        "title": "About you",
                        "fields": [
                            {"fieldId": "bio", "label": "Short bio", "fieldType": "LongText"},
                            {"fieldId": "agree", "label": "Custom field", "fieldType": "ProprietaryWidget"},
                        ],
                    }
                ]
            }
        },
        provider="ashby",
    )

    assert [question.normalized_type for question in questions] == [
        ApplicationQuestionType.TEXTAREA,
        ApplicationQuestionType.UNKNOWN,
    ]
    assert questions[0].source_field_name == "bio"
    assert questions[1].handling is ApplicationQuestionHandling.UNSUPPORTED
    assert questions[1].label == "Custom field"


def test_sensitive_and_legal_questions_are_flagged_without_answering() -> None:
    questions = extract_application_questions(
        {
            "demographic_questions": [
                {
                    "id": "gender",
                    "label": "What is your gender?",
                    "type": "multi_value_single_select",
                    "answer_options": [{"id": 1, "label": "Woman"}, {"id": 2, "label": "Man"}],
                }
            ],
            "compliance": [
                {"id": "work-auth", "label": "Are you authorized to work in the US?", "type": "boolean"}
            ],
        },
        provider="greenhouse",
    )

    assert len(questions) == 2
    by_label = {question.label: question for question in questions}
    assert by_label["What is your gender?"].handling is ApplicationQuestionHandling.SENSITIVE
    assert by_label["What is your gender?"].options == ("Woman", "Man")
    assert by_label["Are you authorized to work in the US?"].handling is ApplicationQuestionHandling.LEGAL
    assert all(question.answer is None for question in questions)
    assert all(question.human_review_required for question in questions)


def test_requirement_extraction_categories_and_evidence() -> None:
    extracted = extract_job_requirements(
        """Requirements
- 3+ years of backend engineering experience.
- Bachelor's degree in Computer Science.

Preferred Qualifications
- Experience with Rust would be a plus.

Responsibilities
- Design and maintain reliable APIs.

Benefits
- We offer health insurance and paid time off.
"""
    )

    assert [item.category for item in extracted] == [
        RequirementCategory.MUST_HAVE,
        RequirementCategory.MUST_HAVE,
        RequirementCategory.PREFERRED,
        RequirementCategory.RESPONSIBILITY,
        RequirementCategory.BENEFIT,
    ]
    assert extracted[0].text == "3+ years of backend engineering experience."
    assert "public job posting, line 2" in extracted[0].evidence
    assert extracted[0].extracted_from == "public job posting"
    assert all(item.confidence >= 0.7 for item in extracted)


def test_generic_mentions_are_not_promoted_to_must_have() -> None:
    extracted = extract_job_requirements(
        "Our product is built with Python and PostgreSQL. We work with customers around the world. "
        "We use a preferred vendor for our application portal. We offer clients a platform for analytics."
    )

    assert len(extracted) == 4
    assert all(item.category is RequirementCategory.UNKNOWN for item in extracted)
    assert all(item.confidence < 0.7 for item in extracted)


def test_only_explicit_cues_promote_standalone_text_and_unknown_is_retained() -> None:
    extracted = extract_job_requirements(
        "Candidates must be authorized to work in the country.\n"
        "Experience with cloud systems would be a plus.\n"
        "The team values curiosity."
    )

    assert [item.category for item in extracted] == [
        RequirementCategory.MUST_HAVE,
        RequirementCategory.PREFERRED,
        RequirementCategory.UNKNOWN,
    ]
    assert extract_job_requirements(None) == []


def test_this_role_requires_heading_applies_to_following_clause_but_not_disclosures():
    extracted = extract_job_requirements(
        "This role requires\n"
        "Experience with distributed systems, concurrency, and scaling in production environments\n"
        "If you require a reasonable accommodation to complete any part of the recruiting process, contact us.\n"
        "All persons hired will be required to verify identity and complete employment eligibility verification.\n"
        "A criminal background check is required to join the company."
    )

    assert [item.category for item in extracted] == [
        RequirementCategory.MUST_HAVE,
        RequirementCategory.UNKNOWN,
        RequirementCategory.UNKNOWN,
        RequirementCategory.UNKNOWN,
    ]
    assert all("This role requires" not in item.text for item in extracted)


def test_preferred_heading_does_not_capture_later_company_or_process_copy():
    extracted = extract_job_requirements(
        "Bonus points if you have\n"
        "Experience with OpenTelemetry or related industry knowledge\n"
        "Fostering a diverse, welcoming and inclusive environment is important to us.\n"
        "Our hiring process\n"
        "All persons hired will be required to verify identity and work eligibility."
    )

    assert [item.category for item in extracted] == [
        RequirementCategory.PREFERRED,
        RequirementCategory.UNKNOWN,
        RequirementCategory.UNKNOWN,
    ]
