"""Persist cross-source URL and company identity evidence.

Revision ID: 0003_cross_source_urls
Revises: 0002_source_fields
Create Date: 2026-09-24
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_cross_source_urls"
down_revision: Union[str, None] = "0002_source_fields"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("job_sources", sa.Column("canonical_url", sa.String(length=2048), nullable=True))
    op.add_column("job_sources", sa.Column("apply_url", sa.String(length=2048), nullable=True))
    op.add_column("job_sources", sa.Column("company_website", sa.String(length=2048), nullable=True))


def downgrade() -> None:
    op.drop_column("job_sources", "company_website")
    op.drop_column("job_sources", "apply_url")
    op.drop_column("job_sources", "canonical_url")
