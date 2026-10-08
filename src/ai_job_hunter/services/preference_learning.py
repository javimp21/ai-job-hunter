"""The alerts learn from a person's free-text opinions.

Every few days, when at least three new opinions exist, Claude reads them with each offer's facts and returns structured
changes of seven kinds (see ``services/learned.py``). Each valid change is applied at once, recorded with the opinion
that caused it and announced to the person with an "Undo" button; anything Claude proposes outside those kinds is dropped.
Someone's opinion about one offer is only turned into a rule when it clearly says so.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_job_hunter.models import ReportDelivery
from ai_job_hunter.models.usage import PreferenceChange
from ai_job_hunter.models.user import User
from ai_job_hunter.services import learned
from ai_job_hunter.services.cover_letters import CoverLetterError, _anthropic_client
from ai_job_hunter.services.feedback_review import FeedbackItem, collect_notes

ADAPT_KIND = "PREFERENCE_ADAPT"
MODEL = "claude-sonnet-5-5"
MIN_NOTES = 3
MIN_DAYS_BETWEEN = 2
MAX_CHANGES = 5
TOOL = "propose_changes"
UNDO_PREFIX = "pc:undo:"

_SYSTEM = """You tune the job alerts of one job seeker from the free-text opinions they wrote about offers.
You get today's date, the opinions, and for each one the offer it is about (title, company, vote).

Call the tool once with the changes the person CLEARLY asked for. Allowed kinds and their value:
- exclude_title_term: a job-title word or phrase never to alert about (a role they do not want). Value: the term, 4 to 40 characters, e.g. "full stack".
- exclude_company: a company never to alert about. Value: the company name exactly as in the offer.
- exclude_language: a spoken language that must not be required. Value: the English name in lower case, e.g. "german".
- more_like_this: they want more offers like the one they praised. Value: that offer's job title.
- prefer_technology: a technology they prefer (software only). Value: its name.
- quiet_hours: they do not want alerts at some hours. Value: {"start": hour, "end": hour} in their local 24h time, e.g. night = {"start": 22, "end": 8}.
- pause_until: they want a pause. Value: an ISO date (YYYY-MM-DD) when alerts resume.

Rules:
- Propose a change only when the opinion states a general preference or asks for it ("this type of position does not interest me", "no consultancies", "nothing that asks German", "do not alert me at night", "pause until Monday"). An opinion that only describes one offer ("the salary is low here") is NOT a change: propose nothing for it.
- A vote alone is never a reason. Never invent preferences the person did not state.
- Prefer the narrowest change that satisfies the opinion. At most 5 changes. If nothing qualifies, return an empty list.
- note_number is the opinion the change comes from. reason is one short sentence in Spanish, in the second person, saying what you understood."""

_VALUE_SCHEMA = {"anyOf": [{"type": "string"}, {"type": "object"}]}


@dataclass(frozen=True, slots=True)
class ProposedChange:
    kind: str
    value: Any
    reason: str
    note_number: int


@dataclass(frozen=True, slots=True)
class Announcement:
    text: str
    change_id: Any


def build_request(items: list[FeedbackItem], today: date) -> dict[str, Any]:
    lines = [f"Today: {today.isoformat()}", ""]
    for index, item in enumerate(items, 1):
        lines += [
            f"[{index}] vote={item.vote or 'none'} | offer: {item.title} @ {item.company}",
            f"    opinion: {item.note}",
            "",
        ]
    return {
        "model": MODEL,
        "max_tokens": 1500,
        "system": _SYSTEM,
        "messages": [{"role": "user", "content": "\n".join(lines)}],
        "tools": [{
            "name": TOOL,
            "description": "The changes to the person's alerts that their opinions clearly ask for.",
            "input_schema": {
                "type": "object",
                "properties": {"changes": {"type": "array", "items": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": list(learned.KINDS)},
                        "value": _VALUE_SCHEMA,
                        "note_number": {"type": "integer"},
                        "reason": {"type": "string"},
                    },
                    "required": ["kind", "value", "note_number", "reason"],
                }}},
                "required": ["changes"],
            },
        }],
        "tool_choice": {"type": "tool", "name": TOOL},
    }


def parse_changes(raw: Any, note_count: int) -> list[ProposedChange]:
    """The usable changes of Claude's answer; anything malformed or out of range is dropped, never repaired."""

    result: list[ProposedChange] = []
    items = raw.get("changes") if isinstance(raw, dict) else None
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict) or item.get("kind") not in learned.KINDS:
            continue
        number, reason, value = item.get("note_number"), item.get("reason"), item.get("value")
        if not isinstance(number, int) or isinstance(number, bool) or not 1 <= number <= note_count:
            continue
        if not isinstance(reason, str) or not reason.strip():
            continue
        if item["kind"] in learned.LIST_KINDS:
            if not isinstance(value, str) or not 3 <= len(value.strip()) <= 60:
                continue
            if item["kind"] == "exclude_title_term" and len(value.strip()) < 4:
                continue
        result.append(ProposedChange(item["kind"], value, reason.strip()[:200], number))
        if len(result) == MAX_CHANGES:
            break
    return result


def _last_adaptation(session: Session) -> datetime | None:
    from sqlalchemy import func

    value = session.scalar(select(func.max(ReportDelivery.sent_at)).where(ReportDelivery.kind == ADAPT_KIND))
    return value if value is None or value.tzinfo is not None else value.replace(tzinfo=UTC)


def due(session: Session, *, now: datetime) -> list[FeedbackItem] | None:
    """The new opinions when enough exist and enough time has passed since the last adaptation, else None."""

    last = _last_adaptation(session)
    if last is not None and now - last < timedelta(days=MIN_DAYS_BETWEEN):
        return None
    items = collect_notes(session, since=last)
    return items if len(items) >= MIN_NOTES else None


def adapt(session: Session, user: User, *, client: Any | None = None, now: datetime | None = None) -> list[Announcement]:
    """Read the new opinions, apply what they clearly ask for and return one announcement per change.

    Acts as whoever is the acting user of the session's context. Nothing happens (and nothing is spent) when fewer than
    three new opinions exist or the last adaptation was less than two days ago.
    """

    moment = now or datetime.now(UTC)
    items = due(session, now=moment)
    if items is None:
        return []
    try:
        response = (client or _anthropic_client()).messages.create(**build_request(items, moment.date()))
        block = next((b for b in response.content if getattr(b, "type", "") == "tool_use"), None)
    except CoverLetterError:
        return []
    except Exception:  # noqa: BLE001 - provider errors never carry details worth echoing; try again next time
        return []
    proposals = parse_changes(block.input if block is not None else None, len(items))
    announcements: list[Announcement] = []
    for proposal in proposals:
        if not learned.apply_change(session, user, proposal.kind, proposal.value):
            continue
        note = items[proposal.note_number - 1].note
        change = PreferenceChange(kind=proposal.kind, value={"value": proposal.value}, reason=proposal.reason, note=note[:500])
        session.add(change)
        session.flush()
        announcements.append(Announcement(_announcement_text(proposal, note), change.id))
    session.add(ReportDelivery(kind=ADAPT_KIND, period_start=moment, period_end=moment, sent_at=moment))
    session.flush()
    return announcements


def _announcement_text(proposal: ProposedChange, note: str) -> str:
    value = proposal.value
    what = {
        "exclude_title_term": f"dejo de avisarte de puestos con «{value}» en el título",
        "exclude_company": f"dejo de avisarte de ofertas de {value}",
        "exclude_language": f"dejo de avisarte de ofertas que pidan {value}",
        "more_like_this": f"te avisaré de más puestos como «{value}»",
        "prefer_technology": f"daré más peso a {value}",
        "quiet_hours": (
            f"no te avisaré entre las {value['start']}:00 y las {value['end']}:00"
            if isinstance(value, dict) else "ajusto tus horas de silencio"
        ),
        "pause_until": f"pauso los avisos hasta el {value}",
    }[proposal.kind]
    quote = re.sub(r"\s+", " ", note).strip()
    quote = quote if len(quote) <= 90 else quote[:87] + "…"
    return f"🧠 Por tu nota «{quote}»: {what}. {proposal.reason}"


def undo(session: Session, user: User, change_id: Any) -> str:
    """Undo one change of this person; the text to answer with."""

    change = session.get(PreferenceChange, change_id)
    if change is None or change.user_id != user.id:
        return "No encuentro ese cambio."
    if change.status == "UNDONE":
        return "Ese cambio ya estaba deshecho."
    learned.undo_change(session, user, change.kind, change.value.get("value"))
    change.status, change.undone_at = "UNDONE", datetime.now(UTC)
    session.flush()
    return "Hecho, he deshecho ese cambio."
