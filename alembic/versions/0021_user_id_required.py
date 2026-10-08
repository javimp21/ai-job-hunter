"""Multiuser hardening: user_id is required on every per-person table and outreach uniqueness is per user.

Rows still without a user (none in production; 0018 filled them) go to the owner first. The four partial unique indexes
of outreaches start with user_id, so two people can each have an active outreach to the same contact or job.

Revision ID: 0021_user_id_required
Revises: 0020_onboarding
Create Date: 2026-10-09
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0021_user_id_required"
down_revision: Union[str, None] = "0020_onboarding"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PER_USER_TABLES = (
    "job_evaluations",
    "job_reviews",
    "opportunity_notifications",
    "applications",
    "outreaches",
    "connection_requests",
    "report_deliveries",
    "job_feedback_notes",
)
_ACTIVE = "'DRAFT', 'APPROVED', 'SENT', 'REPLIED'"
# name -> (columns, where)
OUTREACH_INDEXES = {
    "uq_outreach_active_job_contact_purpose": (
        ("job_id", "contact_id", "purpose"), f"job_id IS NOT NULL AND contact_id IS NOT NULL AND status IN ({_ACTIVE})"
    ),
    "uq_outreach_active_job_without_contact_purpose": (
        ("job_id", "purpose"), f"job_id IS NOT NULL AND contact_id IS NULL AND status IN ({_ACTIVE})"
    ),
    "uq_outreach_active_company_contact_purpose": (
        ("company_id", "contact_id", "channel", "purpose"), f"job_id IS NULL AND contact_id IS NOT NULL AND status IN ({_ACTIVE})"
    ),
    "uq_outreach_active_company_without_contact_purpose": (
        ("company_id", "channel", "purpose"), f"job_id IS NULL AND contact_id IS NULL AND status IN ({_ACTIVE})"
    ),
}


def _recreate_outreach_indexes(*, per_user: bool) -> None:
    for name, (columns, where) in OUTREACH_INDEXES.items():
        op.drop_index(name, table_name="outreaches")
        op.create_index(
            name, "outreaches", (["user_id"] if per_user else []) + list(columns), unique=True,
            sqlite_where=sa.text(where), postgresql_where=sa.text(where),
        )


def upgrade() -> None:
    flag = "true" if op.get_bind().dialect.name == "postgresql" else "1"
    for table in PER_USER_TABLES:
        op.execute(
            f"UPDATE {table} SET user_id = (SELECT id FROM users WHERE is_owner = {flag} LIMIT 1) "
            f"WHERE user_id IS NULL AND EXISTS (SELECT 1 FROM users WHERE is_owner = {flag})"
        )
        with op.batch_alter_table(table) as batch:
            batch.alter_column("user_id", existing_type=sa.Uuid(), nullable=False)
    _recreate_outreach_indexes(per_user=True)


def downgrade() -> None:
    _recreate_outreach_indexes(per_user=False)
    for table in PER_USER_TABLES:
        with op.batch_alter_table(table) as batch:
            batch.alter_column("user_id", existing_type=sa.Uuid(), nullable=True)
