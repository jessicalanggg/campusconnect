"""email verification

Revision ID: 003
Revises: 002

Existing accounts start unverified and must confirm their (Penn) email before signing in again.
"""
import sqlalchemy as sa
from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    with op.batch_alter_table("users") as batch:
        batch.drop_column("email_verified_at")
