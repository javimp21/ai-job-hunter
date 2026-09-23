"""Store normalized details on source occurrences.

Revision ID: 0002_source_fields
Revises: 0001_initial
Create Date: 2026-09-24
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_source_fields"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("job_sources", sa.Column("salary_min", sa.Numeric(14, 2), nullable=True))
    op.add_column("job_sources", sa.Column("salary_max", sa.Numeric(14, 2), nullable=True))
    op.add_column("job_sources", sa.Column("salary_currency", sa.String(length=3), nullable=True))
    op.add_column("job_sources", sa.Column("salary_period", sa.String(length=20), nullable=True))
    op.add_column("job_sources", sa.Column("employment_type", sa.String(length=30), nullable=True))
    op.add_column("job_sources", sa.Column("remote_policy", sa.String(length=20), nullable=True))
    op.add_column("job_sources", sa.Column("remote_eligibility", sa.String(length=30), nullable=True))
    op.add_column("job_sources", sa.Column("published_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("job_sources", "published_at")
    op.drop_column("job_sources", "remote_eligibility")
    op.drop_column("job_sources", "remote_policy")
    op.drop_column("job_sources", "employment_type")
    op.drop_column("job_sources", "salary_period")
    op.drop_column("job_sources", "salary_currency")
    op.drop_column("job_sources", "salary_max")
    op.drop_column("job_sources", "salary_min")
