from datetime import date, datetime, timezone
from sqlalchemy import (JSON, Boolean, CheckConstraint, Date, DateTime, Float, ForeignKey, Integer, String, Text,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.db.session import Base


def utcnow():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    # Set when the student clicks the link sent to their Penn address; unverified accounts can't sign in.
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Course(Base):
    __tablename__ = "courses"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(200))
    department: Mapped[str] = mapped_column(String(100))


class Exam(Base):
    """A course milestone. Matching for a course runs automatically in the window before each exam."""
    __tablename__ = "exams"
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    exam_date: Mapped[date] = mapped_column(Date)
    course: Mapped[Course] = relationship()


class MatchRun(Base):
    """One execution of the matcher for a course, with baseline comparisons for evaluation."""
    __tablename__ = "match_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    exam_id: Mapped[int | None] = mapped_column(ForeignKey("exams.id", ondelete="SET NULL"), nullable=True)
    trigger: Mapped[str] = mapped_column(String(30))  # scheduled | admin | rematch
    algorithm: Mapped[str] = mapped_column(String(30))  # algorithm whose result was applied
    students: Mapped[int] = mapped_column(Integer, default=0)
    assigned: Mapped[int] = mapped_column(Integer, default=0)
    groups_created: Mapped[int] = mapped_column(Integer, default=0)
    greedy_quality: Mapped[float] = mapped_column(Float, default=0)
    local_search_quality: Mapped[float] = mapped_column(Float, default=0)
    ilp_quality: Mapped[float] = mapped_column(Float, default=0)
    greedy_overlap_hours: Mapped[float] = mapped_column(Float, default=0)
    ilp_overlap_hours: Mapped[float] = mapped_column(Float, default=0)
    runtime_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StudyGroup(Base):
    __tablename__ = "study_groups"
    __table_args__ = (CheckConstraint("max_members >= 2", name="ck_group_capacity"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="RESTRICT"), index=True)
    # Groups are formed by the matcher and have no owner: every member is equal and anyone may leave.
    owner_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=True)
    title: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="")
    max_members: Mapped[int] = mapped_column(default=8)
    kind: Mapped[str] = mapped_column(String(20), default="matched")  # all groups are matched since migration 004
    exam_id: Mapped[int | None] = mapped_column(ForeignKey("exams.id", ondelete="SET NULL"), nullable=True)
    match_run_id: Mapped[int | None] = mapped_column(ForeignKey("match_runs.id", ondelete="SET NULL"), nullable=True)
    match_quality: Mapped[float | None] = mapped_column(Float, nullable=True)
    common_slots: Mapped[list[int] | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    course: Mapped[Course] = relationship()
    owner: Mapped[User | None] = relationship()
    memberships: Mapped[list["Membership"]] = relationship(back_populates="group", cascade="all, delete-orphan",
                                                           passive_deletes=True)


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("user_id", "group_id", name="uq_membership"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("study_groups.id", ondelete="CASCADE"), index=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    group: Mapped[StudyGroup] = relationship(back_populates="memberships")


class MatchRequest(Base):
    """A student's request to be matched for one course (and optionally one exam cycle)."""
    __tablename__ = "match_requests"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), index=True)
    exam_id: Mapped[int | None] = mapped_column(ForeignKey("exams.id", ondelete="SET NULL"), nullable=True)
    goal: Mapped[str] = mapped_column(String(20))
    pace: Mapped[int] = mapped_column(Integer)
    preferred_size: Mapped[int] = mapped_column(Integer)
    availability: Mapped[list[int]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="waiting", index=True)  # waiting | matched | withdrawn
    group_id: Mapped[int | None] = mapped_column(ForeignKey("study_groups.id", ondelete="SET NULL"), nullable=True)
    # Groups this student chose to leave; the matcher never puts them back into one of these.
    left_group_ids: Mapped[list[int]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    matched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    course: Mapped[Course] = relationship()


class MeetingCheckin(Base):
    """'Did your group meet?' — one answer per member per group per date."""
    __tablename__ = "meeting_checkins"
    __table_args__ = (UniqueConstraint("user_id", "group_id", "met_on", name="uq_checkin"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    group_id: Mapped[int] = mapped_column(ForeignKey("study_groups.id", ondelete="CASCADE"), index=True)
    met: Mapped[bool] = mapped_column(Boolean)
    met_on: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
