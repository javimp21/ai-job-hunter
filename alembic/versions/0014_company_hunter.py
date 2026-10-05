"""Add the manual LinkedIn connection queue and per-channel company outreach uniqueness.

Revision ID: 0014_company_hunter
Revises: 0013_report_deliveries
Create Date: 2026-10-04
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0014_company_hunter"
down_revision: Union[str, None] = "0013_report_deliveries"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ACTIVE = "'DRAFT', 'APPROVED', 'SENT', 'REPLIED'"
_STATUSES = "'SUGGESTED', 'SENT', 'ACCEPTED', 'SKIPPED'"


def _company_indexes(*, with_channel: bool) -> None:
    # Indexes (unlike CHECK constraints) can be dropped and recreated on SQLite.
    for name in (
        "uq_outreach_active_company_contact_purpose",
        "uq_outreach_active_company_without_contact_purpose",
    ):
        op.drop_index(name, table_name="outreaches")
    channel = ["channel"] if with_channel else []
    op.create_index(
        "uq_outreach_active_company_contact_purpose",
        "outreaches",
        ["company_id", "contact_id", *channel, "purpose"],
        unique=True,
        sqlite_where=sa.text(f"job_id IS NULL AND contact_id IS NOT NULL AND status IN ({_ACTIVE})"),
        postgresql_where=sa.text(f"job_id IS NULL AND contact_id IS NOT NULL AND status IN ({_ACTIVE})"),
    )
    op.create_index(
        "uq_outreach_active_company_without_contact_purpose",
        "outreaches",
        ["company_id", *channel, "purpose"],
        unique=True,
        sqlite_where=sa.text(f"job_id IS NULL AND contact_id IS NULL AND status IN ({_ACTIVE})"),
        postgresql_where=sa.text(f"job_id IS NULL AND contact_id IS NULL AND status IN ({_ACTIVE})"),
    )


def upgrade() -> None:
    # An email draft and a LinkedIn DM draft for the same company are distinct records.
    _company_indexes(with_channel=True)
    op.create_table(
        "connection_requests",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("contact_id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=16), server_default="SUGGESTED", nullable=False),
        sa.Column("language", sa.String(length=2), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("grounding_post", sa.Text(), nullable=True),
        sa.Column("follow_up_draft", sa.Text(), nullable=True),
        sa.Column("telegram_message_id", sa.String(length=32), nullable=True),
        sa.Column("suggested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("skipped_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("skip_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(f"status IN ({_STATUSES})", name="ck_connection_requests_status"),
        sa.CheckConstraint("language IN ('es', 'en')", name="ck_connection_requests_language"),
        sa.CheckConstraint("length(note) <= 300", name="ck_connection_requests_note_length"),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_connection_requests_contact_status", "connection_requests", ["contact_id", "status"]
    )
    op.create_index(
        "ix_connection_requests_company_status", "connection_requests", ["company_id", "status"]
    )
    op.create_index("ix_connection_requests_suggested_at", "connection_requests", ["suggested_at"])


def downgrade() -> None:
    op.drop_index("ix_connection_requests_suggested_at", table_name="connection_requests")
    op.drop_index("ix_connection_requests_company_status", table_name="connection_requests")
    op.drop_index("ix_connection_requests_contact_status", table_name="connection_requests")
    op.drop_table("connection_requests")
    # Keep one active draft per company/purpose again: cancel the later channel duplicates first.
    op.execute(
        "UPDATE outreaches SET status = 'CANCELLED' WHERE job_id IS NULL "
        f"AND status IN ({_ACTIVE}) AND EXISTS (SELECT 1 FROM outreaches o2 "
        "WHERE o2.company_id = outreaches.company_id AND o2.purpose = outreaches.purpose "
        "AND o2.job_id IS NULL AND (o2.contact_id = outreaches.contact_id "
        "OR (o2.contact_id IS NULL AND outreaches.contact_id IS NULL)) "
        f"AND o2.status IN ({_ACTIVE}) AND o2.id < outreaches.id)"
    )
    _company_indexes(with_channel=False)
