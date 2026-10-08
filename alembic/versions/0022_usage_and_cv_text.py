"""Letters and interview briefs for other people: a stored experience summary, a usage ledger and the written documents.

Revision ID: 0022_usage_and_cv_text
Revises: 0021_user_id_required
Create Date: 2026-10-09
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0022_usage_and_cv_text"
down_revision: Union[str, None] = "0021_user_id_required"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("user_profiles", sa.Column("cv_text", sa.Text(), nullable=True))
    op.create_table(
        "usage_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("used_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_usage_events_user_kind_created", "usage_events", ["user_id", "kind", "created_at"])
    op.create_table(
        "generated_documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("language", sa.String(length=5), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("model", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_generated_documents_user_job_kind_language", "generated_documents",
        ["user_id", "job_id", "kind", "language"], unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_generated_documents_user_job_kind_language", table_name="generated_documents")
    op.drop_table("generated_documents")
    op.drop_index("ix_usage_events_user_kind_created", table_name="usage_events")
    op.drop_table("usage_events")
    with op.batch_alter_table("user_profiles") as batch:
        batch.drop_column("cv_text")
