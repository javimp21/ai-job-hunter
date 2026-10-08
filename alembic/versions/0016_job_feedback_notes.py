"""Add free-text feedback notes about alerts.

Revision ID: 0016_job_feedback_notes
Revises: 0015_users_and_profiles
Create Date: 2026-10-08
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0016_job_feedback_notes"
down_revision: Union[str, None] = "0015_users_and_profiles"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "job_feedback_notes",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("job_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("vote", sa.String(length=20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_job_feedback_notes_job_id", "job_feedback_notes", ["job_id"])


def downgrade() -> None:
    op.drop_index("ix_job_feedback_notes_job_id", table_name="job_feedback_notes")
    op.drop_table("job_feedback_notes")
