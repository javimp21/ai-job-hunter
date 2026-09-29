from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest

from ai_job_hunter.application_prep.browser.extraction import (
    extract_snapshot_from_html,
    snapshot_from_dom_records,
)
from ai_job_hunter.application_prep.browser.mapping import map_form_fields, safe_fill_plan
from ai_job_hunter.application_prep.browser.models import (
    AnswerPolicy,
    ApplicationFormSnapshot,
    ApplicationSession,
    ApplicationSessionStatus,
    ATSProvider,
    CanonicalField,
    FieldMapping,
    ManualInterventionReason,
    MappingConfidence,
)
from ai_job_hunter.application_prep.browser.playwright_driver import MappingAndFillPlan, PlaywrightAssistedBrowser
from ai_job_hunter.application_prep.browser.safety import (
    BrowserSafetyError,
    NavigationTrust,
    NetworkDecision,
    SubmissionBlockedError,
    assert_safe_next_action,
    canonicalize_application_url,
    classify_navigation_url,
    detect_ats,
    is_safe_application_popup,
    make_form_action,
    network_decision,
    validate_application_url,
)
from ai_job_hunter.application_prep.browser.store import ApplicationSessionStore
from ai_job_hunter.application_prep.configuration import (
    CandidateApplicationFacts,
    load_candidate_application_facts,
    load_candidate_documents,
)
from ai_job_hunter.application_prep.models import (
    ApplicationPackage,
    CandidateDocument,
    CandidateDocumentType,
)
from ai_job_hunter.candidates.profile import CandidateConfig, CandidatePreferences, CandidateProfile
from ai_job_hunter.domain.normalized_job import SalaryPeriod
from ai_job_hunter.outreach.projects import CandidateProject


FIXTURES = Path(__file__).parent / "fixtures"
OLX_URL = "https://jobs.eu.lever.co/olx/fixture-id/apply"


def _candidate() -> CandidateConfig:
    return CandidateConfig(
        profile=CandidateProfile(
            years_of_experience=Decimal("5"),
            current_role="Backend Engineer",
            primary_skills=["Python", "Java"],
            technologies=["FastAPI", "PostgreSQL"],
            current_city="Madrid",
            current_country="Spain",
        ),
        preferences=CandidatePreferences(
            target_salary=Decimal("60000"),
            salary_currency="EUR",
            salary_period=SalaryPeriod.YEAR,
        ),
    )


def _facts() -> CandidateApplicationFacts:
    return CandidateApplicationFacts(
        first_name="Test",
        last_name="Candidate",
        email="candidate@example.test",
        phone="+34000000000",
        linkedin_url="https://www.linkedin.com/in/test-candidate",
    )


def _package() -> ApplicationPackage:
    return ApplicationPackage(
        job_id=uuid4(),
        fingerprint="a" * 64,
        candidate_profile_fingerprint="b" * 64,
        candidate_preferences_fingerprint="c" * 64,
        job_title="Backend Engineer",
        company_name="Example",
        source_ats="Lever",
        application_url=OLX_URL,
        requirements_summary="Python backend systems",
        suggested_cv_variant="configured-backend-cv",
    )


def _snapshot(fixture: str = "browser_application_step.html"):
    return extract_snapshot_from_html((FIXTURES / fixture).read_text(encoding="utf-8"), url=OLX_URL)


def _mapping(snapshot=None):
    snapshot = snapshot or _snapshot()
    project = CandidateProject(
        name="Backend service",
        url="https://example.test/project",
        short_description="A small Python API with PostgreSQL persistence.",
        technologies=("Python", "PostgreSQL"),
        tags=("backend",),
    )
    return map_form_fields(
        snapshot,
        candidate=_candidate(),
        facts=_facts(),
        package=_package(),
        projects=(project,),
    )


def test_html_dom_extraction_covers_control_types_and_redacts_current_values():
    snapshot = _snapshot()

    by_label = {field.label: field for field in snapshot.fields}
    assert by_label["First name"].required is True
    assert by_label["Email address"].field_type.value == "EMAIL"
    assert by_label["Country"].options == ("Choose one", "Spain", "Portugal")
    assert by_label["I agree to the terms"].field_type.value == "CHECKBOX"
    assert by_label["Work authorization"].field_type.value == "RADIO"
    assert by_label["Work authorization"].options == ("Yes", "No")
    assert by_label["Why are you interested in this role?"].field_type.value == "TEXTAREA"
    assert by_label["Resume / CV"].field_type.value == "FILE"
    assert by_label["First name"].current_value_present is True
    assert by_label["Why are you interested in this role?"].current_value_present is True
    assert snapshot.step == 1
    assert snapshot.step_count == 2
    serialized = snapshot.model_dump_json()
    assert "PERSONAL_VALUE_SENTINEL" not in serialized
    assert "DRAFT_VALUE_SENTINEL" not in serialized
    assert "value" not in by_label["First name"].model_dump()


@pytest.mark.parametrize(
    ("fixture", "reason"),
    [
        ("browser_application_login.html", ManualInterventionReason.AUTHENTICATION),
        ("browser_application_captcha.html", ManualInterventionReason.CAPTCHA),
        ("browser_application_captcha_text.html", ManualInterventionReason.CAPTCHA),
    ],
)
def test_login_and_captcha_stop_for_manual_intervention(fixture, reason):
    snapshot = _snapshot(fixture)
    assert snapshot.manual_intervention_required is True
    assert snapshot.manual_intervention_reason is reason


def test_submit_controls_are_detected_and_never_allowed_as_actions():
    snapshot = _snapshot("browser_application_submission.html")
    submissions = [action for action in snapshot.actions if action.submission_intent]
    assert {action.label for action in submissions} == {
        "Submit application", "Send application", "Finish application"
    }
    assert all(action.control_type == "submit" for action in submissions)
    for action in submissions:
        with pytest.raises(SubmissionBlockedError):
            assert_safe_next_action(action)


@pytest.mark.parametrize("label", ["Submit", "Submit application", "Send", "Send application", "Apply", "Apply now", "Complete", "Complete application", "Finish", "Finish application"])
def test_common_final_action_labels_are_blocked(label):
    action = make_form_action(label, "button")
    assert action is not None and action.submission_intent
    with pytest.raises(SubmissionBlockedError):
        assert_safe_next_action(action)


def test_only_explicit_safe_next_action_can_advance():
    action = make_form_action("Next", "button")
    assert action is not None and action.continue_intent and not action.submission_intent
    assert_safe_next_action(action)
    with pytest.raises(BrowserSafetyError, match="required fields"):
        assert_safe_next_action(action, required_fields_unresolved=("required-email",))
    final_submit = make_form_action("Submit", "submit")
    with pytest.raises(SubmissionBlockedError):
        assert_safe_next_action(action, visible_actions=(action, final_submit))
    implicit_submit = make_form_action("Continue", "submit")
    with pytest.raises(SubmissionBlockedError):
        assert_safe_next_action(implicit_submit)


def test_safe_autofill_uses_only_exact_explicit_facts_and_never_overwrites():
    snapshot = _snapshot()
    mappings = _mapping(snapshot)
    by_label = {field.label: field for field in snapshot.fields}
    by_id = {item.field_id: item for item in mappings}

    assert by_id[by_label["Email address"].id].answer_policy is AnswerPolicy.SAFE_AUTO_FILL
    assert by_id[by_label["Country"].id].answer_policy is AnswerPolicy.SAFE_AUTO_FILL
    assert by_id[by_label["City"].id].answer_policy is AnswerPolicy.SAFE_AUTO_FILL
    assert by_id[by_label["Current role"].id].answer_policy is AnswerPolicy.SAFE_AUTO_FILL
    assert by_id[by_label["Total years of experience"].id].answer_policy is AnswerPolicy.SAFE_AUTO_FILL
    assert by_id[by_label["Job title"].id].answer_policy is AnswerPolicy.NEEDS_USER_INPUT
    assert by_id[by_label["Years of Python experience"].id].answer_policy is AnswerPolicy.TEXT_DRAFT_REVIEW

    plan = safe_fill_plan(snapshot, mappings, candidate=_candidate(), facts=_facts())
    assert plan[by_label["Email address"].id] == "candidate@example.test"
    assert plan[by_label["Country"].id] == "Spain"
    assert plan[by_label["City"].id] == "Madrid"
    assert by_label["First name"].id not in plan  # The fixture already has a value.
    assert "PERSONAL_VALUE_SENTINEL" not in repr(plan)


def test_salary_sensitive_legal_and_document_fields_are_review_only():
    snapshot = _snapshot()
    mappings = {item.source_label: item for item in _mapping(snapshot)}
    assert mappings["Expected salary"].answer_policy is AnswerPolicy.SALARY_SUGGESTION_REVIEW
    assert mappings["Expected salary"].suggested_answer == (
        "SALARY_INPUT_REQUIRED: target annual EUR 60000; monthly equivalent EUR 5000 (annual / 12). "
        "Payment schedule (12 vs 14 payments) is unknown; enter manually."
    )
    assert mappings["Work authorization"].answer_policy is AnswerPolicy.LEGAL
    assert mappings["I agree to the terms"].answer_policy is AnswerPolicy.LEGAL
    assert mappings["Voluntary self-identification"].answer_policy is AnswerPolicy.OPTIONAL_SELF_IDENTIFICATION
    assert mappings["Resume / CV"].answer_policy is AnswerPolicy.DOCUMENT_RECOMMENDATION_ONLY
    assert mappings["Resume / CV"].recommendation.startswith("NO_CV_CONFIGURED")
    assert mappings["Tell us about a project"].answer_policy is AnswerPolicy.TEXT_DRAFT_REVIEW
    assert "Backend service" in mappings["Tell us about a project"].suggested_answer
    assert "does not specify a separate duration for Python" in mappings["Years of Python experience"].suggested_answer
    assert mappings["Why are you interested in this role?"].suggested_answer is None
    assert not safe_fill_plan(snapshot, tuple(mappings.values()), candidate=_candidate(), facts=_facts()).get("salary")


def test_document_fields_recommend_matching_metadata_without_opening_or_uploading_files():
    snapshot = snapshot_from_dom_records(
        url=OLX_URL,
        records=[
            {"tag": "input", "type": "file", "id": "resume", "label": "Resume / CV", "label_source": "label", "required": True, "visible": True},
            {"tag": "input", "type": "file", "id": "cover", "label": "Cover letter", "label_source": "label", "visible": True},
        ],
    )
    documents = (
        CandidateDocument(
            id="backend-cv",
            type=CandidateDocumentType.CV,
            local_path="private/configured-cv.pdf",
            role_families=("backend engineer",),
        ),
        CandidateDocument(
            id="cover-letter-en",
            type=CandidateDocumentType.COVER_LETTER,
            local_path="private/configured-cover-letter.pdf",
            language="en",
        ),
    )
    mappings = map_form_fields(
        snapshot,
        candidate=_candidate(),
        facts=_facts(),
        package=_package().model_copy(update={"suggested_cv_variant": None}),
        documents=documents,
    )

    recommendations = {item.source_label: item.recommendation for item in mappings}
    assert recommendations["Resume / CV"] == "backend-cv"
    assert recommendations["Cover letter"] == "cover-letter-en"
    assert all(item.answer_policy is AnswerPolicy.DOCUMENT_RECOMMENDATION_ONLY for item in mappings)


def test_candidate_contact_facts_optional_config_and_document_schema(tmp_path):
    facts_path = tmp_path / "candidate_application.local.json"
    facts_path.write_text('{"first_name":"", "email":null}', encoding="utf-8")
    facts = load_candidate_application_facts(facts_path)
    assert facts.first_name is None
    assert facts.email is None

    docs_path = tmp_path / "candidate_documents.local.json"
    docs_path.write_text(
        '{"documents":[{"id":"cv-backend","type":"CV","local_path":"private/backend.pdf",'
        '"language":"en","tags":["backend"],"role_families":["backend"],"technologies":["Python"]}]}',
        encoding="utf-8",
    )
    document = load_candidate_documents(docs_path).documents[0]
    assert document.id == "cv-backend"
    assert document.local_path == "private/backend.pdf"

    legacy = load_candidate_documents(FIXTURES / "candidate_documents_legacy.json")
    assert legacy.documents[0].local_path == "private/backend.pdf"
    assert legacy.documents[0].id == "backend-resume"


def test_full_name_and_location_are_composed_only_from_explicit_facts():
    snapshot = snapshot_from_dom_records(
        url=OLX_URL,
        records=[
            {"tag": "input", "type": "text", "id": "full", "label": "Full name", "label_source": "label"},
            {"tag": "input", "type": "text", "id": "location", "label": "Current location", "label_source": "label"},
        ],
    )
    mappings = map_form_fields(snapshot, candidate=_candidate(), facts=_facts(), package=_package())
    plan = safe_fill_plan(snapshot, mappings, candidate=_candidate(), facts=_facts())
    assert plan == {"full": "Test Candidate", "location": "Madrid, Spain"}

    incomplete = CandidateApplicationFacts(first_name="Test")
    incomplete_mappings = map_form_fields(snapshot, candidate=_candidate(), facts=incomplete, package=_package())
    assert next(item for item in incomplete_mappings if item.field_id == "full").answer_policy is AnswerPolicy.NEEDS_USER_INPUT
    assert safe_fill_plan(snapshot, incomplete_mappings, candidate=_candidate(), facts=incomplete) == {"location": "Madrid, Spain"}


def test_spain_region_and_presence_are_safe_only_for_explicit_geographic_questions():
    snapshot = snapshot_from_dom_records(
        url=OLX_URL,
        records=[
            {"tag": "select", "type": "select", "id": "region", "label": "Region", "label_source": "label", "options": ["Europe", "Asia"]},
            {"tag": "input", "type": "radio", "id": "based-yes", "name": "based", "label": "Are you currently based in Spain?", "group_label": "Are you currently based in Spain?", "option_label": "Yes", "label_source": "label"},
            {"tag": "input", "type": "radio", "id": "based-no", "name": "based", "label": "Are you currently based in Spain?", "group_label": "Are you currently based in Spain?", "option_label": "No", "label_source": "label"},
        ],
    )
    mappings = map_form_fields(snapshot, candidate=_candidate(), facts=_facts(), package=_package())
    by_id = {item.field_id: item for item in mappings}
    assert by_id["region"].answer_policy is AnswerPolicy.SAFE_AUTO_FILL
    assert by_id["radio:based:1"].answer_policy is AnswerPolicy.SAFE_AUTO_FILL
    plan = safe_fill_plan(snapshot, mappings, candidate=_candidate(), facts=_facts())
    assert plan == {"region": "Europe", "radio:based:1": "Yes"}

    auth = snapshot_from_dom_records(
        url=OLX_URL,
        records=[{"tag": "input", "type": "radio", "id": "auth", "label": "Are you currently authorized to work in Spain?", "required": True}],
    )
    auth_mapping = map_form_fields(auth, candidate=_candidate(), facts=_facts(), package=_package())[0]
    assert auth_mapping.answer_policy is AnswerPolicy.LEGAL

    relocation_question = "Please be informed that this position can be hired in Spain only and OLX does not offer relocation."
    relocation = snapshot_from_dom_records(
        url=OLX_URL,
        records=[
            {"tag": "input", "type": "radio", "id": "there", "name": "availability", "label": relocation_question, "group_label": relocation_question, "option_label": "I am in Spain already."},
            {"tag": "input", "type": "radio", "id": "will-move", "name": "availability", "label": relocation_question, "group_label": relocation_question, "option_label": "I plan to relocate to Spain on my own."},
            {"tag": "input", "type": "radio", "id": "no-move", "name": "availability", "label": relocation_question, "group_label": relocation_question, "option_label": "I am not in Spain and I do not plan to relocate there."},
        ],
    )
    relocation_mappings = map_form_fields(relocation, candidate=_candidate(), facts=CandidateApplicationFacts(), package=_package())
    relocation_plan = safe_fill_plan(relocation, relocation_mappings, candidate=_candidate(), facts=CandidateApplicationFacts())
    assert len(relocation.fields) == 1
    assert relocation_plan == {relocation.fields[0].id: "I am in Spain already."}
    assert "no relocation willingness is inferred" in relocation_mappings[0].evidence[-1]


def test_only_explicit_previous_employment_relocation_and_notice_answers_can_fill():
    snapshot = snapshot_from_dom_records(
        url=OLX_URL,
        records=[
            {"tag": "input", "type": "radio", "id": "worked-yes", "name": "worked", "label": "Have you previously worked at OLX?", "group_label": "Have you previously worked at OLX?", "option_label": "Yes"},
            {"tag": "input", "type": "radio", "id": "worked-no", "name": "worked", "label": "Have you previously worked at OLX?", "group_label": "Have you previously worked at OLX?", "option_label": "No"},
            {"tag": "input", "type": "radio", "id": "relocation-yes", "name": "relocation", "label": "Are you willing to relocate?", "group_label": "Are you willing to relocate?", "option_label": "Yes"},
            {"tag": "input", "type": "radio", "id": "relocation-no", "name": "relocation", "label": "Are you willing to relocate?", "group_label": "Are you willing to relocate?", "option_label": "No"},
            {"tag": "input", "type": "text", "id": "notice", "label": "What is your notice period?", "label_source": "label"},
            {"tag": "input", "type": "radio", "id": "consent-yes", "name": "consent", "label": "I consent to data processing", "group_label": "I consent to data processing", "option_label": "Yes"},
            {"tag": "input", "type": "radio", "id": "consent-no", "name": "consent", "label": "I consent to data processing", "group_label": "I consent to data processing", "option_label": "No"},
        ],
    )
    facts = CandidateApplicationFacts(previous_employment="Yes", relocation_response="No", notice_period="One month")
    mappings = map_form_fields(snapshot, candidate=_candidate(), facts=facts, package=_package())
    plan = safe_fill_plan(snapshot, mappings, candidate=_candidate(), facts=facts)
    assert plan == {
        "radio:worked:1": "Yes",
        "radio:relocation:2": "No",
        "notice": "One month",
    }
    consent_mapping = next(item for item in mappings if item.source_label == "I consent to data processing")
    assert consent_mapping.answer_policy is AnswerPolicy.LEGAL
    assert consent_mapping.field_id not in plan


def test_legal_responses_are_review_only_and_java_is_suggested_only_for_review():
    snapshot = snapshot_from_dom_records(
        url=OLX_URL,
        records=[
            {"tag": "input", "type": "text", "id": "auth", "label": "Describe your work authorization", "label_source": "label"},
            {"tag": "input", "type": "text", "id": "sponsor", "label": "Will you need visa sponsorship?", "label_source": "label"},
            {"tag": "input", "type": "text", "id": "language", "label": "What is your go-to programming language?", "label_source": "label"},
        ],
    )
    facts = CandidateApplicationFacts(work_authorization_response="User-confirmed response", sponsorship_response="User-confirmed sponsorship response")
    mappings = map_form_fields(snapshot, candidate=_candidate(), facts=facts, package=_package())
    by_id = {item.field_id: item for item in mappings}
    assert by_id["auth"].answer_policy is AnswerPolicy.LEGAL
    assert by_id["auth"].suggested_answer == "User-confirmed response"
    assert by_id["sponsor"].suggested_answer == "User-confirmed sponsorship response"
    assert by_id["language"].suggested_answer == "Java"
    assert by_id["language"].answer_policy is AnswerPolicy.TEXT_DRAFT_REVIEW
    assert safe_fill_plan(snapshot, mappings, candidate=_candidate(), facts=facts) == {}


def test_structured_choice_groups_keep_prompt_and_option_labels_separate():
    snapshot = snapshot_from_dom_records(
        url=OLX_URL,
        records=[
            {"tag": "input", "type": "radio", "id": "heard-a", "name": "heard", "label": "How did you hear about us?", "group_label": "How did you hear about us?", "option_label": "LinkedIn", "label_source": "label", "required": True},
            {"tag": "input", "type": "radio", "id": "heard-b", "name": "heard", "label": "How did you hear about us?", "group_label": "How did you hear about us?", "option_label": "Referral", "label_source": "label"},
            {"tag": "input", "type": "checkbox", "id": "updates-a", "name": "updates", "label": "Which updates do you want?", "group_label": "Which updates do you want?", "option_label": "Email", "label_source": "label"},
            {"tag": "input", "type": "checkbox", "id": "updates-b", "name": "updates", "label": "Which updates do you want?", "group_label": "Which updates do you want?", "option_label": "SMS", "label_source": "label"},
        ],
    )
    assert len(snapshot.fields) == 2
    assert snapshot.fields[0].label == "How did you hear about us?"
    assert snapshot.fields[0].options == ("LinkedIn", "Referral")
    assert snapshot.fields[0].field_type.value == "RADIO"
    assert snapshot.fields[0].option_ordinals == (0, 1)
    assert snapshot.fields[1].options == ("Email", "SMS")
    assert snapshot.fields[1].field_type.value == "CHECKBOX"


def test_browser_session_persistence_is_private_and_contains_no_dom_values(tmp_path):
    snapshot = _snapshot()
    session = ApplicationSession(
        job_id=uuid4(),
        application_package_id=uuid4(),
        url=OLX_URL,
        ats=ATSProvider.LEVER,
        current_step=1,
        snapshot=snapshot,
        snapshots=(snapshot,),
        status=ApplicationSessionStatus.NEEDS_INPUT,
        required_field_ids=("email",),
        legal_field_ids=("consent",),
        required_document_field_ids=("cv",),
        readiness_reasons=("manual review required",),
        dry_run=True,
        would_fill_field_ids=("city",),
        needs_input_field_ids=("email",),
    )
    path = tmp_path / "application-sessions.local.json"
    store = ApplicationSessionStore(path)
    store.save(session)
    assert store.get_by_job(session.job_id) == session
    raw = path.read_text(encoding="utf-8")
    assert "PERSONAL_VALUE_SENTINEL" not in raw
    assert "DRAFT_VALUE_SENTINEL" not in raw
    assert "cookies" not in raw.casefold()
    assert "SUBMITTED" not in {item.value for item in ApplicationSessionStatus}


def test_versioned_application_config_examples_match_supported_schema():
    from ai_job_hunter.application_prep.configuration import CandidateDocumentsConfig
    import json

    root = Path(__file__).resolve().parents[1]
    facts_payload = json.loads((root / "config/examples/candidate_application.example.json").read_text(encoding="utf-8"))
    documents_payload = json.loads((root / "config/examples/candidate_documents.example.json").read_text(encoding="utf-8"))
    facts = CandidateApplicationFacts.model_validate(facts_payload)
    documents = CandidateDocumentsConfig.model_validate(documents_payload)
    assert facts.first_name is None
    assert facts.previous_employment is None
    assert len(documents.documents) == 1


def test_network_and_submit_guards_block_writes_enter_and_post_fill_traffic():
    assert network_decision(
        url=OLX_URL, method="GET", resource_type="document", is_navigation=True,
        initial_url=OLX_URL, interacted_with_page=False,
    ) is NetworkDecision.ALLOW
    assert network_decision(
        url=OLX_URL, method="POST", resource_type="fetch", is_navigation=False,
        initial_url=OLX_URL, interacted_with_page=False,
    ) is NetworkDecision.BLOCK
    assert network_decision(
        url=OLX_URL, method="GET", resource_type="image", is_navigation=False,
        initial_url=OLX_URL, interacted_with_page=True,
    ) is NetworkDecision.BLOCK
    assert network_decision(
        url="https://example.test/collect", method="GET", resource_type="image", is_navigation=False,
        initial_url=OLX_URL, interacted_with_page=False,
    ) is NetworkDecision.BLOCK
    assert network_decision(
        url="https://evil.lever.co/olx/script.js", method="GET", resource_type="script", is_navigation=False,
        initial_url=OLX_URL, interacted_with_page=False,
    ) is NetworkDecision.BLOCK
    assert network_decision(
        url=OLX_URL + "?utm_source=listing#step-2", method="GET", resource_type="document", is_navigation=True,
        initial_url=OLX_URL + "#apply", interacted_with_page=False,
    ) is NetworkDecision.ALLOW
    assert network_decision(
        url=OLX_URL + "/", method="HEAD", resource_type="document", is_navigation=True,
        initial_url=OLX_URL, interacted_with_page=False,
    ) is NetworkDecision.ALLOW
    assert network_decision(
        url="https://jobs.lever.co/olx/fixture-id/apply?from=eu",
        method="GET", resource_type="document", is_navigation=True,
        initial_url=OLX_URL, interacted_with_page=False,
    ) is NetworkDecision.ALLOW
    assert network_decision(
        url="https://jobs.lever.co/olx/another-job/apply",
        method="GET", resource_type="document", is_navigation=True,
        initial_url=OLX_URL, interacted_with_page=False,
    ) is NetworkDecision.BLOCK
    assert network_decision(
        url="about:blank", method="GET", resource_type="document", is_navigation=True,
        initial_url=OLX_URL, interacted_with_page=False,
    ) is NetworkDecision.BLOCK
    assert network_decision(
        url="https://jobs.eu.lever.co/olx/41139c11-553a-4dde-9a12-316334a1d2b3/submit",
        method="GET", resource_type="fetch", is_navigation=False,
        initial_url=OLX_URL, interacted_with_page=False,
    ) is NetworkDecision.BLOCK
    assert network_decision(
        url=OLX_URL + "?action=submit", method="GET", resource_type="fetch", is_navigation=False,
        initial_url=OLX_URL, interacted_with_page=False,
    ) is NetworkDecision.BLOCK
    assert "event.key === 'Enter'" in __import__(
        "ai_job_hunter.application_prep.browser.safety", fromlist=["SUBMIT_GUARD_INIT_SCRIPT"]
    ).SUBMIT_GUARD_INIT_SCRIPT
    assert "requestSubmit" in __import__(
        "ai_job_hunter.application_prep.browser.safety", fromlist=["SUBMIT_GUARD_INIT_SCRIPT"]
    ).SUBMIT_GUARD_INIT_SCRIPT
    assert not callable(getattr(PlaywrightAssistedBrowser, "submit", None))
    assert not callable(getattr(PlaywrightAssistedBrowser, "upload", None))
    assert not callable(getattr(PlaywrightAssistedBrowser, "click", None))
    assert not callable(getattr(PlaywrightAssistedBrowser, "keyboard", None))


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_network_policy_blocks_all_write_methods(method):
    assert network_decision(
        url=OLX_URL, method=method, resource_type="document", is_navigation=True,
        initial_url=OLX_URL, interacted_with_page=False,
    ) is NetworkDecision.BLOCK


def test_browser_runner_does_not_advance_when_native_submit_control_is_visible():
    raw = {
        "fields": [{
            "tag": "input", "type": "text", "id": "optional", "label": "Optional field",
            "label_source": "label", "required": False, "visible": True, "ordinal": 0,
        }],
        "actions": [
            {"label": "Next", "control_type": "button", "ordinal": 0, "click_ordinal": 0, "visible": True},
            {"label": "Submit application", "control_type": "submit", "ordinal": 1, "visible": True},
        ],
        "step_text": "",
        "captcha_detected": False,
        "captcha_text_detected": False,
        "login_detected": False,
    }

    class Page:
        url = "about:blank"
        locator_called = False

        def goto(self, target_url, **kwargs):
            self.url = target_url

        def wait_for_load_state(self, *args, **kwargs):
            pass

        def evaluate(self, script):
            assert self.url != "about:blank"
            return raw

        def locator(self, selector):
            self.locator_called = True
            raise AssertionError("runner must refuse Next before looking up a clickable locator")

        def wait_for_timeout(self, milliseconds):
            pass

    page = Page()

    class Context:
        def add_init_script(self, script):
            pass

        def route(self, *args):
            pass

        def route_web_socket(self, *args):
            pass

        def new_page(self):
            return page

        @property
        def pages(self):
            return [page]

        def close(self):
            pass

    class Browser:
        def new_context(self, **kwargs):
            return Context()

        def close(self):
            pass

    class Chromium:
        def launch(self, **kwargs):
            return Browser()

    class Playwright:
        chromium = Chromium()

    class SyncPlaywright:
        def __enter__(self):
            return Playwright()

        def __exit__(self, *args):
            pass

    result = PlaywrightAssistedBrowser()._run(
        SyncPlaywright,
        url=OLX_URL,
        provider=ATSProvider.LEVER,
        plan_for_snapshot=lambda snapshot, page_url: MappingAndFillPlan(mappings=(), values_by_field_id={}),
        fill_safe=False,
        max_steps=2,
    )

    assert len(result.snapshots) == 1
    assert result.advanced_steps == 0
    assert page.locator_called is False


def test_browser_dry_run_never_fills_or_clicks_and_reports_value_free_plan():
    raw = {
        "fields": [{"tag": "input", "type": "email", "id": "email", "name": "email", "label": "Email address", "label_source": "label", "required": True, "visible": True, "ordinal": 0}],
        "actions": [{"label": "Next", "control_type": "button", "ordinal": 0, "click_ordinal": 0, "visible": True}],
        "step_text": "Step 1 of 2", "captcha_detected": False, "captcha_text_detected": False, "login_detected": False,
    }

    class Page:
        url = "about:blank"
        def goto(self, target_url, **kwargs): self.url = target_url
        def wait_for_load_state(self, *args, **kwargs): pass
        def evaluate(self, script): return raw
        def locator(self, selector): raise AssertionError("dry-run must never query a fill or click locator")

    page = Page()
    class Context:
        def add_init_script(self, script): pass
        def route(self, *args): pass
        def route_web_socket(self, *args): pass
        def new_page(self): return page
        @property
        def pages(self): return [page]
        def close(self): pass
    class Browser:
        def new_context(self, **kwargs): return Context()
        def close(self): pass
    class Chromium:
        def launch(self, **kwargs):
            assert kwargs.get("headless") is True
            return Browser()
    class Playwright:
        chromium = Chromium()
    class SyncPlaywright:
        def __enter__(self): return Playwright()
        def __exit__(self, *args): pass

    def planner(snapshot, page_url):
        mapping = FieldMapping(
            field_id=snapshot.fields[0].id,
            canonical_field=CanonicalField.EMAIL,
            confidence=MappingConfidence.HIGH,
            source_label="Email address",
            answer_policy=AnswerPolicy.SAFE_AUTO_FILL,
            source_key="facts.email",
        )
        return MappingAndFillPlan((mapping,), {snapshot.fields[0].id: "private@example.test"})

    result = PlaywrightAssistedBrowser()._run(
        SyncPlaywright, url=OLX_URL, provider=ATSProvider.LEVER,
        plan_for_snapshot=planner, fill_safe=True, dry_run=True,
    )
    assert result.filled_safe_field_ids == ()
    assert result.advanced_steps == 0
    assert result.would_fill_field_ids == ("step-1:email",)
    assert result.would_skip_field_ids == ()
    assert result.needs_input_field_ids == ()


def test_browser_runner_waits_for_delayed_dom_navigation_without_fixed_sleep():
    states = [
        {
            "fields": [{"tag": "input", "type": "text", "id": "one", "label": "Optional one", "required": False, "visible": True, "ordinal": 0}],
            "actions": [{"label": "Next", "control_type": "button", "ordinal": 0, "click_ordinal": 0, "visible": True}],
            "step_text": "Step 1 of 2", "captcha_detected": False, "captcha_text_detected": False, "login_detected": False,
        },
        {
            "fields": [{"tag": "input", "type": "text", "id": "two", "label": "Optional two", "required": False, "visible": True, "ordinal": 0}],
            "actions": [],
            "step_text": "Step 2 of 2", "captcha_detected": False, "captcha_text_detected": False, "login_detected": False,
        },
    ]

    class Button:
        def is_visible(self):
            return True

        def inner_text(self):
            return "Next"

        def evaluate(self, script):
            return {"tag": "button", "type": "button", "role": ""}

        def click(self, **kwargs):
            pass

    class ButtonCollection:
        def nth(self, ordinal):
            assert ordinal == 0
            return Button()

    class Page:
        url = "about:blank"
        step = 0
        transition_waits = 0

        def goto(self, target_url, **kwargs):
            self.url = target_url

        def wait_for_load_state(self, *args, **kwargs):
            pass

        def evaluate(self, script):
            if "MutationObserver" in script:
                return None
            assert self.url != "about:blank"
            return states[self.step]

        def locator(self, selector):
            return ButtonCollection()

        def wait_for_function(self, expression, **kwargs):
            self.transition_waits += 1
            if "location.href" in expression:
                # Simulate the form's asynchronous second step after Next.
                self.step = 1

    page = Page()

    class Context:
        def add_init_script(self, script):
            pass

        def route(self, *args):
            pass

        def route_web_socket(self, *args):
            pass

        def new_page(self):
            return page

        @property
        def pages(self):
            return [page]

        def close(self):
            pass

    class Browser:
        def new_context(self, **kwargs):
            return Context()

        def close(self):
            pass

    class Playwright:
        chromium = type("Chromium", (), {"launch": lambda self, **kwargs: Browser()})()

    class SyncPlaywright:
        def __enter__(self):
            return Playwright()

        def __exit__(self, *args):
            pass

    result = PlaywrightAssistedBrowser()._run(
        SyncPlaywright, url=OLX_URL, provider=ATSProvider.LEVER,
        plan_for_snapshot=lambda snapshot, page_url: MappingAndFillPlan(mappings=(), values_by_field_id={}),
        fill_safe=False, max_steps=2,
    )

    assert len(result.snapshots) == 2
    assert result.advanced_steps == 1
    assert page.transition_waits >= 2


@pytest.mark.parametrize(
    ("popup_url", "expected_url", "expected_reason"),
    [
        (
            "https://jobs.lever.co/olx/fixture-id/apply?ref=popup",
            "https://jobs.lever.co/olx/fixture-id/apply",
            None,
        ),
        ("https://example.test/olx/apply", OLX_URL, ManualInterventionReason.UNEXPECTED_PAGE),
    ],
)
def test_browser_runner_adopts_only_allowlisted_application_popup(popup_url, expected_url, expected_reason):
    raw = {
        "fields": [{"tag": "input", "type": "text", "id": "name", "label": "Name", "required": False, "visible": True, "ordinal": 0}],
        "actions": [], "step_text": "", "captcha_detected": False,
        "captcha_text_detected": False, "login_detected": False,
    }

    class Page:
        def __init__(self, page_url, *, active):
            self.url = page_url
            self.active = active

        def goto(self, target_url, **kwargs):
            self.url = target_url

        def wait_for_load_state(self, *args, **kwargs):
            pass

        def wait_for_url(self, predicate, **kwargs):
            pass

        def evaluate(self, script):
            assert self.active, "only the origin-checked popup may be inspected"
            return raw

    main_page = Page("about:blank", active=False)
    popup = Page(popup_url, active=True)

    class Context:
        def add_init_script(self, script):
            pass

        def route(self, *args):
            pass

        def route_web_socket(self, *args):
            pass

        def new_page(self):
            return main_page

        @property
        def pages(self):
            return [main_page, popup]

        def close(self):
            pass

    class Browser:
        def new_context(self, **kwargs):
            return Context()

        def close(self):
            pass

    class Playwright:
        chromium = type("Chromium", (), {"launch": lambda self, **kwargs: Browser()})()

    class SyncPlaywright:
        def __enter__(self):
            return Playwright()

        def __exit__(self, *args):
            pass

    result = PlaywrightAssistedBrowser()._run(
        SyncPlaywright, url=OLX_URL, provider=ATSProvider.LEVER,
        plan_for_snapshot=lambda snapshot, page_url: MappingAndFillPlan(mappings=(), values_by_field_id={}),
        fill_safe=False, max_steps=1,
    )

    assert result.manual_intervention_reason is expected_reason
    assert result.final_snapshot.url == expected_url


def test_supported_ats_urls_are_https_and_host_allowlisted():
    assert detect_ats(OLX_URL) is ATSProvider.LEVER
    assert validate_application_url(OLX_URL, ATSProvider.LEVER) is ATSProvider.LEVER
    with pytest.raises(BrowserSafetyError):
        validate_application_url("http://jobs.eu.lever.co/olx/apply")
    with pytest.raises(BrowserSafetyError):
        validate_application_url("https://not-lever.co/olx/apply")
    with pytest.raises(BrowserSafetyError):
        validate_application_url("https://user:pass@jobs.lever.co/olx/apply")


def test_url_canonicalization_and_navigation_trust_are_explicit_and_query_free():
    original = "HTTPS://JOBS.EU.LEVER.CO:443/olx/job-123/apply/?source=private#step-1"
    canonical = canonicalize_application_url(original)
    assert canonical.url == "https://jobs.eu.lever.co/olx/job-123/apply"
    assert canonical.origin == ("https", "jobs.eu.lever.co", 443)

    assert classify_navigation_url(
        original, "https://jobs.eu.lever.co/olx/job-123/apply?tracking=changed"
    ) is NavigationTrust.EXPECTED_ORIGIN
    assert classify_navigation_url(
        original, "https://jobs.lever.co/olx/job-123/apply/?tracking=changed#step-2"
    ) is NavigationTrust.ALLOWED_REDIRECT
    assert classify_navigation_url(
        original, "https://jobs.lever.co/other-company/job-123/apply"
    ) is NavigationTrust.UNEXPECTED_ORIGIN
    assert classify_navigation_url(
        original, "https://malicious-lever.co/olx/job-123/apply"
    ) is NavigationTrust.UNEXPECTED_ORIGIN
    assert is_safe_application_popup(original, "https://jobs.lever.co/olx/job-123/apply?ref=popup")
    assert not is_safe_application_popup(original, "https://jobs.lever.co/olx/job-123/other")
    assert not is_safe_application_popup(original, "https://example.test/olx/job-123/apply")


def test_session_and_snapshot_urls_canonicalize_query_fragment_host_port_and_slash():
    snapshot = ApplicationFormSnapshot(
        url="HTTPS://JOBS.EU.LEVER.CO:443/olx/job-123/apply/?candidate=private#step-2",
        ats=ATSProvider.LEVER,
    )
    assert snapshot.url == "https://jobs.eu.lever.co/olx/job-123/apply"

    session = ApplicationSession(
        job_id=uuid4(), application_package_id=uuid4(),
        url="HTTPS://JOBS.EU.LEVER.CO:443/olx/job-123/apply/?candidate=private#step-2",
        ats=ATSProvider.LEVER,
        redirects_observed=("HTTPS://JOBS.LEVER.CO:443/olx/job-123/apply/?token=private#fragment",),
    )
    assert session.url == "https://jobs.eu.lever.co/olx/job-123/apply"
    assert session.redirects_observed == ("https://jobs.lever.co/olx/job-123/apply",)
