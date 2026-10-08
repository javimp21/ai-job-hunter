"""Multiuser step 3: fill again the rows created since 0017 without a user (the owner's), before reads are scoped.

Revision ID: 0018_user_id_backfill
Revises: 0017_user_id_columns
Create Date: 2026-10-08
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0018_user_id_backfill"
down_revision: Union[str, None] = "0017_user_id_columns"
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


def upgrade() -> None:
    flag = "true" if op.get_bind().dialect.name == "postgresql" else "1"
    for table in PER_USER_TABLES:
        op.execute(
            f"UPDATE {table} SET user_id = (SELECT id FROM users WHERE is_owner = {flag} LIMIT 1) "
            f"WHERE user_id IS NULL AND EXISTS (SELECT 1 FROM users WHERE is_owner = {flag})"
        )


def downgrade() -> None:
    """Nothing to undo: the rows keep their owner, which 0017 already allowed."""
