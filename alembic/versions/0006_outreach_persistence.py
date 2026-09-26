"""Add company contacts, outreach drafts, and lifecycle history.

Revision ID: 0006_outreach_persistence
Revises: 0005_opportunity_workflow
Create Date: 2026-09-26
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0006_outreach_persistence"
down_revision: Union[str, None] = "0005_opportunity_workflow"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_CONTACT_TYPES = "'RECRUITER', 'TALENT', 'HIRING_MANAGER', 'ENGINEERING_MANAGER', 'ENGINEER', 'FOUNDER', 'OTHER'"
_PURPOSES = "'REFERRAL', 'RECRUITER_INTRO', 'HIRING_MANAGER_INTRO', 'JOB_INTEREST', 'COLD_OUTREACH'"
_CHANNELS = "'EMAIL', 'LINKEDIN', 'OTHER'"
_STATUSES = "'DRAFT', 'APPROVED', 'SENT', 'REPLIED', 'DECLINED', 'NO_RESPONSE', 'CANCELLED'"
_EVENT_TYPES = "'CREATED', 'DRAFT', 'APPROVED', 'SENT', 'REPLIED', 'DECLINED', 'NO_RESPONSE', 'CANCELLED', 'NOTE_ADDED'"
_ACTIVE_STATUSES = "'DRAFT', 'APPROVED', 'SENT', 'REPLIED'"


def upgrade() -> None:
    op.create_table(
        "contacts",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("contact_type", sa.String(length=32), nullable=False),
        sa.Column("linkedin_url", sa.String(length=2048), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("source_provider", sa.String(length=100), nullable=True),
        sa.Column("external_id", sa.String(length=512), nullable=True),
        sa.Column("source_url", sa.String(length=2048), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("raw_metadata", sa.JSON(), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(f"contact_type IN ({_CONTACT_TYPES})", name="ck_contacts_contact_type"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_contacts_company_id", "contacts", ["company_id"])
    op.create_index("ix_contacts_company_email", "contacts", ["company_id", "email"])
    op.create_index("ix_contacts_company_linkedin", "contacts", ["company_id", "linkedin_url"])
    op.create_index(
        "ix_contacts_source_identity", "contacts", ["company_id", "source_provider", "external_id"]
    )

    op.create_table(
        "outreaches",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=True),
        sa.Column("contact_id", sa.Uuid(), nullable=True),
        sa.Column("application_id", sa.Uuid(), nullable=True),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("channel", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="DRAFT", nullable=False),
        sa.Column("subject", sa.String(length=500), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("recipient_contact_type", sa.String(length=32), nullable=True),
        sa.Column("recommendation", sa.String(length=32), nullable=True),
        sa.Column("rationale", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(f"purpose IN ({_PURPOSES})", name="ck_outreaches_purpose"),
        sa.CheckConstraint(f"channel IN ({_CHANNELS})", name="ck_outreaches_channel"),
        sa.CheckConstraint(f"status IN ({_STATUSES})", name="ck_outreaches_status"),
        sa.CheckConstraint(
            f"recipient_contact_type IS NULL OR recipient_contact_type IN ({_CONTACT_TYPES})",
            name="ck_outreaches_recipient_contact_type",
        ),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_outreaches_company_status", "outreaches", ["company_id", "status"])
    op.create_index("ix_outreaches_job_id", "outreaches", ["job_id"])
    op.create_index("ix_outreaches_contact_id", "outreaches", ["contact_id"])
    op.create_index("ix_outreaches_application_id", "outreaches", ["application_id"])

    # Split indexes avoid NULL uniqueness gaps for optional job/contact values.
    _create_active_duplicate_indexes()

    op.create_table(
        "outreach_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("outreach_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("from_status", sa.String(length=20), nullable=True),
        sa.Column("to_status", sa.String(length=20), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(f"event_type IN ({_EVENT_TYPES})", name="ck_outreach_events_event_type"),
        sa.CheckConstraint(
            f"from_status IS NULL OR from_status IN ({_STATUSES})",
            name="ck_outreach_events_from_status",
        ),
        sa.CheckConstraint(f"to_status IN ({_STATUSES})", name="ck_outreach_events_to_status"),
        sa.ForeignKeyConstraint(["outreach_id"], ["outreaches.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_outreach_events_outreach_occurred", "outreach_events", ["outreach_id", "occurred_at"]
    )


def _create_active_duplicate_indexes() -> None:
    op.create_index(
        "uq_outreach_active_job_contact_purpose",
        "outreaches",
        ["job_id", "contact_id", "purpose"],
        unique=True,
        sqlite_where=sa.text(
            f"job_id IS NOT NULL AND contact_id IS NOT NULL AND status IN ({_ACTIVE_STATUSES})"
        ),
        postgresql_where=sa.text(
            f"job_id IS NOT NULL AND contact_id IS NOT NULL AND status IN ({_ACTIVE_STATUSES})"
        ),
    )
    op.create_index(
        "uq_outreach_active_job_without_contact_purpose",
        "outreaches",
        ["job_id", "purpose"],
        unique=True,
        sqlite_where=sa.text(
            f"job_id IS NOT NULL AND contact_id IS NULL AND status IN ({_ACTIVE_STATUSES})"
        ),
        postgresql_where=sa.text(
            f"job_id IS NOT NULL AND contact_id IS NULL AND status IN ({_ACTIVE_STATUSES})"
        ),
    )
    op.create_index(
        "uq_outreach_active_company_contact_purpose",
        "outreaches",
        ["company_id", "contact_id", "purpose"],
        unique=True,
        sqlite_where=sa.text(
            f"job_id IS NULL AND contact_id IS NOT NULL AND status IN ({_ACTIVE_STATUSES})"
        ),
        postgresql_where=sa.text(
            f"job_id IS NULL AND contact_id IS NOT NULL AND status IN ({_ACTIVE_STATUSES})"
        ),
    )
    op.create_index(
        "uq_outreach_active_company_without_contact_purpose",
        "outreaches",
        ["company_id", "purpose"],
        unique=True,
        sqlite_where=sa.text(
            f"job_id IS NULL AND contact_id IS NULL AND status IN ({_ACTIVE_STATUSES})"
        ),
        postgresql_where=sa.text(
            f"job_id IS NULL AND contact_id IS NULL AND status IN ({_ACTIVE_STATUSES})"
        ),
    )


def downgrade() -> None:
    op.drop_index("ix_outreach_events_outreach_occurred", table_name="outreach_events")
    op.drop_table("outreach_events")
    for name in (
        "uq_outreach_active_company_without_contact_purpose",
        "uq_outreach_active_company_contact_purpose",
        "uq_outreach_active_job_without_contact_purpose",
        "uq_outreach_active_job_contact_purpose",
    ):
        op.drop_index(name, table_name="outreaches")
    op.drop_index("ix_outreaches_application_id", table_name="outreaches")
    op.drop_index("ix_outreaches_contact_id", table_name="outreaches")
    op.drop_index("ix_outreaches_job_id", table_name="outreaches")
    op.drop_index("ix_outreaches_company_status", table_name="outreaches")
    op.drop_table("outreaches")
    op.drop_index("ix_contacts_source_identity", table_name="contacts")
    op.drop_index("ix_contacts_company_linkedin", table_name="contacts")
    op.drop_index("ix_contacts_company_email", table_name="contacts")
    op.drop_index("ix_contacts_company_id", table_name="contacts")
    op.drop_table("contacts")
