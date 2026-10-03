"""Add monitored company boards with an explicit review lifecycle.

Revision ID: 0009_monitored_sources
Revises: 0008_opportunity_notifications
Create Date: 2026-10-03
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0009_monitored_sources"
down_revision: Union[str, None] = "0008_opportunity_notifications"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "monitored_sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("identifier", sa.String(length=512), nullable=False),
        sa.Column("identifier_key", sa.String(length=512), nullable=False),
        sa.Column("region", sa.String(length=32), nullable=True),
        sa.Column("region_key", sa.String(length=32), server_default="", nullable=False),
        sa.Column("careers_url", sa.String(length=2048), nullable=True),
        sa.Column("state", sa.String(length=16), server_default="REVIEW_SOURCE", nullable=False),
        sa.Column("state_reason", sa.Text(), nullable=True),
        sa.Column("state_changed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("origin", sa.String(length=40), nullable=False),
        sa.Column("last_fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_fetch_status", sa.String(length=16), nullable=True),
        sa.Column("last_fetch_error", sa.String(length=100), nullable=True),
        sa.Column("last_job_count", sa.Integer(), nullable=True),
        sa.Column("consecutive_failures", sa.Integer(), server_default="0", nullable=False),
        sa.Column("preview_stats", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "state IN ('REVIEW_SOURCE', 'ACTIVE', 'PAUSED', 'REJECTED')",
            name="ck_monitored_sources_state",
        ),
        sa.CheckConstraint("consecutive_failures >= 0", name="ck_monitored_sources_failures"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "identifier_key", "region_key", name="uq_monitored_source_board"),
    )
    op.create_index(
        "ix_monitored_sources_state_fetched",
        "monitored_sources",
        ["state", "last_fetched_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_monitored_sources_state_fetched", table_name="monitored_sources")
    op.drop_table("monitored_sources")
