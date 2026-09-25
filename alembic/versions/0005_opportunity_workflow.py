"""Persist versioned evaluations, human review state, and applications.

Revision ID: 0005_opportunity_workflow
Revises: 0004_company_evidence
Create Date: 2026-09-25
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005_opportunity_workflow"
down_revision: Union[str, None] = "0004_company_evidence"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_APPLICATION_STATUSES = "'DRAFT', 'APPLIED', 'INTERVIEW', 'OFFER', 'REJECTED', 'WITHDRAWN'"


def upgrade() -> None:
    op.add_column("job_sources", sa.Column("source_title", sa.String(length=255), nullable=True))
    op.add_column("job_sources", sa.Column("source_description", sa.Text(), nullable=True))
    op.add_column("job_sources", sa.Column("source_location", sa.String(length=255), nullable=True))
    op.execute(
        "UPDATE job_sources SET "
        "source_title = (SELECT jobs.title FROM jobs WHERE jobs.id = job_sources.job_id), "
        "source_description = (SELECT jobs.description FROM jobs WHERE jobs.id = job_sources.job_id), "
        "source_location = (SELECT jobs.location FROM jobs WHERE jobs.id = job_sources.job_id)"
    )

    op.create_table(
        "job_evaluations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("evaluation_fingerprint", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="PENDING", nullable=False),
        sa.Column("decision", sa.String(length=16), nullable=True),
        sa.Column("rubric_version", sa.String(length=100), nullable=False),
        sa.Column("policy_version", sa.String(length=100), nullable=False),
        sa.Column("engine_name", sa.String(length=100), nullable=False),
        sa.Column("engine_configuration", sa.String(length=255), nullable=True),
        sa.Column("model_version", sa.String(length=255), nullable=True),
        sa.Column("config_fingerprint", sa.String(length=128), nullable=False),
        sa.Column("deterministic_result", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("jev_signals", sa.JSON(), nullable=True),
        sa.Column("jev_reasons", sa.JSON(), nullable=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "status IN ('PENDING', 'EVALUATED')", name="ck_job_evaluations_status"
        ),
        sa.CheckConstraint(
            "decision IS NULL OR decision IN ('APPLY', 'REVIEW', 'SKIP')",
            name="ck_job_evaluations_decision",
        ),
        sa.CheckConstraint(
            "(status = 'PENDING' AND decision IS NULL AND evaluated_at IS NULL) OR "
            "(status = 'EVALUATED' AND decision IS NOT NULL AND evaluated_at IS NOT NULL)",
            name="ck_job_evaluations_completion_fields",
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "job_id", "evaluation_fingerprint", name="uq_job_evaluations_job_fingerprint"
        ),
    )
    op.create_index(
        "ix_job_evaluations_rubric_version", "job_evaluations", ["rubric_version"], unique=False
    )

    op.create_table(
        "job_reviews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("state", sa.String(length=20), server_default="NEW", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "state IN ('NEW', 'SEEN', 'SAVED', 'DISMISSED')", name="ck_job_reviews_state"
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", name="uq_job_reviews_job_id"),
    )

    op.create_table(
        "applications",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="DRAFT", nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source", sa.String(length=100), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("application_url", sa.String(length=2048), nullable=True),
        sa.Column("cv_version", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            f"status IN ({_APPLICATION_STATUSES})", name="ck_applications_status"
        ),
        sa.ForeignKeyConstraint(["job_id"], ["jobs.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", name="uq_applications_job_id"),
    )
    op.create_index("ix_applications_status", "applications", ["status"], unique=False)

    op.create_table(
        "application_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("from_status", sa.String(length=20), nullable=True),
        sa.Column("to_status", sa.String(length=20), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            f"from_status IS NULL OR from_status IN ({_APPLICATION_STATUSES})",
            name="ck_application_events_from_status",
        ),
        sa.CheckConstraint(
            f"to_status IN ({_APPLICATION_STATUSES})", name="ck_application_events_to_status"
        ),
        sa.ForeignKeyConstraint(["application_id"], ["applications.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_application_events_application_occurred",
        "application_events",
        ["application_id", "occurred_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_application_events_application_occurred", table_name="application_events")
    op.drop_table("application_events")
    op.drop_index("ix_applications_status", table_name="applications")
    op.drop_table("applications")
    op.drop_table("job_reviews")
    op.drop_index("ix_job_evaluations_rubric_version", table_name="job_evaluations")
    op.drop_table("job_evaluations")
    op.drop_column("job_sources", "source_location")
    op.drop_column("job_sources", "source_description")
    op.drop_column("job_sources", "source_title")
