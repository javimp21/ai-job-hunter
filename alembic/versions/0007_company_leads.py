"""Persist company leads and their discovery provenance.

Revision ID: 0007_company_leads
Revises: 0006_outreach_persistence
Create Date: 2026-09-30
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0007_company_leads"
down_revision: Union[str, None] = "0006_outreach_persistence"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "company_leads",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_name", sa.String(length=255), nullable=False),
        sa.Column("normalized_name", sa.String(length=255), nullable=False),
        sa.Column("domain_key", sa.String(length=255), server_default="", nullable=False),
        sa.Column("website_url", sa.String(length=2048), nullable=True),
        sa.Column("careers_url", sa.String(length=2048), nullable=True),
        sa.Column("source_type", sa.String(length=100), nullable=False),
        sa.Column("source_label", sa.String(length=255), nullable=False),
        sa.Column("source_url", sa.String(length=2048), nullable=True),
        sa.Column("location_hint", sa.String(length=255), nullable=True),
        sa.Column("hiring_hint", sa.String(length=512), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("source_provenance", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("status", sa.String(length=32), server_default="NEW", nullable=False),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("company_id", sa.Uuid(), nullable=True),
        sa.Column("ats_provider", sa.String(length=32), nullable=True),
        sa.Column("ats_identifier", sa.String(length=512), nullable=True),
        sa.Column("ats_region", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("normalized_name", "domain_key", name="uq_company_lead_name_domain"),
    )
    op.create_index("ix_company_leads_status", "company_leads", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_company_leads_status", table_name="company_leads")
    op.drop_table("company_leads")
