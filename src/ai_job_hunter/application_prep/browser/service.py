"""Local orchestration for a single assisted-only browser application session."""

from __future__ import annotations

from datetime import UTC, datetime

from ai_job_hunter.application_prep.browser.mapping import (
    map_form_fields,
    safe_fill_plan,
)
from ai_job_hunter.application_prep.browser.models import (
    AnswerPolicy,
    ApplicationSession,
    ApplicationSessionStatus,
    ATSProvider,
)
from ai_job_hunter.application_prep.browser.playwright_driver import (
    MappingAndFillPlan,
    PlaywrightAssistedBrowser,
)
from ai_job_hunter.application_prep.browser.safety import BrowserSafetyError, detect_ats
from ai_job_hunter.application_prep.configuration import CandidateApplicationFacts
from ai_job_hunter.application_prep.models import ApplicationPackage
from ai_job_hunter.application_prep.models import CandidateDocument
from ai_job_hunter.candidates.profile import CandidateConfig
from ai_job_hunter.outreach.projects import CandidateProject


def inspect_application_package(
    package: ApplicationPackage,
    *,
    candidate: CandidateConfig,
    facts: CandidateApplicationFacts,
    projects: tuple[CandidateProject, ...] = (),
    documents: tuple[CandidateDocument, ...] = (),
    fill_safe: bool = False,
    dry_run: bool = False,
    browser: PlaywrightAssistedBrowser | None = None,
) -> ApplicationSession:
    if not package.application_url:
        raise BrowserSafetyError("The saved application package has no direct application URL.")
    expected_ats = _provider(package.source_ats) or detect_ats(package.application_url)
    if expected_ats is ATSProvider.UNKNOWN:
        raise BrowserSafetyError("The application URL is not on a supported ATS host.")

    def planner(snapshot, page_url):
        mappings = map_form_fields(
            snapshot,
            candidate=candidate,
            facts=facts,
            package=package,
            projects=projects,
            documents=documents,
        )
        values = safe_fill_plan(snapshot, mappings, candidate=candidate, facts=facts) if fill_safe else {}
        return MappingAndFillPlan(mappings=mappings, values_by_field_id=values)

    result = (browser or PlaywrightAssistedBrowser()).inspect_and_fill(
        package.application_url,
        expected_ats=expected_ats,
        plan_for_snapshot=planner,
        fill_safe=fill_safe,
        dry_run=dry_run,
    )
    all_field_ids = {field.id for snapshot in result.snapshots for field in snapshot.fields}
    filled = set(result.filled_safe_field_ids)
    pending = tuple(
        item.field_id for item in result.mappings
        if item.answer_policy is not AnswerPolicy.SAFE_AUTO_FILL or item.field_id not in filled
    )
    mappings_by_id = {item.field_id: item for item in result.mappings}
    required_fields = tuple(
        field.id for snapshot in result.snapshots for field in snapshot.fields if field.required
    )
    sensitive_fields = tuple(
        item.field_id for item in result.mappings
        if item.answer_policy in {AnswerPolicy.SENSITIVE, AnswerPolicy.OPTIONAL_SELF_IDENTIFICATION}
    )
    legal_fields = tuple(
        item.field_id for item in result.mappings if item.answer_policy is AnswerPolicy.LEGAL
    )
    required_documents = tuple(
        field.id for snapshot in result.snapshots for field in snapshot.fields
        if field.required and mappings_by_id.get(field.id) is not None
        and mappings_by_id[field.id].canonical_field.value in {"CV", "COVER_LETTER", "PORTFOLIO_DOCUMENT", "OTHER_DOCUMENT"}
    )
    readiness_reasons: list[str] = []
    if result.manual_intervention_reason is not None:
        status = ApplicationSessionStatus.BLOCKED
        readiness_reasons.append("Manual intervention is required before the ATS form can be used.")
    else:
        required_missing = any(
            field.required
            and (
                not field.current_value_present
                and (
                mappings_by_id.get(field.id) is None
                or mappings_by_id[field.id].answer_policy is not AnswerPolicy.SAFE_AUTO_FILL
                or field.id not in filled
                )
            )
            for snapshot in result.snapshots
            for field in snapshot.fields
        )
        if required_missing:
            status = ApplicationSessionStatus.NEEDS_INPUT
            readiness_reasons.append("One or more required fields still need input or human review.")
        elif filled:
            status = ApplicationSessionStatus.PARTIALLY_FILLED
        else:
            status = ApplicationSessionStatus.READY_FOR_FINAL_REVIEW
    now = datetime.now(UTC)
    if required_documents:
        readiness_reasons.append("Required document metadata must be configured and reviewed locally.")
    if legal_fields:
        readiness_reasons.append("Legal and work-authorization answers require human review.")
    if sensitive_fields:
        readiness_reasons.append("Sensitive or optional self-identification fields require human review.")
    return ApplicationSession(
        job_id=package.job_id,
        application_package_id=package.id,
        url=result.final_snapshot.url,
        redirects_observed=result.redirects_observed,
        ats=result.final_snapshot.ats,
        current_step=result.final_snapshot.step or len(result.snapshots),
        snapshot=result.final_snapshot,
        snapshots=result.snapshots,
        mappings=result.mappings,
        filled_safe_field_ids=result.filled_safe_field_ids,
        pending_field_ids=tuple(dict.fromkeys(item for item in pending if item in all_field_ids)),
        required_field_ids=tuple(dict.fromkeys(required_fields)),
        sensitive_field_ids=tuple(dict.fromkeys(sensitive_fields)),
        legal_field_ids=tuple(dict.fromkeys(legal_fields)),
        required_document_field_ids=tuple(dict.fromkeys(required_documents)),
        readiness_reasons=tuple(dict.fromkeys(readiness_reasons)),
        dry_run=dry_run,
        would_fill_field_ids=result.would_fill_field_ids,
        would_skip_field_ids=result.would_skip_field_ids,
        needs_input_field_ids=result.needs_input_field_ids,
        status=status,
        created_at=now,
        updated_at=now,
    )


def _provider(value: str | None) -> ATSProvider | None:
    if not value:
        return None
    folded = value.casefold()
    if "greenhouse" in folded:
        return ATSProvider.GREENHOUSE
    if "lever" in folded:
        return ATSProvider.LEVER
    if "ashby" in folded:
        return ATSProvider.ASHBY
    return None
