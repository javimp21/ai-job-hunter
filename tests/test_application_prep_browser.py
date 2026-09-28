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
    ApplicationSession,
    ApplicationSessionStatus,
    ATSProvider,
    CanonicalField,
    ManualInterventionReason,
)
from ai_job_hunter.application_prep.browser.playwright_driver import MappingAndFillPlan, PlaywrightAssistedBrowser
from ai_job_hunter.application_prep.browser.safety import (
    BrowserSafetyError,
    NetworkDecision,
    SubmissionBlockedError,
    assert_safe_next_action,
    detect_ats,
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
    assert mappings["Expected salary"].suggested_answer == "60000 EUR per year"
    assert mappings["Work authorization"].answer_policy is AnswerPolicy.LEGAL
    assert mappings["I agree to the terms"].answer_policy is AnswerPolicy.LEGAL
    assert mappings["Voluntary self-identification"].answer_policy is AnswerPolicy.OPTIONAL_SELF_IDENTIFICATION
    assert mappings["Resume / CV"].answer_policy is AnswerPolicy.DOCUMENT_RECOMMENDATION_ONLY
    assert mappings["Resume / CV"].recommendation == "configured-backend-cv"
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
        url = OLX_URL
        locator_called = False

        def goto(self, *args, **kwargs):
            pass

        def wait_for_load_state(self, *args, **kwargs):
            pass

        def evaluate(self, script):
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


def test_supported_ats_urls_are_https_and_host_allowlisted():
    assert detect_ats(OLX_URL) is ATSProvider.LEVER
    assert validate_application_url(OLX_URL, ATSProvider.LEVER) is ATSProvider.LEVER
    with pytest.raises(BrowserSafetyError):
        validate_application_url("http://jobs.eu.lever.co/olx/apply")
    with pytest.raises(BrowserSafetyError):
        validate_application_url("https://not-lever.co/olx/apply")
    with pytest.raises(BrowserSafetyError):
        validate_application_url("https://user:pass@jobs.lever.co/olx/apply")
