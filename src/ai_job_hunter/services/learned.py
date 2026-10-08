"""What a person's opinions taught the alerts, kept in ``user_profiles.learned`` and merged over their answers.

Seven kinds of change exist; each is one small, understandable edit and each can be undone:
excluded title terms, excluded companies, excluded required languages, "more like this" roles, preferred technologies,
quiet hours and a pause until a date. The answers given at sign-up (``config``) are never rewritten by this module.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_job_hunter.candidates.profile import CandidateConfig
from ai_job_hunter.models.user import User, UserProfile

# change kind -> key of the list in ``learned``
LIST_KINDS = {
    "exclude_title_term": "excluded_title_terms",
    "exclude_company": "excluded_companies",
    "exclude_language": "excluded_languages",
    "more_like_this": "more_roles",
    "prefer_technology": "preferred_technologies",
}
KINDS = (*LIST_KINDS, "quiet_hours", "pause_until")


def merge_learned(config: CandidateConfig, learned: dict[str, Any] | None) -> CandidateConfig:
    """The person's answers plus what was learned (the answers stay as they are; lists only grow)."""

    if not learned:
        return config
    data = config.model_dump(mode="json")
    preferences = data["preferences"]

    def union(target: str, extra: list[str]) -> None:
        preferences[target] = list(dict.fromkeys([*preferences.get(target, []), *extra]))

    for field in ("excluded_title_terms", "excluded_companies", "excluded_languages", "preferred_technologies"):
        union(field, list(learned.get(field) or []))
    union("preferred_roles", list(learned.get("more_roles") or []))
    quiet = learned.get("quiet_hours")
    if isinstance(quiet, list) and len(quiet) == 2:
        preferences["quiet_hours_start"], preferences["quiet_hours_end"] = quiet
    if learned.get("paused_until"):
        preferences["paused_until"] = learned["paused_until"]
    return CandidateConfig.model_validate(data)


def _profile(session: Session, user: User) -> UserProfile | None:
    return session.scalar(select(UserProfile).where(UserProfile.user_id == user.id))


def apply_change(session: Session, user: User, kind: str, value: Any) -> bool:
    """Add one learned change; False when there is nothing to add (already there, no profile, unusable value)."""

    profile = _profile(session, user)
    if profile is None or kind not in KINDS:
        return False
    learned = dict(profile.learned or {})
    if kind in LIST_KINDS:
        if not isinstance(value, str) or not value.strip():
            return False
        key = LIST_KINDS[kind]
        items = list(learned.get(key) or [])
        if value.strip().casefold() in {item.casefold() for item in items}:
            return False
        learned[key] = [*items, value.strip()]
    elif kind == "quiet_hours":
        start, end = (value or {}).get("start"), (value or {}).get("end")
        if not all(isinstance(hour, int) and not isinstance(hour, bool) and 0 <= hour <= 23 for hour in (start, end)) or start == end:
            return False
        learned["quiet_hours"] = [start, end]
    else:
        try:
            learned["paused_until"] = date.fromisoformat(str(value)).isoformat()
        except ValueError:
            return False
    profile.learned = learned
    session.flush()
    return True


def undo_change(session: Session, user: User, kind: str, value: Any) -> None:
    profile = _profile(session, user)
    if profile is None or not profile.learned:
        return
    learned = dict(profile.learned)
    if kind in LIST_KINDS:
        key = LIST_KINDS[kind]
        learned[key] = [item for item in learned.get(key) or [] if str(item).casefold() != str(value).strip().casefold()]
    elif kind == "quiet_hours":
        learned.pop("quiet_hours", None)
    else:
        learned.pop("paused_until", None)
    profile.learned = learned
    session.flush()


def with_owner_learned(session: Session, candidate: CandidateConfig) -> CandidateConfig:
    """The owner runs on ``candidate.local.json``; what was learned from their opinions is laid over it."""

    owner_profile = session.scalar(select(UserProfile).join(User, User.id == UserProfile.user_id).where(User.is_owner.is_(True)))
    return merge_learned(candidate, owner_profile.learned) if owner_profile is not None else candidate
