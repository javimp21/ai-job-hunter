"""Who is acting: new per-person rows get that user, and reads only see that user's rows (docs/MULTIUSER_DESIGN.md).

Two hooks on every ORM session replace edits to dozens of queries and constructors:

* before a flush, a new row of a ``UserOwnedMixin`` model without a ``user_id`` gets the acting user;
* a SELECT/UPDATE/DELETE gets ``user_id = <acting user>`` added for those models while a user is acting.

With no user acting, reads are unfiltered (maintenance tasks, today's single-user CLI before an owner exists) and new rows
go to the only user there is. Once several users exist an unnamed actor is an error, so a forgotten ``acting_as`` can
never mix two people's data.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import UUID

from sqlalchemy import event, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, with_loader_criteria

from ai_job_hunter.models.mixins import UserOwnedMixin
from ai_job_hunter.models.user import User, UserStatus

_current: ContextVar[UUID | None] = ContextVar("current_user_id", default=None)
SKIP_USER_SCOPE = "skip_user_scope"  # execution option: a maintenance query that must see every user


class UserContextError(RuntimeError):
    """Several users exist and nobody said which one is acting."""


def current_user_id() -> UUID | None:
    return _current.get()


@contextmanager
def acting_as(user_id: UUID) -> Iterator[None]:
    token = _current.set(user_id)
    try:
        yield
    finally:
        _current.reset(token)


def activate_owner(engine: Engine) -> UUID | None:
    """Make the owner the acting user of this process (the personal CLI and bot); no owner, no change."""

    try:
        with Session(engine) as session:
            owner_id = session.scalar(select(User.id).where(User.is_owner.is_(True)))
    except Exception:  # noqa: BLE001 - a database not migrated yet (no users table) or unreachable: act as nobody
        return None
    if owner_id is not None:
        _current.set(owner_id)
    return owner_id


def _default_user_id(session: Session) -> UUID | None:
    cached = session.info.get("default_user_id")
    if cached is not None:
        return cached
    ids = list(session.scalars(select(User.id).where(User.status != UserStatus.DELETED.value)))
    if not ids:
        return None  # no users yet: the row stays unowned, as before the multiuser work
    if len(ids) > 1:
        raise UserContextError("Several users exist: wrap the work in acting_as(user_id).")
    session.info["default_user_id"] = ids[0]
    return ids[0]


@event.listens_for(Session, "before_flush")
def _own_new_rows(session: Session, flush_context, instances) -> None:  # noqa: ANN001
    pending = [row for row in session.new if isinstance(row, UserOwnedMixin) and row.user_id is None]
    if not pending:
        return
    with session.no_autoflush:
        user_id = current_user_id() or _default_user_id(session)
    if user_id is None:
        return
    for row in pending:
        row.user_id = user_id


@event.listens_for(Session, "do_orm_execute")
def _only_this_users_rows(execute_state) -> None:  # noqa: ANN001
    user_id = current_user_id()
    if user_id is None or execute_state.execution_options.get(SKIP_USER_SCOPE):
        return
    if not (execute_state.is_select or execute_state.is_update or execute_state.is_delete):
        return
    execute_state.statement = execute_state.statement.options(
        with_loader_criteria(UserOwnedMixin, lambda cls: cls.user_id == user_id, include_aliases=True)
    )
