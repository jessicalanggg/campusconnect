"""optional contact handle that group members can see

Revision ID: 005
Revises: 004
"""
import sqlalchemy as sa
from alembic import op

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("contact", sa.String(120), nullable=True))


def downgrade():
    with op.batch_alter_table("users") as batch:
        batch.drop_column("contact")
