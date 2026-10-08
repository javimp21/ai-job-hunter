"""Multiuser step 4: the uniqueness of per-person rows becomes per user.

A vote, an application, an evaluation or a notification is unique per (user, job...) instead of per job, so two people
can each have theirs. Rows without a user keep the old rule (a second partial unique index), so a database with no
users behaves exactly as before.

Revision ID: 0019_per_user_uniqueness
Revises: 0018_user_id_backfill
Create Date: 2026-10-08
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0019_per_user_uniqueness"
down_revision: Union[str, None] = "0018_user_id_backfill"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# table -> (old constraint name, columns, new index base name)
RULES = {
    "job_reviews": ("uq_job_reviews_job_id", ("job_id",), "uq_job_reviews_job"),
    "applications": ("uq_applications_job_id", ("job_id",), "uq_applications_job"),
    "job_evaluations": (
        "uq_job_evaluations_job_fingerprint", ("job_id", "evaluation_fingerprint"), "uq_job_evaluations_job_fingerprint"
    ),
    "opportunity_notifications": (
        "uq_opportunity_notifications_eval_channel",
        ("job_id", "evaluation_fingerprint", "channel"),
        "uq_opportunity_notifications_eval_channel",
    ),
}


def upgrade() -> None:
    for table, (old, columns, base) in RULES.items():
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(old, type_="unique")
        op.create_index(
            f"{base}_user", table, ["user_id", *columns], unique=True,
            sqlite_where=sa.text("user_id IS NOT NULL"), postgresql_where=sa.text("user_id IS NOT NULL"),
        )
        op.create_index(
            f"{base}_unowned", table, list(columns), unique=True,
            sqlite_where=sa.text("user_id IS NULL"), postgresql_where=sa.text("user_id IS NULL"),
        )


def downgrade() -> None:
    for table, (old, columns, base) in RULES.items():
        op.drop_index(f"{base}_unowned", table_name=table)
        op.drop_index(f"{base}_user", table_name=table)
        with op.batch_alter_table(table) as batch:
            batch.create_unique_constraint(old, list(columns))
