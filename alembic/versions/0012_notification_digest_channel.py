"""Allow the daily digest as a notification channel.

Revision ID: 0012_notification_digest_channel
Revises: 0011_job_review_reason
Create Date: 2026-10-04
"""

from typing import Sequence, Union

from alembic import op


revision: str = "0012_notification_digest_channel"
down_revision: Union[str, None] = "0011_job_review_reason"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _replace_channel_check(allowed: str) -> None:
    if op.get_bind().dialect.name == "sqlite":
        # SQLite cannot alter CHECK constraints in place; the offline migration
        # tests run there and the real database is PostgreSQL.
        return
    op.drop_constraint("ck_opportunity_notifications_channel", "opportunity_notifications", type_="check")
    op.create_check_constraint(
        "ck_opportunity_notifications_channel", "opportunity_notifications", f"channel IN ({allowed})"
    )


def upgrade() -> None:
    _replace_channel_check("'TELEGRAM', 'TELEGRAM_DIGEST'")


def downgrade() -> None:
    op.execute("DELETE FROM opportunity_notifications WHERE channel = 'TELEGRAM_DIGEST'")
    _replace_channel_check("'TELEGRAM'")
