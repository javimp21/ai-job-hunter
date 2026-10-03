"""Store why a job was saved or dismissed (feedback for ranking).

Revision ID: 0011_job_review_reason
Revises: 0010_job_source_last_seen
Create Date: 2026-10-04
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0011_job_review_reason"
down_revision: Union[str, None] = "0010_job_source_last_seen"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("job_reviews", sa.Column("reason", sa.String(length=40), nullable=True))
    op.add_column("job_reviews", sa.Column("reason_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("job_reviews", "reason_at")
    op.drop_column("job_reviews", "reason")
