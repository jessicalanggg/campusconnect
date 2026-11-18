"""remove open (student-created) groups and their waitlists

Revision ID: 004
Revises: 003

All study groups are now formed by the matcher. Student-created ("manual") groups, their memberships and check-ins,
and the waitlist table are removed. Downgrade restores the empty waitlist table; deleted groups aren't restored.
"""
import sqlalchemy as sa
from alembic import op

revision = "004"
down_revision = "003"
branch_labels = None
depends_on = None


def upgrade():
    manual = "SELECT id FROM study_groups WHERE kind = 'manual'"
    # Explicit deletes (not relying on ON DELETE CASCADE, which SQLite only honours with foreign_keys=ON).
    op.execute(f"UPDATE match_requests SET group_id = NULL WHERE group_id IN ({manual})")
    op.execute(f"DELETE FROM meeting_checkins WHERE group_id IN ({manual})")
    op.execute(f"DELETE FROM memberships WHERE group_id IN ({manual})")
    op.execute("DELETE FROM waitlist_entries")
    op.execute("DELETE FROM study_groups WHERE kind = 'manual'")
    op.drop_table("waitlist_entries")
    with op.batch_alter_table("study_groups") as batch:
        batch.alter_column("kind", existing_type=sa.String(20), server_default="matched")


def downgrade():
    with op.batch_alter_table("study_groups") as batch:
        batch.alter_column("kind", existing_type=sa.String(20), server_default="manual")
    op.create_table(
        "waitlist_entries",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("group_id", sa.Integer, sa.ForeignKey("study_groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "group_id", name="uq_waitlist"),
    )
    op.create_index("ix_waitlist_entries_user_id", "waitlist_entries", ["user_id"])
    op.create_index("ix_waitlist_entries_group_id", "waitlist_entries", ["group_id"])
