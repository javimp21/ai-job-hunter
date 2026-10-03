"""Track when each job source was last seen and when it was found closed.

Revision ID: 0010_job_source_last_seen
Revises: 0009_monitored_sources
Create Date: 2026-10-04
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0010_job_source_last_seen"
down_revision: Union[str, None] = "0009_monitored_sources"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("job_sources", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("job_sources", sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True))
    # Existing rows were last seen at least when they were discovered.
    op.execute("UPDATE job_sources SET last_seen_at = discovered_at WHERE last_seen_at IS NULL")


def downgrade() -> None:
    op.drop_column("job_sources", "closed_at")
    op.drop_column("job_sources", "last_seen_at")
