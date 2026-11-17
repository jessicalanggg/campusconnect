"""initial schema

Revision ID: 001
Revises:

Explicit snapshot of the original tables (previously Base.metadata.create_all, which would also have
created tables added by later migrations).
"""
import sqlalchemy as sa
from alembic import op

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)
    op.create_table(
        "courses",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("code", sa.String(30), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("department", sa.String(100), nullable=False),
    )
    op.create_index("ix_courses_code", "courses", ["code"], unique=True)
    op.create_table(
        "study_groups",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("course_id", sa.Integer, sa.ForeignKey("courses.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("owner_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("max_members", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("max_members >= 2", name="ck_group_capacity"),
    )
    op.create_index("ix_study_groups_course_id", "study_groups", ["course_id"])
    op.create_index("ix_study_groups_owner_id", "study_groups", ["owner_id"])
    op.create_table(
        "memberships",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("group_id", sa.Integer, sa.ForeignKey("study_groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "group_id", name="uq_membership"),
    )
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])
    op.create_index("ix_memberships_group_id", "memberships", ["group_id"])


def downgrade():
    op.drop_table("memberships")
    op.drop_table("study_groups")
    op.drop_table("courses")
    op.drop_table("users")
