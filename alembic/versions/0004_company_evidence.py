"""Add source-backed evidence associated with companies.

Revision ID: 0004_company_evidence
Revises: 0003_cross_source_urls
Create Date: 2026-09-24
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004_company_evidence"
down_revision: Union[str, None] = "0003_cross_source_urls"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "company_evidence",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=100), nullable=False),
        sa.Column("source_key", sa.String(length=512), nullable=False),
        sa.Column("source_url", sa.String(length=2048), nullable=True),
        sa.Column("external_identifier", sa.String(length=512), nullable=True),
        sa.Column("evidence_type", sa.String(length=100), nullable=False),
        sa.Column("structured_data", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("raw_metadata", sa.JSON(), nullable=True),
        sa.Column("discovered_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider", "evidence_type", "source_key", name="uq_company_evidence_provider_type_key"
        ),
    )
    op.create_index("ix_company_evidence_company_id", "company_evidence", ["company_id"], unique=False)
    op.create_index("ix_company_evidence_provider", "company_evidence", ["provider"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_company_evidence_provider", table_name="company_evidence")
    op.drop_index("ix_company_evidence_company_id", table_name="company_evidence")
    op.drop_table("company_evidence")
