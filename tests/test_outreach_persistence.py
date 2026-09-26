from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from ai_job_hunter.models.application import Application, ApplicationStatus
from ai_job_hunter.models.company import Company
from ai_job_hunter.models.contact import Contact, ContactType
from ai_job_hunter.models.job import Job
from ai_job_hunter.models.outreach import (
    Outreach,
    OutreachChannel,
    OutreachEvent,
    OutreachEventType,
    OutreachPurpose,
    OutreachStatus,
)
from ai_job_hunter.services.outreach_persistence import (
    ContactCreateResult,
    InvalidOutreachTransition,
    OutreachSuppressedByApplication,
    append_outreach_note,
    create_contact,
    create_outreach,
    get_outreach_history,
    list_contacts_for_company,
    transition_outreach,
)


def _company_job(db_session, *, company_name: str = "Example Co") -> tuple[Company, Job]:
    company = Company(name=company_name)
    job = Job(company=company, title="Backend Engineer")
    db_session.add_all([company, job])
    db_session.flush()
    return company, job


def test_contact_persistence_keeps_unknown_identity_fields_null(db_session) -> None:
    company, _job = _company_job(db_session)

    result = create_contact(
        db_session,
        company_id=company.id,
        name="A Person",
        contact_type=ContactType.RECRUITER,
    )

    assert result.created is True
    assert result.contact is not None
    assert result.contact.name == "A Person"
    assert result.contact.contact_type == ContactType.RECRUITER.value
    assert result.contact.email is None
    assert result.contact.linkedin_url is None
    assert list_contacts_for_company(db_session, company.id) == [result.contact]


@pytest.mark.parametrize(
    ("first", "second"),
    [
        (
            {"source_provider": "ExampleSource", "external_id": "person-1"},
            {"source_provider": "examplesource", "external_id": "person-1"},
        ),
        ({"email": " PERSON@Example.Test "}, {"email": "person@example.test"}),
        (
            {"linkedin_url": "https://www.linkedin.com/in/A-Name/?trk=profile"},
            {"linkedin_url": "https://linkedin.com/in/a-name"},
        ),
    ],
)
def test_contact_strong_identity_dedup_returns_existing_without_merging(
    db_session, first: dict[str, str], second: dict[str, str]
) -> None:
    company, _job = _company_job(db_session)
    created = create_contact(
        db_session,
        company_id=company.id,
        name="Source Name",
        contact_type=ContactType.RECRUITER,
        **first,
    )
    assert created.contact is not None
    db_session.flush()

    matched = create_contact(
        db_session,
        company_id=company.id,
        name="A Different Incoming Name",
        contact_type=ContactType.OTHER,
        **second,
    )

    assert matched.created is False
    assert matched.contact is created.contact
    assert matched.matched_by is not None
    assert matched.contact.name == "Source Name"
    assert db_session.scalar(select(func.count()).select_from(Contact)) == 1


def test_name_company_is_only_a_possible_match_and_does_not_merge(db_session) -> None:
    company, _job = _company_job(db_session)
    first = create_contact(
        db_session,
        company_id=company.id,
        name="  Jane   Doe ",
        contact_type=ContactType.ENGINEER,
    )
    assert first.contact is not None

    possible = create_contact(
        db_session,
        company_id=company.id,
        name="jane doe",
        contact_type=ContactType.HIRING_MANAGER,
    )

    assert possible.created is False
    assert possible.contact is None
    assert possible.possible_matches == (first.contact,)
    assert db_session.scalar(select(func.count()).select_from(Contact)) == 1


def test_multiple_conflicting_strong_identity_matches_are_returned_without_merge(db_session) -> None:
    company, _job = _company_job(db_session)
    by_email = create_contact(
        db_session,
        company_id=company.id,
        name="Person One",
        email="one@example.test",
    ).contact
    by_linkedin = create_contact(
        db_session,
        company_id=company.id,
        name="Person Two",
        linkedin_url="https://linkedin.com/in/person-two",
    ).contact
    assert by_email is not None and by_linkedin is not None

    ambiguous = create_contact(
        db_session,
        company_id=company.id,
        name="Incoming Person",
        email="one@example.test",
        linkedin_url="https://www.linkedin.com/in/person-two/?trk=public",
    )

    assert ambiguous.created is False
    assert ambiguous.contact is None
    assert set(ambiguous.possible_matches) == {by_email, by_linkedin}


def test_matching_one_identifier_does_not_override_conflicting_strong_identifier(db_session) -> None:
    company, _job = _company_job(db_session)
    original = create_contact(
        db_session,
        company_id=company.id,
        name="Original Record",
        email="same@example.test",
        linkedin_url="https://linkedin.com/in/original",
    ).contact
    assert original is not None

    incoming = create_contact(
        db_session,
        company_id=company.id,
        name="Updated Record",
        email="same@example.test",
        linkedin_url="https://linkedin.com/in/different",
    )

    assert incoming.created is False
    assert incoming.contact is None
    assert incoming.possible_matches == (original,)


def test_linkedin_dedup_only_accepts_canonical_profile_paths(db_session) -> None:
    company, _job = _company_job(db_session)
    invalid = create_contact(
        db_session,
        company_id=company.id,
        name="Company Page Is Not A Person",
        linkedin_url="https://www.linkedin.com/company/example/",
    )
    valid = create_contact(
        db_session,
        company_id=company.id,
        name="Profile",
        linkedin_url="https://www.linkedin.com/in/person/?trk=public_profile",
    )

    assert invalid.contact is not None
    assert invalid.contact.linkedin_url is None
    assert valid.contact is not None
    assert valid.contact.linkedin_url == "https://linkedin.com/in/person"


def test_contact_metadata_drops_pii_and_credentials_and_is_bounded(db_session) -> None:
    company, _job = _company_job(db_session)
    result = create_contact(
        db_session,
        company_id=company.id,
        name="Canonical Name",
        email="known@example.test",
        evidence={
            "evidence_type": "public profile",
            "name": "duplicate raw name",
            "email": "private@example.test",
            "note": "password: hidden",
        },
        raw_metadata={
            "record_type": "public_profile",
            "phone": "+1 555 111 2222",
            "api_key": "should-not-survive",
        },
    )

    assert result.contact is not None
    assert result.contact.email == "known@example.test"
    assert result.contact.evidence == {
        "evidence_type": "public profile",
    }
    assert result.contact.raw_metadata == {"record_type": "public_profile"}

    with pytest.raises(ValueError, match="size limit"):
        create_contact(
            db_session,
            company_id=company.id,
            name="Another Contact",
            raw_metadata={"evidence_type": "x" * 257},
        )


def test_contact_source_url_drops_query_fragment_and_rejects_userinfo(db_session) -> None:
    company, _job = _company_job(db_session)
    contact = create_contact(
        db_session,
        company_id=company.id,
        name="Public Contact",
        source_url="https://example.test/team/person?email=private%40example.test#contact",
    ).contact
    assert contact is not None
    assert contact.source_url == "https://example.test/team/person"

    with pytest.raises(ValueError, match="userinfo"):
        create_contact(
            db_session,
            company_id=company.id,
            name="Unsafe Contact",
            source_url="https://user:password@example.test/profile",
        )


@pytest.mark.parametrize("external_id", ["x" * 513, "valid\nunsafe"])
def test_contact_external_id_is_bounded_and_rejects_control_characters(
    db_session, external_id: str
) -> None:
    company, _job = _company_job(db_session)
    with pytest.raises(ValueError, match="external ID is invalid"):
        create_contact(
            db_session,
            company_id=company.id,
            name="Contact",
            source_provider="public-directory",
            external_id=external_id,
        )


def test_outreach_creation_persists_placeholder_and_created_event(db_session) -> None:
    company, job = _company_job(db_session)

    result = create_outreach(
        db_session,
        company_id=company.id,
        job_id=job.id,
        purpose=OutreachPurpose.RECRUITER_INTRO,
        channel=OutreachChannel.LINKEDIN,
        recipient_contact_type=ContactType.RECRUITER,
        subject="Introduction",
        body="A factual draft without an invented recipient.",
    )

    assert result.created is True
    assert result.outreach.status == OutreachStatus.DRAFT.value
    assert result.outreach.contact_id is None
    assert result.outreach.recipient_contact_type == ContactType.RECRUITER.value
    assert result.outreach.subject == "Introduction"
    assert [item.event_type for item in get_outreach_history(db_session, result.outreach.id)] == [
        OutreachEventType.CREATED.value
    ]


def test_duplicate_active_outreach_returns_existing_and_does_not_append_created_event(
    db_session,
) -> None:
    company, job = _company_job(db_session)
    contact = create_contact(
        db_session,
        company_id=company.id,
        name="Recruiter",
        contact_type=ContactType.RECRUITER,
    ).contact
    assert contact is not None
    first = create_outreach(
        db_session,
        company_id=company.id,
        job_id=job.id,
        contact_id=contact.id,
        purpose=OutreachPurpose.REFERRAL,
        channel=OutreachChannel.EMAIL,
    )
    second = create_outreach(
        db_session,
        company_id=company.id,
        job_id=job.id,
        contact_id=contact.id,
        purpose=OutreachPurpose.REFERRAL,
        channel=OutreachChannel.LINKEDIN,
        body="This content must not overwrite the active draft.",
    )

    assert first.created is True
    assert second.created is False
    assert second.outreach.id == first.outreach.id
    assert second.outreach.body is None
    assert len(get_outreach_history(db_session, first.outreach.id)) == 1


@pytest.mark.parametrize("job_id,contact_id", [(False, False), (True, False), (False, True)])
def test_active_duplicate_prevention_handles_optional_job_and_contact(
    db_session, job_id: bool, contact_id: bool
) -> None:
    company, job = _company_job(db_session)
    contact = create_contact(
        db_session,
        company_id=company.id,
        name="Contact",
        contact_type=ContactType.OTHER,
    ).contact
    assert contact is not None
    selected_job_id = job.id if job_id else None
    selected_contact_id = contact.id if contact_id else None
    first = create_outreach(
        db_session,
        company_id=company.id,
        job_id=selected_job_id,
        contact_id=selected_contact_id,
        purpose=OutreachPurpose.COLD_OUTREACH,
        channel=OutreachChannel.EMAIL,
    )
    repeated = create_outreach(
        db_session,
        company_id=company.id,
        job_id=selected_job_id,
        contact_id=selected_contact_id,
        purpose=OutreachPurpose.COLD_OUTREACH,
        channel=OutreachChannel.EMAIL,
    )
    assert repeated.outreach.id == first.outreach.id
    assert repeated.created is False


def test_lifecycle_appends_history_and_requires_manual_sent_record(db_session) -> None:
    company, job = _company_job(db_session)
    created = create_outreach(
        db_session,
        company_id=company.id,
        job_id=job.id,
        purpose=OutreachPurpose.JOB_INTEREST,
        channel=OutreachChannel.EMAIL,
    )

    approved = transition_outreach(db_session, created.outreach.id, OutreachStatus.APPROVED)
    with pytest.raises(InvalidOutreachTransition, match="manual=True"):
        transition_outreach(db_session, approved.id, OutreachStatus.SENT)
    sent = transition_outreach(db_session, approved.id, OutreachStatus.SENT, manual=True)
    replied = transition_outreach(db_session, sent.id, OutreachStatus.REPLIED, note="Reply recorded manually.")

    assert replied.status == OutreachStatus.REPLIED.value
    assert [event.to_status for event in get_outreach_history(db_session, replied.id)] == [
        OutreachStatus.DRAFT.value,
        OutreachStatus.APPROVED.value,
        OutreachStatus.SENT.value,
        OutreachStatus.REPLIED.value,
    ]
    assert [event.event_type for event in get_outreach_history(db_session, replied.id)] == [
        OutreachEventType.CREATED.value,
        OutreachEventType.APPROVED.value,
        OutreachEventType.SENT.value,
        OutreachEventType.REPLIED.value,
    ]


def test_approved_outreach_can_return_to_draft_with_history(db_session) -> None:
    company, job = _company_job(db_session)
    draft = create_outreach(
        db_session,
        company_id=company.id,
        job_id=job.id,
        purpose=OutreachPurpose.JOB_INTEREST,
        channel=OutreachChannel.EMAIL,
    )
    transition_outreach(db_session, draft.outreach.id, OutreachStatus.APPROVED)
    returned = transition_outreach(
        db_session,
        draft.outreach.id,
        OutreachStatus.DRAFT,
        note="Approval withdrawn for edits.",
    )

    assert returned.status == OutreachStatus.DRAFT.value
    assert [event.event_type for event in get_outreach_history(db_session, returned.id)] == [
        OutreachEventType.CREATED.value,
        OutreachEventType.APPROVED.value,
        OutreachEventType.DRAFT.value,
    ]


def test_invalid_terminal_transition_and_history_mutation_are_rejected(db_session) -> None:
    company, job = _company_job(db_session)
    created = create_outreach(
        db_session,
        company_id=company.id,
        job_id=job.id,
        purpose=OutreachPurpose.JOB_INTEREST,
        channel=OutreachChannel.EMAIL,
    )
    cancelled = transition_outreach(db_session, created.outreach.id, OutreachStatus.CANCELLED)
    with pytest.raises(InvalidOutreachTransition):
        transition_outreach(db_session, cancelled.id, OutreachStatus.APPROVED)

    event_row = get_outreach_history(db_session, cancelled.id)[0]
    event_row.note = "changed"
    with pytest.raises(ValueError, match="append-only"):
        db_session.flush()
    db_session.rollback()


def test_note_history_is_append_only_and_database_prevents_active_duplicate(db_session) -> None:
    company, job = _company_job(db_session)
    created = create_outreach(
        db_session,
        company_id=company.id,
        job_id=job.id,
        purpose=OutreachPurpose.JOB_INTEREST,
        channel=OutreachChannel.EMAIL,
    )
    append_outreach_note(db_session, created.outreach.id, "Manual note.")
    assert len(get_outreach_history(db_session, created.outreach.id)) == 2

    duplicate = Outreach(
        company_id=company.id,
        job_id=job.id,
        purpose=OutreachPurpose.JOB_INTEREST.value,
        channel=OutreachChannel.EMAIL.value,
        status=OutreachStatus.DRAFT.value,
    )
    db_session.add(duplicate)
    with pytest.raises(IntegrityError):
        db_session.flush()
    db_session.rollback()


@pytest.mark.parametrize("status", [
    ApplicationStatus.APPLIED,
    ApplicationStatus.INTERVIEW,
    ApplicationStatus.OFFER,
    ApplicationStatus.REJECTED,
    ApplicationStatus.WITHDRAWN,
])
def test_applied_or_later_suppresses_automatic_outreach_but_manual_history_remains(
    db_session, status: ApplicationStatus
) -> None:
    company, job = _company_job(db_session)
    application = Application(job_id=job.id, status=status.value)
    db_session.add(application)
    db_session.flush()

    with pytest.raises(OutreachSuppressedByApplication):
        create_outreach(
            db_session,
            company_id=company.id,
            job_id=job.id,
            application_id=application.id,
            purpose=OutreachPurpose.RECRUITER_INTRO,
            channel=OutreachChannel.EMAIL,
            automatic=True,
        )

    manual = create_outreach(
        db_session,
        company_id=company.id,
        job_id=job.id,
        application_id=application.id,
        purpose=OutreachPurpose.RECRUITER_INTRO,
        channel=OutreachChannel.EMAIL,
        automatic=False,
    )
    assert manual.created is True
    assert db_session.scalar(select(func.count()).select_from(OutreachEvent)) == 1


def test_jobless_company_cold_outreach_is_supported(db_session) -> None:
    company = Company(name="Company Without Job")
    db_session.add(company)
    db_session.flush()

    draft = create_outreach(
        db_session,
        company_id=company.id,
        purpose=OutreachPurpose.COLD_OUTREACH,
        channel=OutreachChannel.EMAIL,
        recipient_contact_type=ContactType.FOUNDER,
    )

    assert draft.created is True
    assert draft.outreach.job_id is None
    assert draft.outreach.status == OutreachStatus.DRAFT.value
