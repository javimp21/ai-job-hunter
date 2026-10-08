"""Reusable columns shared by persisted entities."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Uuid, func
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
