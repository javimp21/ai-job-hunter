"""Add the report delivery marker table (weekly Telegram report).

Revision ID: 0013_report_deliveries
Revises: 0012_notification_digest_channel
Create Date: 2026-10-04
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0013_report_deliveries"
down_revision: Union[str, None] = "0012_notification_digest_channel"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # A plain new table: no CHECK widening, so it behaves the same on SQLite
    # (offline migration tests) and PostgreSQL.
    op.create_table(
        "report_deliveries",
        sa.Column("id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provider_message_id", sa.String(length=100), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_report_deliveries_kind_sent", "report_deliveries", ["kind", "sent_at"])


def downgrade() -> None:
    op.drop_index("ix_report_deliveries_kind_sent", table_name="report_deliveries")
    op.drop_table("report_deliveries")
