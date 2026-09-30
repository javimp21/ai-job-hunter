"""Add the notification delivery ledger.

Revision ID: 0008_opportunity_notifications
Revises: 0007_company_leads
Create Date: 2026-09-30
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0008_opportunity_notifications"
down_revision: Union[str, None] = "0007_company_leads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "opportunity_notifications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("evaluation_fingerprint", sa.String(length=128), nullable=False),
        sa.Column("channel", sa.String(length=20), nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("dispatch_started", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("dispatch_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retryable", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("failure_reason", sa.String(length=100), nullable=True),
        sa.Column("suppression_reason", sa.String(length=100), nullable=True),
        sa.Column("provider_message_id", sa.String(length=100), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('PENDING', 'SENT', 'FAILED', 'SUPPRESSED')",
            name="ck_opportunity_notifications_status",
        ),
        sa.CheckConstraint(
            "decision IN ('APPLY', 'REVIEW', 'SKIP')",
            name="ck_opportunity_notifications_decision",
        ),
        sa.CheckConstraint(
            "channel IN ('TELEGRAM')", name="ck_opportunity_notifications_channel"
        ),
        sa.CheckConstraint(
            "attempt_count >= 0", name="ck_opportunity_notifications_attempt_count"
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "job_id",
            "evaluation_fingerprint",
            "channel",
            name="uq_opportunity_notifications_eval_channel",
        ),
    )
    op.create_index(
        "ix_opportunity_notifications_status_created",
        "opportunity_notifications",
        ["status", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_opportunity_notifications_status_created",
        table_name="opportunity_notifications",
    )
    op.drop_table("opportunity_notifications")
