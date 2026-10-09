"""The bot's question after a vote is remembered in the database, so an opinion written after a restart is still stored.

Revision ID: 0024_feedback_prompts
Revises: 0023_learned_preferences
Create Date: 2026-10-09
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0024_feedback_prompts"
down_revision: Union[str, None] = "0023_learned_preferences"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "feedback_prompts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("message_id", sa.BigInteger(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("uq_feedback_prompts_user_message", "feedback_prompts", ["user_id", "message_id"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_feedback_prompts_user_message", table_name="feedback_prompts")
    op.drop_table("feedback_prompts")
