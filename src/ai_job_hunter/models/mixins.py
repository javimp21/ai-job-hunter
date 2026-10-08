"""Reusable columns shared by persisted entities."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Index, Uuid, func, text
from sqlalchemy.orm import Mapped, mapped_column


class TimestampMixin:
    """Creation and modification times managed by the database."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class UserOwnedMixin:
    """The person a row belongs to (docs/MULTIUSER_DESIGN.md).

    Nullable while the code still writes without it: migration 0017 added the column and filled it with the owner; the
    "contract" step makes it required once every writer passes the user.
    """

    user_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )


def _per_user_unique(base: str, *columns: str) -> tuple[Index, Index]:
    """Unique per (user, columns); rows with no user keep the old rule (see migration 0019)."""

    return (
        Index(f"{base}_user", "user_id", *columns, unique=True,
              sqlite_where=text("user_id IS NOT NULL"), postgresql_where=text("user_id IS NOT NULL")),
        Index(f"{base}_unowned", *columns, unique=True,
              sqlite_where=text("user_id IS NULL"), postgresql_where=text("user_id IS NULL")),
    )
