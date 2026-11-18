"""Concurrency guarantees for matched groups, run against a REAL PostgreSQL (SQLite has no row locks).

Set TEST_POSTGRES_URL (CI provides a Postgres service) to run these, e.g.
    TEST_POSTGRES_URL=postgresql+psycopg://postgres:postgres@localhost:5432/campus_test pytest tests/test_concurrency_postgres.py
"""
import os
import threading
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.db.session import Base
from app.matching import service
from app.matching.engine import HOURS_PER_DAY
from app.models.entities import Course, MatchRequest, Membership, StudyGroup, User

PG_URL = os.environ.get("TEST_POSTGRES_URL", "")
pytestmark = pytest.mark.skipif(not PG_URL, reason="needs TEST_POSTGRES_URL pointing at a real PostgreSQL")

EVENING = [d * HOURS_PER_DAY + h - 8 for d in (0, 2) for h in range(18, 21)]
T0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def Session():
    url = PG_URL.replace("postgres://", "postgresql+psycopg://", 1).replace("postgresql://", "postgresql+psycopg://", 1)
    engine = create_engine(url, pool_size=20, max_overflow=0)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.drop_all(engine)
    engine.dispose()


def make_group(Session, members: int, waiting: int, max_members: int = 6):
    """A matched group with `members` students and `waiting` compatible students in the pool, oldest first."""
    with Session() as db:
        course = Course(code="CIS 1200", title="Programming", department="CS")
        db.add(course)
        db.flush()
        group = StudyGroup(course_id=course.id, owner_id=None, title="CIS 1200 study group", description="",
                           max_members=max_members, kind="matched")
        db.add(group)
        db.flush()

        def student(i, status):
            user = User(email=f"s{i}@upenn.edu", name=f"S{i}", password_hash="x")
            db.add(user)
            db.flush()
            req = MatchRequest(user_id=user.id, course_id=course.id, goal="exam_prep", pace=2, preferred_size=6,
                               availability=EVENING, status=status, left_group_ids=[],
                               created_at=T0 + timedelta(minutes=i))
            db.add(req)
            db.flush()
            return user, req

        for i in range(members):
            user, req = student(i, "matched")
            db.add(Membership(group_id=group.id, user_id=user.id))
            req.group_id, req.matched_at = group.id, T0
        waiting_ids = [student(100 + i, "waiting")[1].id for i in range(waiting)]
        db.commit()
        return course.id, group.id, waiting_ids


def run_together(fns):
    """Start all callables at the same instant (barrier) and re-raise any error."""
    barrier, errors = threading.Barrier(len(fns)), []

    def wrap(fn):
        try:
            barrier.wait()
            fn()
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=wrap, args=(fn,)) for fn in fns]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    assert not errors, errors


def state(Session, group_id):
    with Session() as db:
        members = db.scalar(select(func.count(Membership.id)).where(Membership.group_id == group_id))
        placed = db.scalars(select(MatchRequest.id).where(MatchRequest.group_id == group_id,
                                                          MatchRequest.status == "matched")).all()
        dupes = db.scalar(select(func.count()).select_from(
            select(Membership.user_id).group_by(Membership.user_id).having(func.count() > 1).subquery()))
        return members, set(placed), dupes


@pytest.mark.parametrize("open_seats", [1, 2])
def test_row_locks_alone_never_overfill_a_group(Session, open_seats):
    """Ten students race for the open seats with NO advisory lock: only the row locks protect capacity."""
    _, gid, waiting = make_group(Session, members=6 - open_seats, waiting=10)
    placed_flags = []

    def attempt(rid):
        def go():
            with Session() as db:
                placed_flags.append(service.try_instant_fill(db, db.get(MatchRequest, rid)))
                db.commit()
        return go

    run_together([attempt(r) for r in waiting])
    members, placed, dupes = state(Session, gid)
    assert members == 6 and sum(placed_flags) == open_seats
    assert len(placed & set(waiting)) == open_seats and dupes == 0


def test_concurrent_refills_give_the_seat_to_the_longest_waiting_student(Session):
    """Several refill workflows (scheduler + API) run at once; the seat goes to the oldest compatible request."""
    course_id, gid, waiting = make_group(Session, members=5, waiting=10)

    def refill():
        with Session() as db:
            service.lock_course(db, course_id)
            service.fill_waiting(db, course_id)
            db.commit()

    run_together([refill for _ in range(8)])
    members, placed, dupes = state(Session, gid)
    assert members == 6 and dupes == 0
    assert placed & set(waiting) == {waiting[0]}  # waiting[0] has the earliest created_at
    with Session() as db:
        still_waiting = db.scalar(select(func.count(MatchRequest.id)).where(MatchRequest.status == "waiting"))
    assert still_waiting == 9


def test_a_student_is_never_placed_twice(Session):
    """Two groups each have a seat; concurrent refills must not put the same student in both."""
    course_id, gid, waiting = make_group(Session, members=5, waiting=1)
    with Session() as db:
        second = StudyGroup(course_id=course_id, owner_id=None, title="Second", description="", max_members=6,
                            kind="matched")
        db.add(second)
        db.flush()
        for i in range(5):
            user = User(email=f"t{i}@upenn.edu", name=f"T{i}", password_hash="x")
            db.add(user)
            db.flush()
            db.add(Membership(group_id=second.id, user_id=user.id))
            db.add(MatchRequest(user_id=user.id, course_id=course_id, goal="exam_prep", pace=2, preferred_size=6,
                                availability=EVENING, status="matched", group_id=second.id, left_group_ids=[],
                                created_at=T0, matched_at=T0))
        db.commit()

    def attempt():
        with Session() as db:
            service.try_instant_fill(db, db.get(MatchRequest, waiting[0]))
            db.commit()

    run_together([attempt for _ in range(6)])
    with Session() as db:
        memberships = db.scalar(select(func.count(Membership.id)).join(User).where(User.email == "s100@upenn.edu"))
    assert memberships == 1
