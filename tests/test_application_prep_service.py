from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from ai_job_hunter.application_prep.models import (
    ApplicationAnswerStatus,
    ApplicationPackage,
    ApplicationPackageStatus,
    ApplicationQuestion,
    ApplicationQuestionHandling,
    ApplicationQuestionType,
    ApplicationReadinessReason,
    ApplicationReadinessStatus,
    CandidateDocument,
    CandidateDocumentType,
    QuestionSchemaStatus,
)
from ai_job_hunter.application_prep.service import (
    ApplicationJobInput,
    ApplicationPreparationError,
    answer_application_question,
    assess_readiness,
    build_application_package,
    cancel_application_package,
    mark_ready_to_submit,
    recommend_cv_variant,
)
from ai_job_hunter.candidates.profile import CandidateConfig
from ai_job_hunter.outreach.projects import CandidateProject


def _candidate() -> CandidateConfig:
    return CandidateConfig.model_validate(
        {
            "profile": {
                "current_role": "Backend Engineer",
                "years_of_experience": Decimal("4"),
                "primary_skills": ["Java", "Python"],
                "technologies": ["Spring", "PostgreSQL"],
            },
            "preferences": {"willing_to_learn_technologies": ["Kotlin"]},
        }
    )


def _job(**changes) -> ApplicationJobInput:
    values = {
        "job_id": uuid4(),
        "title": "Backend Engineer",
        "company": "Example Co",
        "description": "Requirements: Java and 3+ years of experience. Build backend services.",
        "provider": "greenhouse",
        "canonical_job_url": "https://example.test/jobs/1",
        "application_url": "https://example.test/jobs/1/apply",
        "raw_metadata": {},
        "source_snapshot_at": datetime(2026, 9, 24, tzinfo=UTC),
    }
    values.update(changes)
    return ApplicationJobInput(**values)


def _package(*, questions=(), schema=QuestionSchemaStatus.AVAILABLE, url="https://example.test/apply"):
    return ApplicationPackage(
        job_id=uuid4(),
        fingerprint="a" * 64,
        candidate_profile_fingerprint="b" * 64,
        candidate_preferences_fingerprint="c" * 64,
        application_url=url,
        question_schema_status=schema,
        questions=list(questions),
        suggested_cv_variant="configured-cv",
    )


def _question(
    identifier: str,
    label: str,
    *,
    required: bool = True,
    kind: ApplicationQuestionType = ApplicationQuestionType.TEXT,
    handling: ApplicationQuestionHandling = ApplicationQuestionHandling.NEEDS_USER_INPUT,
) -> ApplicationQuestion:
    return ApplicationQuestion(
        id=identifier,
        label=label,
        required=required,
        normalized_type=kind,
        extracted_from="fixture",
        confidence=1.0,
        handling=handling,
    )


def test_package_build_maps_facts_questions_documents_and_projects():
    documents = (
        CandidateDocument(
            type=CandidateDocumentType.CV,
            name="backend-java CV",
            local_reference="private/backend.pdf",
            technologies=("Java", "Spring"),
            role_families=("backend engineer",),
        ),
    )
    project = CandidateProject(
        name="Catalog API",
        url="https://example.test/catalog",
        short_description="A Java backend API for catalog data.",
        technologies=("Java", "Spring"),
        tags=("backend",),
    )
    package = build_application_package(
        _job(
            raw_metadata={
                "questions": [
                    {
                        "label": "Do you have experience with Java?",
                        "required": True,
                        "fields": [{"name": "java_experience", "type": "input_text"}],
                    }
                ]
            }
        ),
        _candidate(),
        documents=documents,
        projects=(project,),
        question_schema_status=QuestionSchemaStatus.AVAILABLE,
    )

    assert package.status is ApplicationPackageStatus.READY_FOR_REVIEW
    assert package.job_title == "Backend Engineer"
    assert package.company_name == "Example Co"
    assert package.suggested_cv_variant == "backend-java CV"
    assert package.questions[0].answer == "Yes"
    assert package.questions[0].answer_status is ApplicationAnswerStatus.DRAFTED
    assert package.answers[0].human_review_required is True
    assert package.candidate_fit[0].job_requirement
    assert package.source_snapshot_at == datetime(2026, 9, 24, tzinfo=UTC)
    assert package.readiness.status is ApplicationReadinessStatus.READY
    assert package.suggested_cover_letter is None


def test_cover_letter_is_generated_only_when_requested_or_required():
    documents = (
        CandidateDocument(
            type=CandidateDocumentType.CV,
            name="backend CV",
            local_reference="private/backend.pdf",
            role_families=("backend engineer",),
        ),
    )
    optional = build_application_package(
        _job(description="Build backend APIs."),
        _candidate(),
        documents=documents,
        question_schema_status=QuestionSchemaStatus.AVAILABLE,
    )
    required = build_application_package(
        _job(description="Please include a cover letter. Build backend APIs."),
        _candidate(),
        documents=documents,
        question_schema_status=QuestionSchemaStatus.AVAILABLE,
    )
    requested = build_application_package(
        _job(description="Build backend APIs."),
        _candidate(),
        documents=documents,
        question_schema_status=QuestionSchemaStatus.AVAILABLE,
        request_cover_letter=True,
    )

    assert optional.suggested_cover_letter is None
    assert required.suggested_cover_letter is not None
    assert requested.suggested_cover_letter is not None


def test_no_document_recommendation_without_explicit_metadata():
    result = recommend_cv_variant("Backend Engineer", ("Java",), (), ())
    assert result is None


def test_missing_configured_cv_keeps_application_readiness_at_needs_input():
    package = _package().model_copy(update={"suggested_cv_variant": None})

    readiness = assess_readiness(package)

    assert readiness.status is ApplicationReadinessStatus.NEEDS_INPUT
    assert ApplicationReadinessReason.MISSING_DOCUMENT in readiness.reasons


def test_missing_schema_and_url_require_input_and_never_claim_readiness():
    package = _package(schema=QuestionSchemaStatus.UNAVAILABLE, url=None)
    readiness = assess_readiness(package)

    assert readiness.status is ApplicationReadinessStatus.NEEDS_INPUT
    assert ApplicationReadinessReason.OTHER in readiness.reasons


def test_required_unsupported_file_field_blocks_package():
    package = _package(
        questions=(
            _question(
                "resume",
                "Upload your CV",
                kind=ApplicationQuestionType.FILE,
                handling=ApplicationQuestionHandling.UNSUPPORTED,
            ),
        )
    )

    readiness = assess_readiness(package)

    assert readiness.status is ApplicationReadinessStatus.BLOCKED
    assert ApplicationReadinessReason.MISSING_DOCUMENT in readiness.reasons
    assert ApplicationReadinessReason.UNSUPPORTED_FORM_FIELD in readiness.reasons


def test_missing_required_answer_needs_input_and_sensitive_answer_requires_confirmation():
    legal = _question(
        "authorization",
        "Are you legally authorized to work here?",
        kind=ApplicationQuestionType.YES_NO,
        handling=ApplicationQuestionHandling.LEGAL,
    )
    package = _package(questions=(legal,))
    assert assess_readiness(package).status is ApplicationReadinessStatus.NEEDS_INPUT
    assert ApplicationReadinessReason.WORK_AUTHORIZATION_UNKNOWN in assess_readiness(package).reasons

    with pytest.raises(ApplicationPreparationError, match="legal or sensitive"):
        answer_application_question(package, "authorization", "Yes")

    updated = answer_application_question(
        package, "authorization", "Yes", confirm_sensitive=True
    )
    assert updated.questions[0].answer == "Yes"
    assert updated.questions[0].answer_status is ApplicationAnswerStatus.USER_PROVIDED
    assert updated.questions[0].human_review_required is True
    assert updated.answers[0].evidence == ("Entered explicitly by the user.",)


def test_user_answer_validation_and_local_lifecycle():
    question = _question(
        "country", "Preferred country", kind=ApplicationQuestionType.SELECT
    ).model_copy(update={"options": ("Spain", "Portugal")})
    package = _package(questions=(question,))

    with pytest.raises(ApplicationPreparationError, match="listed options"):
        answer_application_question(package, "country", "France")
    answered = answer_application_question(package, "country", "Spain")
    assert answered.status is ApplicationPackageStatus.READY_FOR_REVIEW
    assert answered.readiness.status is ApplicationReadinessStatus.READY
    ready = mark_ready_to_submit(answered)
    assert ready.status is ApplicationPackageStatus.READY_TO_SUBMIT
    assert ready.readiness.status is ApplicationReadinessStatus.READY
    cancelled = cancel_application_package(ready)
    assert cancelled.status is ApplicationPackageStatus.CANCELLED
    with pytest.raises(ApplicationPreparationError):
        mark_ready_to_submit(cancelled)


def test_unavailable_required_answer_cannot_be_marked_ready():
    package = _package(questions=(_question("why", "Why this company?"),))
    with pytest.raises(ApplicationPreparationError, match="still needs input"):
        mark_ready_to_submit(package)


def test_submitted_status_is_not_constructible():
    with pytest.raises(ValidationError, match="SUBMITTED is reserved"):
        ApplicationPackage(
            job_id=uuid4(),
            fingerprint="a" * 64,
            candidate_profile_fingerprint="b" * 64,
            candidate_preferences_fingerprint="c" * 64,
            status=ApplicationPackageStatus.SUBMITTED,
        )
