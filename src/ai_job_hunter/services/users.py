"""Users and their profiles (multiuser step 2a, docs/MULTIUSER_DESIGN.md): the runtime does not read them yet."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ai_job_hunter.candidates.profile import CandidateConfig, load_candidate_config
from ai_job_hunter.models.user import User, UserProfile, UserStatus


def get_owner(session: Session) -> User | None:
    return session.scalar(select(User).where(User.is_owner.is_(True)))


def ensure_owner(
    session: Session, *, telegram_chat_id: str | None = None, language: str = "es", timezone: str = "Europe/Madrid"
) -> User:
    """The owner row, created on first use. There is exactly one owner."""

    owner = get_owner(session)
    if owner is not None:
        return owner
    owner = User(
        telegram_chat_id=telegram_chat_id, language=language, timezone=timezone,
        status=UserStatus.ACTIVE.value, is_owner=True,
    )
    session.add(owner)
    session.flush()
    return owner


def save_profile(
    session: Session, user: User, config: CandidateConfig, *, cv_text: str | None = None
) -> tuple[UserProfile, bool]:
    """Create or replace the user's profile; returns it and whether anything changed.

    ``cv_text`` (the experience summary) is replaced only when given, so editing preferences never drops it.
    """

    payload = config.model_dump(mode="json")
    profile = session.scalar(select(UserProfile).where(UserProfile.user_id == user.id))
    if profile is None:
        profile = UserProfile(user_id=user.id, sector=config.preferences.sector, config=payload, cv_text=cv_text)
        session.add(profile)
        session.flush()
        return profile, True
    if profile.config == payload and profile.sector == config.preferences.sector and cv_text in (None, profile.cv_text):
        return profile, False
    profile.sector = config.preferences.sector
    profile.config = payload
    if cv_text is not None:
        profile.cv_text = cv_text
    session.flush()
    return profile, True


def load_profile(session: Session, user: User) -> CandidateConfig | None:
    from ai_job_hunter.services.learned import merge_learned

    profile = session.scalar(select(UserProfile).where(UserProfile.user_id == user.id))
    if profile is None:
        return None
    return merge_learned(CandidateConfig.model_validate(profile.config), profile.learned)


def import_owner_profile(session: Session, path: str | Path) -> tuple[User, UserProfile, bool]:
    """Store the local candidate file as the owner's profile (idempotent)."""

    config = load_candidate_config(path)
    owner = ensure_owner(session)
    profile, changed = save_profile(session, owner, config)
    return owner, profile, changed
