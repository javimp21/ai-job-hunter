"""Sign-up by invitation: an ONBOARDING user status, the draft state of the conversation, and invitations.

Revision ID: 0020_onboarding
Revises: 0019_per_user_uniqueness
Create Date: 2026-10-08
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0020_onboarding"
down_revision: Union[str, None] = "0019_per_user_uniqueness"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD = "status IN ('ACTIVE', 'PAUSED', 'TRIAL_ENDED', 'DELETED')"
NEW = "status IN ('ONBOARDING', 'ACTIVE', 'PAUSED', 'TRIAL_ENDED', 'DELETED')"


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("onboarding", sa.JSON(), nullable=True))
        batch.drop_constraint("ck_users_status", type_="check")
        batch.create_check_constraint("ck_users_status", NEW)
    op.create_table(
        "invitations",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=16), nullable=False),
        sa.Column("created_by_user_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_by_user_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["used_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_invitations_code"),
    )


def downgrade() -> None:
    op.drop_table("invitations")
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("ck_users_status", type_="check")
        batch.create_check_constraint("ck_users_status", OLD)
        batch.drop_column("onboarding")
