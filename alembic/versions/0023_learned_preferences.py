"""What a person's opinions taught the alerts: a learned-preferences column and the undoable change log.

Revision ID: 0023_learned_preferences
Revises: 0022_usage_and_cv_text
Create Date: 2026-10-09
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0023_learned_preferences"
down_revision: Union[str, None] = "0022_usage_and_cv_text"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("user_profiles", sa.Column("learned", sa.JSON(), nullable=True))
    op.create_table(
        "preference_changes",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("undone_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_preference_changes_user_status", "preference_changes", ["user_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_preference_changes_user_status", table_name="preference_changes")
    op.drop_table("preference_changes")
    with op.batch_alter_table("user_profiles") as batch:
        batch.drop_column("learned")
