"""matching, exams, waitlists, meeting check-ins

Revision ID: 002
Revises: 001
"""
import sqlalchemy as sa
from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "exams",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("course_id", sa.Integer, sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("exam_date", sa.Date, nullable=False),
    )
    op.create_index("ix_exams_course_id", "exams", ["course_id"])
    op.create_table(
        "match_runs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("course_id", sa.Integer, sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("exam_id", sa.Integer, sa.ForeignKey("exams.id", ondelete="SET NULL"), nullable=True),
        sa.Column("trigger", sa.String(30), nullable=False),
        sa.Column("algorithm", sa.String(30), nullable=False),
        sa.Column("students", sa.Integer, nullable=False),
        sa.Column("assigned", sa.Integer, nullable=False),
        sa.Column("groups_created", sa.Integer, nullable=False),
        sa.Column("greedy_quality", sa.Float, nullable=False),
        sa.Column("local_search_quality", sa.Float, nullable=False),
        sa.Column("ilp_quality", sa.Float, nullable=False),
        sa.Column("greedy_overlap_hours", sa.Float, nullable=False),
        sa.Column("ilp_overlap_hours", sa.Float, nullable=False),
        sa.Column("runtime_ms", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_match_runs_course_id", "match_runs", ["course_id"])

    with op.batch_alter_table("study_groups") as batch:
        batch.alter_column("owner_id", existing_type=sa.Integer, nullable=True)
        batch.add_column(sa.Column("kind", sa.String(20), nullable=False, server_default="manual"))
        batch.add_column(sa.Column("exam_id", sa.Integer, nullable=True))
        batch.add_column(sa.Column("match_run_id", sa.Integer, nullable=True))
        batch.add_column(sa.Column("match_quality", sa.Float, nullable=True))
        batch.add_column(sa.Column("common_slots", sa.JSON, nullable=True))
        batch.create_foreign_key("fk_study_groups_exam_id", "exams", ["exam_id"], ["id"], ondelete="SET NULL")
        batch.create_foreign_key("fk_study_groups_match_run_id", "match_runs", ["match_run_id"], ["id"],
                                 ondelete="SET NULL")

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
    op.create_table(
        "match_requests",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("course_id", sa.Integer, sa.ForeignKey("courses.id", ondelete="CASCADE"), nullable=False),
        sa.Column("exam_id", sa.Integer, sa.ForeignKey("exams.id", ondelete="SET NULL"), nullable=True),
        sa.Column("goal", sa.String(20), nullable=False),
        sa.Column("pace", sa.Integer, nullable=False),
        sa.Column("preferred_size", sa.Integer, nullable=False),
        sa.Column("availability", sa.JSON, nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("group_id", sa.Integer, sa.ForeignKey("study_groups.id", ondelete="SET NULL"), nullable=True),
        sa.Column("left_group_ids", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("matched_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_match_requests_user_id", "match_requests", ["user_id"])
    op.create_index("ix_match_requests_course_id", "match_requests", ["course_id"])
    op.create_index("ix_match_requests_status", "match_requests", ["status"])
    op.create_table(
        "meeting_checkins",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("group_id", sa.Integer, sa.ForeignKey("study_groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("met", sa.Boolean, nullable=False),
        sa.Column("met_on", sa.Date, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "group_id", "met_on", name="uq_checkin"),
    )
    op.create_index("ix_meeting_checkins_user_id", "meeting_checkins", ["user_id"])
    op.create_index("ix_meeting_checkins_group_id", "meeting_checkins", ["group_id"])


def downgrade():
    op.drop_table("meeting_checkins")
    op.drop_table("match_requests")
    op.drop_table("waitlist_entries")
    with op.batch_alter_table("study_groups") as batch:
        batch.drop_constraint("fk_study_groups_match_run_id", type_="foreignkey")
        batch.drop_constraint("fk_study_groups_exam_id", type_="foreignkey")
        for col in ("common_slots", "match_quality", "match_run_id", "exam_id", "kind"):
            batch.drop_column(col)
        batch.alter_column("owner_id", existing_type=sa.Integer, nullable=False)
    op.drop_table("match_runs")
    op.drop_table("exams")
