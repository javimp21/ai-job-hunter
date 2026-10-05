"""Contact and outreach persistence with conservative identity matching.

This module stores drafts and lifecycle facts only. It contains no message
transport, delivery client, or send operation.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_job_hunter.contact_discovery.matching import canonical_linkedin_profile_url
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


_ACTIVE_OUTREACH_STATUSES = (
    OutreachStatus.DRAFT.value,
    OutreachStatus.APPROVED.value,
    OutreachStatus.SENT.value,
    OutreachStatus.REPLIED.value,
)
_APPLICATION_ALREADY_APPLIED_STATUSES = (
    ApplicationStatus.APPLIED.value,
    ApplicationStatus.INTERVIEW.value,
    ApplicationStatus.OFFER.value,
    ApplicationStatus.REJECTED.value,
    ApplicationStatus.WITHDRAWN.value,
)
_ALLOWED_TRANSITIONS: dict[OutreachStatus, frozenset[OutreachStatus]] = {
    OutreachStatus.DRAFT: frozenset({OutreachStatus.APPROVED, OutreachStatus.CANCELLED}),
    OutreachStatus.APPROVED: frozenset(
        {OutreachStatus.DRAFT, OutreachStatus.SENT, OutreachStatus.CANCELLED}
    ),
    OutreachStatus.SENT: frozenset(
        {OutreachStatus.REPLIED, OutreachStatus.DECLINED, OutreachStatus.NO_RESPONSE}
    ),
    OutreachStatus.REPLIED: frozenset(),
    OutreachStatus.DECLINED: frozenset(),
    OutreachStatus.NO_RESPONSE: frozenset(),
    OutreachStatus.CANCELLED: frozenset(),
}
_SAFE_CONTACT_METADATA_KEYS = frozenset(
    {
        "evidence_type",
        "observed_at",
        "record_type",
        "confidence",
        # Company Hunter: the public text that supports the contact, its language
        # and a public article/talk of theirs (never an email or phone).
        "quote",
        "language",
        "topic",
        "topic_url",
    }
)
_MAX_CONTACT_METADATA_BYTES = 2048
_MAX_CONTACT_METADATA_VALUE_LENGTH = 256
_SENSITIVE_METADATA_VALUE = re.compile(
    r"(?i)(?:\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b|"
    r"\b(?:api[_ -]?key|access[_ -]?token|password|secret|credential)\b|"
    r"\b(?:sk|ghp|gho|xox[baprs]|tok)[A-Za-z0-9_-]{12,}\b)"
)
_PHONE_LIKE_METADATA_VALUE = re.compile(r"(?<!\w)\+?\d[\d ()-]{7,}\d(?!\w)")


class OutreachPersistenceError(ValueError):
    """A safe persistence or lifecycle validation error."""


class InvalidOutreachTransition(OutreachPersistenceError):
    """Raised when a requested lifecycle transition is not permitted."""


class OutreachSuppressedByApplication(OutreachPersistenceError):
    """Raised when an automatic initial outreach is suppressed by application state."""


@dataclass(frozen=True, slots=True)
class ContactCreateResult:
    contact: Contact | None
    created: bool
    matched_by: str | None = None
    possible_matches: tuple[Contact, ...] = ()


@dataclass(frozen=True, slots=True)
class OutreachCreateResult:
    outreach: Outreach
    created: bool


def create_contact(
    session: Session,
    *,
    company_id: UUID,
    name: str,
    contact_type: ContactType | str = ContactType.OTHER,
    title: str | None = None,
    linkedin_url: str | None = None,
    email: str | None = None,
    source_provider: str | None = None,
    external_id: str | None = None,
    source_url: str | None = None,
    evidence: dict[str, object] | None = None,
    raw_metadata: dict[str, object] | None = None,
    allow_weak_duplicate: bool = False,
) -> ContactCreateResult:
    """Create a company-scoped contact or return exact/possible identity matches.

    Provider/external ID, normalized email, and canonical LinkedIn URL are
    strong signals. Name plus company is weak: it is surfaced as a possible
    match and never merges existing rows automatically. A user can explicitly
    choose to add a separate record with ``allow_weak_duplicate=True``.
    """

    cleaned_name = _required_text(name, "name")
    normalized_contact_type = _coerce_enum(ContactType, contact_type, "contact type")
    normalized_email = _normalize_email(email)
    canonical_linkedin_url = canonical_linkedin_profile_url(linkedin_url)
    normalized_provider = _normalize_provider(source_provider)
    normalized_external_id = _validate_external_id(external_id)
    sanitized_source_url = _sanitize_source_url(source_url)
    if not session.get(Company, company_id):
        raise OutreachPersistenceError("Contact company does not exist.")

    strong_matches: dict[UUID, tuple[Contact, set[str]]] = {}
    if normalized_provider and normalized_external_id:
        _add_strong_matches(
            strong_matches,
            session.scalars(
                select(Contact).where(
                    Contact.company_id == company_id,
                    Contact.source_provider == normalized_provider,
                    Contact.external_id == normalized_external_id,
                )
            ).all(),
            "provider_external_id",
        )
    if normalized_email:
        _add_strong_matches(
            strong_matches,
            session.scalars(
                select(Contact).where(
                    Contact.company_id == company_id,
                    Contact.email == normalized_email,
                )
            ).all(),
            "email",
        )
    if canonical_linkedin_url:
        _add_strong_matches(
            strong_matches,
            session.scalars(
                select(Contact).where(
                    Contact.company_id == company_id,
                    Contact.linkedin_url == canonical_linkedin_url,
                )
            ).all(),
            "linkedin_url",
        )

    conflicting_candidates = [
        contact
        for contact, _signals in strong_matches.values()
        if _strong_identity_conflicts(
            contact,
            provider=normalized_provider,
            external_id=normalized_external_id,
            email=normalized_email,
            linkedin_url=canonical_linkedin_url,
        )
    ]
    if len(strong_matches) == 1 and not conflicting_candidates:
        match, signals = next(iter(strong_matches.values()))
        return ContactCreateResult(
            contact=match,
            created=False,
            matched_by="+".join(sorted(signals)),
        )
    if len(strong_matches) > 1 or conflicting_candidates:
        return ContactCreateResult(
            contact=None,
            created=False,
            possible_matches=tuple(
                item[0] for _, item in sorted(strong_matches.items(), key=lambda pair: str(pair[0]))
            ),
        )

    weak_matches = _find_weak_name_matches(session, company_id, cleaned_name)
    if weak_matches and not allow_weak_duplicate:
        return ContactCreateResult(
            contact=None,
            created=False,
            possible_matches=tuple(weak_matches),
        )

    contact = Contact(
        company_id=company_id,
        name=cleaned_name,
        title=_optional_str(title),
        contact_type=normalized_contact_type.value,
        linkedin_url=canonical_linkedin_url,
        email=normalized_email,
        source_provider=normalized_provider,
        external_id=normalized_external_id,
        source_url=sanitized_source_url,
        evidence=_sanitize_contact_metadata(evidence),
        raw_metadata=_sanitize_contact_metadata(raw_metadata),
    )
    session.add(contact)
    session.flush()
    return ContactCreateResult(
        contact=contact,
        created=True,
        possible_matches=tuple(weak_matches) if allow_weak_duplicate else (),
    )


def create_outreach(
    session: Session,
    *,
    company_id: UUID,
    purpose: OutreachPurpose | str,
    channel: OutreachChannel | str,
    job_id: UUID | None = None,
    contact_id: UUID | None = None,
    application_id: UUID | None = None,
    recipient_contact_type: ContactType | str | None = None,
    subject: str | None = None,
    body: str | None = None,
    recommendation: str | None = None,
    rationale: str | None = None,
    automatic: bool = False,
) -> OutreachCreateResult:
    """Persist a DRAFT, or return an existing active duplicate.

    ``automatic=True`` applies the Application APPLIED-or-later guard. Manual
    persistence remains available so historical records are not discarded.
    No path in this function sends or delivers content.
    """

    normalized_purpose = _coerce_enum(OutreachPurpose, purpose, "outreach purpose")
    normalized_channel = _coerce_enum(OutreachChannel, channel, "outreach channel")
    normalized_recipient_type = (
        _coerce_enum(ContactType, recipient_contact_type, "recipient contact type")
        if recipient_contact_type is not None
        else None
    )
    company = session.get(Company, company_id)
    if company is None:
        raise OutreachPersistenceError("Outreach company does not exist.")

    if job_id is not None:
        job = session.get(Job, job_id)
        if job is None:
            raise OutreachPersistenceError("Outreach job does not exist.")
        if job.company_id is not None and job.company_id != company_id:
            raise OutreachPersistenceError("Outreach company does not match the job company.")
    if contact_id is not None:
        contact = session.get(Contact, contact_id)
        if contact is None or contact.company_id != company_id:
            raise OutreachPersistenceError("Outreach contact must belong to the selected company.")
    if application_id is not None:
        application = session.get(Application, application_id)
        if application is None:
            raise OutreachPersistenceError("Outreach application does not exist.")
        if job_id is None or application.job_id != job_id:
            raise OutreachPersistenceError("Outreach application must belong to the selected job.")

    if automatic and job_id is not None and _has_applied_or_later_application(session, job_id):
        raise OutreachSuppressedByApplication(
            "Automatic initial outreach is suppressed because this job has an application at APPLIED or later."
        )

    existing = find_active_duplicate(
        session,
        company_id=company_id,
        job_id=job_id,
        contact_id=contact_id,
        purpose=normalized_purpose,
        channel=normalized_channel,
    )
    if existing is not None:
        return OutreachCreateResult(outreach=existing, created=False)

    outreach = Outreach(
        company_id=company_id,
        job_id=job_id,
        contact_id=contact_id,
        application_id=application_id,
        purpose=normalized_purpose.value,
        channel=normalized_channel.value,
        status=OutreachStatus.DRAFT.value,
        recipient_contact_type=(normalized_recipient_type.value if normalized_recipient_type else None),
        subject=_optional_str(subject),
        body=_optional_str(body),
        recommendation=_optional_str(recommendation),
        rationale=_optional_str(rationale),
    )
    session.add(outreach)
    session.flush()
    session.add(
        OutreachEvent(
            outreach_id=outreach.id,
            event_type=OutreachEventType.CREATED.value,
            from_status=None,
            to_status=OutreachStatus.DRAFT.value,
            occurred_at=_next_event_time(session, outreach.id),
        )
    )
    session.flush()
    return OutreachCreateResult(outreach=outreach, created=True)


def find_active_duplicate(
    session: Session,
    *,
    company_id: UUID,
    job_id: UUID | None,
    contact_id: UUID | None,
    purpose: OutreachPurpose | str,
    channel: OutreachChannel | str | None = None,
) -> Outreach | None:
    """Return the oldest active outreach with the same dedupe identity.

    Company-level outreach (no job) is unique per channel too, so an email
    draft and a LinkedIn draft for one company coexist.
    """

    normalized_purpose = _coerce_enum(OutreachPurpose, purpose, "outreach purpose")
    statement = select(Outreach).where(
        Outreach.purpose == normalized_purpose.value,
        Outreach.status.in_(_ACTIVE_OUTREACH_STATUSES),
    )
    if job_id is None:
        statement = statement.where(Outreach.company_id == company_id)
        if channel is not None:
            statement = statement.where(
                Outreach.channel == _coerce_enum(OutreachChannel, channel, "outreach channel").value
            )
    statement = statement.where(
        Outreach.job_id.is_(None) if job_id is None else Outreach.job_id == job_id
    )
    statement = statement.where(
        Outreach.contact_id.is_(None)
        if contact_id is None
        else Outreach.contact_id == contact_id
    )
    return session.scalars(statement.order_by(Outreach.created_at, Outreach.id)).first()


def transition_outreach(
    session: Session,
    outreach_id: UUID,
    new_status: OutreachStatus | str,
    *,
    note: str | None = None,
    manual: bool = False,
) -> Outreach:
    """Apply one allowed state transition and append its history event.

    SENT is state recording only and requires an explicit ``manual=True``
    assertion. It never triggers message delivery.
    """

    target_status = _coerce_enum(OutreachStatus, new_status, "outreach status")
    outreach = session.get(Outreach, outreach_id)
    if outreach is None:
        raise OutreachPersistenceError("Outreach does not exist.")
    current_status = OutreachStatus(outreach.status)
    if target_status not in _ALLOWED_TRANSITIONS[current_status]:
        raise InvalidOutreachTransition(
            f"Transition {current_status.value} -> {target_status.value} is not allowed."
        )
    if target_status is OutreachStatus.SENT and not manual:
        raise InvalidOutreachTransition("SENT can only be recorded with manual=True.")

    outreach.status = target_status.value
    session.flush()
    event_type = OutreachEventType(target_status.value)
    session.add(
        OutreachEvent(
            outreach_id=outreach.id,
            event_type=event_type.value,
            from_status=current_status.value,
            to_status=target_status.value,
            note=_optional_str(note),
            occurred_at=_next_event_time(session, outreach.id),
        )
    )
    session.flush()
    return outreach


def append_outreach_note(session: Session, outreach_id: UUID, note: str) -> OutreachEvent:
    """Append a note event without overwriting prior history."""

    outreach = session.get(Outreach, outreach_id)
    if outreach is None:
        raise OutreachPersistenceError("Outreach does not exist.")
    event_row = OutreachEvent(
        outreach_id=outreach.id,
        event_type=OutreachEventType.NOTE_ADDED.value,
        from_status=outreach.status,
        to_status=outreach.status,
        note=_required_text(note, "note"),
        occurred_at=_next_event_time(session, outreach.id),
    )
    session.add(event_row)
    session.flush()
    return event_row


def list_contacts_for_company(session: Session, company_id: UUID) -> list[Contact]:
    """List persisted contacts for one company without external discovery."""

    return session.scalars(
        select(Contact).where(Contact.company_id == company_id).order_by(Contact.name, Contact.id)
    ).all()


def list_outreaches(
    session: Session,
    *,
    company_id: UUID | None = None,
    job_id: UUID | None = None,
    status: OutreachStatus | str | None = None,
    limit: int | None = None,
) -> list[Outreach]:
    """List persisted outreach records for CLI and feed consumers."""

    statement = select(Outreach)
    if company_id is not None:
        statement = statement.where(Outreach.company_id == company_id)
    if job_id is not None:
        statement = statement.where(Outreach.job_id == job_id)
    if status is not None:
        statement = statement.where(
            Outreach.status == _coerce_enum(OutreachStatus, status, "outreach status").value
        )
    statement = statement.order_by(Outreach.created_at.desc(), Outreach.id)
    if limit is not None:
        if limit < 1:
            raise OutreachPersistenceError("limit must be positive.")
        statement = statement.limit(limit)
    return session.scalars(statement).all()


def get_outreach_history(session: Session, outreach_id: UUID) -> list[OutreachEvent]:
    """Read append-only events for a single outreach in chronological order."""

    if session.get(Outreach, outreach_id) is None:
        raise OutreachPersistenceError("Outreach does not exist.")
    return session.scalars(
        select(OutreachEvent)
        .where(OutreachEvent.outreach_id == outreach_id)
        .order_by(OutreachEvent.occurred_at, OutreachEvent.id)
    ).all()


def _has_applied_or_later_application(session: Session, job_id: UUID) -> bool:
    return (
        session.scalar(
            select(Application.id)
            .where(
                Application.job_id == job_id,
                Application.status.in_(_APPLICATION_ALREADY_APPLIED_STATUSES),
            )
            .limit(1)
        )
        is not None
    )


def _next_event_time(session: Session, outreach_id: UUID) -> datetime:
    latest = session.scalar(
        select(OutreachEvent.occurred_at)
        .where(OutreachEvent.outreach_id == outreach_id)
        .order_by(OutreachEvent.occurred_at.desc(), OutreachEvent.id.desc())
        .limit(1)
    )
    now = datetime.now(UTC)
    if latest is None:
        return now
    if latest.tzinfo is None or latest.utcoffset() is None:
        latest = latest.replace(tzinfo=UTC)
    else:
        latest = latest.astimezone(UTC)
    return max(now, latest + timedelta(microseconds=1))


def _find_weak_name_matches(session: Session, company_id: UUID, name: str) -> list[Contact]:
    normalized_name = _normalize_name(name)
    contacts = session.scalars(
        select(Contact).where(Contact.company_id == company_id).order_by(Contact.name, Contact.id)
    ).all()
    return [contact for contact in contacts if _normalize_name(contact.name) == normalized_name]


def _add_strong_matches(
    destination: dict[UUID, tuple[Contact, set[str]]],
    matches: list[Contact],
    signal: str,
) -> None:
    for contact in matches:
        if contact.id in destination:
            destination[contact.id][1].add(signal)
        else:
            destination[contact.id] = (contact, {signal})


def _strong_identity_conflicts(
    contact: Contact,
    *,
    provider: str | None,
    external_id: str | None,
    email: str | None,
    linkedin_url: str | None,
) -> bool:
    existing_provider = _normalize_provider(contact.source_provider)
    existing_external_id = _optional_str(contact.external_id)
    if (
        provider
        and external_id
        and existing_provider
        and existing_external_id
        and provider == existing_provider
        and external_id != existing_external_id
    ):
        return True
    existing_email = _normalize_email(contact.email)
    if email and existing_email and email != existing_email:
        return True
    existing_linkedin = canonical_linkedin_profile_url(contact.linkedin_url)
    return bool(linkedin_url and existing_linkedin and linkedin_url != existing_linkedin)


def _sanitize_contact_metadata(value: dict[str, object] | None) -> dict[str, object] | None:
    """Keep bounded, non-personal source facts; omit arbitrary raw payloads.

    Identity/contact fields have dedicated columns. Only a small safe-key
    allowlist is retained here, so provider payloads cannot duplicate PII or
    credentials into unreviewed JSON metadata.
    """

    if value is None:
        return None
    safe: dict[str, object] = {}
    for key, item in value.items():
        normalized_key = key.strip().casefold() if isinstance(key, str) else ""
        if normalized_key not in _SAFE_CONTACT_METADATA_KEYS:
            continue
        if isinstance(item, str):
            cleaned: object = item.strip()
            if len(cleaned) > _MAX_CONTACT_METADATA_VALUE_LENGTH:
                raise OutreachPersistenceError("Contact metadata value exceeds the size limit.")
            if _SENSITIVE_METADATA_VALUE.search(cleaned) or _PHONE_LIKE_METADATA_VALUE.search(cleaned):
                continue
        elif item is None or isinstance(item, (bool, int, float)):
            cleaned = item
        else:
            continue
        safe[normalized_key] = cleaned
    if len(json.dumps(safe, ensure_ascii=False).encode("utf-8")) > _MAX_CONTACT_METADATA_BYTES:
        raise OutreachPersistenceError("Contact metadata exceeds the size limit.")
    return safe or None


def _normalize_email(value: str | None) -> str | None:
    text_value = _optional_str(value)
    return text_value.casefold() if text_value else None


def _normalize_provider(value: str | None) -> str | None:
    text_value = _optional_str(value)
    if text_value is not None and (len(text_value) > 100 or _has_control_chars(text_value)):
        raise OutreachPersistenceError("Contact source provider is invalid.")
    return text_value.casefold() if text_value else None


def _validate_external_id(value: str | None) -> str | None:
    cleaned = _optional_str(value)
    if cleaned is not None and (len(cleaned) > 512 or _has_control_chars(cleaned)):
        raise OutreachPersistenceError("Contact external ID is invalid.")
    return cleaned


def _sanitize_source_url(value: str | None) -> str | None:
    cleaned = _optional_str(value)
    if cleaned is None:
        return None
    if len(cleaned) > 2048 or _has_control_chars(cleaned):
        raise OutreachPersistenceError("Contact source URL is invalid.")
    try:
        parsed = urlsplit(cleaned)
        _ = parsed.port
    except ValueError as error:
        raise OutreachPersistenceError("Contact source URL is invalid.") from error
    if (
        parsed.scheme.casefold() not in {"http", "https"}
        or not parsed.hostname
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise OutreachPersistenceError("Contact source URL must be an absolute HTTP(S) URL without userinfo.")
    return urlunsplit((parsed.scheme.casefold(), parsed.netloc, parsed.path, "", ""))


def _has_control_chars(value: str) -> bool:
    return any(unicodedata.category(character) == "Cc" for character in value)


def _normalize_name(value: str) -> str:
    return " ".join(value.casefold().split())


def _optional_str(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def _required_text(value: str, field_name: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise OutreachPersistenceError(f"{field_name} is required.")
    return cleaned


def _coerce_enum(enum_type: type[StrEnum], value: StrEnum | str, label: str) -> StrEnum:
    try:
        return enum_type(value)
    except (TypeError, ValueError) as error:
        raise OutreachPersistenceError(f"Unsupported {label}.") from error
