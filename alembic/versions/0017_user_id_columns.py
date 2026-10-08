"""Multiuser step 2b: a nullable user_id on every per-person table, filled with the owner (nothing reads it yet).

Revision ID: 0017_user_id_columns
Revises: 0016_job_feedback_notes
Create Date: 2026-10-08
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0017_user_id_columns"
down_revision: Union[str, None] = "0016_job_feedback_notes"
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
    for table in PER_USER_TABLES:
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("user_id", sa.Uuid(as_uuid=True), nullable=True))
            batch.create_foreign_key(f"fk_{table}_user_id", "users", ["user_id"], ["id"], ondelete="RESTRICT")
    # Rows that exist now belong to the owner. A database without an owner (a fresh one) has nothing to fill.
    for table in PER_USER_TABLES:
        op.execute(
            f"UPDATE {table} SET user_id = (SELECT id FROM users WHERE is_owner = {_true()} LIMIT 1) "
            f"WHERE user_id IS NULL AND EXISTS (SELECT 1 FROM users WHERE is_owner = {_true()})"
        )


def downgrade() -> None:
    for table in PER_USER_TABLES:
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(f"fk_{table}_user_id", type_="foreignkey")
            batch.drop_column("user_id")


def _true() -> str:
    return "true" if op.get_bind().dialect.name == "postgresql" else "1"
