"""Database-facing matching workflows: batch runs, instant fills, rematching and metrics.

Concurrency: every workflow that changes group membership for a course first takes a per-course PostgreSQL advisory
transaction lock, so the scheduler and API requests never interleave on the same course. Underneath that, placing a
student locks the request row and the group row (SELECT ... FOR UPDATE) and re-checks capacity, so a group is never
overfilled and a student is never placed twice even without the advisory lock (see tests/test_concurrency_postgres.py).
"""
from __future__ import annotations

import statistics
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.matching.engine import MatchConfig, Student, best_insertion_for, describe_slots, score_group, solve_all
from app.models.entities import (Course, Exam, MatchRequest, MatchRun, MeetingCheckin, Membership, StudyGroup, User,
                                 utcnow)

ADVISORY_NAMESPACE = 4242
DISSOLVE_BELOW = 2  # a matched group with fewer members than this is dissolved and its members requeued
INSTANT_FILL_MIN_QUALITY = 0.5


def config() -> MatchConfig:
    return MatchConfig(ilp_seconds=settings.ilp_time_limit_seconds)


def aware(dt: datetime | None) -> datetime | None:
    """SQLite drops tzinfo; treat naive datetimes as UTC."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def lock_course(db: Session, course_id: int) -> None:
    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(:ns, :key)"), {"ns": ADVISORY_NAMESPACE, "key": course_id})


def lock_group(db: Session, group_id: int) -> StudyGroup | None:
    return db.scalar(select(StudyGroup).where(StudyGroup.id == group_id).with_for_update()
                     .execution_options(populate_existing=True))


def to_student(req: MatchRequest) -> Student:
    return Student(id=req.id, slots=frozenset(req.availability), goal=req.goal, pace=req.pace,
                   preferred_size=req.preferred_size)


def member_count(db: Session, group_id: int) -> int:
    return db.scalar(select(func.count(Membership.id)).where(Membership.group_id == group_id)) or 0


def active_exam(db: Session, course_id: int, today: date | None = None) -> Exam | None:
    """The next exam for the course if today falls inside its matching window."""
    today = today or utcnow().date()
    return db.scalar(select(Exam).where(Exam.course_id == course_id, Exam.exam_date >= today,
                                        Exam.exam_date <= today + timedelta(days=settings.match_window_days))
                     .order_by(Exam.exam_date))


def matched_requests(db: Session, group_id: int) -> list[MatchRequest]:
    return list(db.scalars(select(MatchRequest).where(MatchRequest.group_id == group_id,
                                                      MatchRequest.status == "matched")))


def refresh_group(db: Session, group: StudyGroup) -> None:
    """Recompute a matched group's shared free time, quality and description from its current members."""
    reqs = matched_requests(db, group.id)
    if not reqs:
        group.common_slots, group.match_quality = [], None
        group.description = "This group was dissolved."
        return
    sc = score_group([to_student(r) for r in reqs], config(), ignore_size=True)
    group.common_slots = sorted(sc.common) if sc else sorted(frozenset.intersection(
        *(frozenset(r.availability) for r in reqs)))
    group.match_quality = round(sc.quality, 4) if sc else 0.0
    when = describe_slots(group.common_slots) or "no shared time yet"
    group.description = f"Matched by CampusConnect. Everyone is free: {when}."


def _place(db: Session, req: MatchRequest, group: StudyGroup) -> None:
    db.add(Membership(group_id=group.id, user_id=req.user_id))
    req.status, req.group_id, req.matched_at = "matched", group.id, utcnow()


def _create_group(db: Session, course: Course, reqs: list[MatchRequest], run: MatchRun | None,
                  exam_id: int | None) -> StudyGroup:
    exam = db.get(Exam, exam_id) if exam_id else None
    title = f"{course.code} · {exam.name} study group" if exam else f"{course.code} study group"
    group = StudyGroup(course_id=course.id, owner_id=None, title=title[:120], description="",
                       max_members=config().max_size, kind="matched", exam_id=exam_id,
                       match_run_id=run.id if run else None)
    db.add(group)
    db.flush()
    for r in reqs:
        _place(db, r, group)
    db.flush()
    refresh_group(db, group)
    return group


def open_matched_groups(db: Session, course_id: int) -> dict[int, list[MatchRequest]]:
    groups = db.scalars(select(StudyGroup).where(StudyGroup.course_id == course_id, StudyGroup.kind == "matched"))
    out = {}
    for g in groups:
        reqs = matched_requests(db, g.id)
        if 1 <= len(reqs) < g.max_members:
            out[g.id] = reqs
    return out


def try_instant_fill(db: Session, req: MatchRequest, open_groups: dict[int, list[MatchRequest]] | None = None) -> bool:
    """Place a waiting student straight into an existing matched group with a vacancy, if they fit well.

    Safe under concurrency on PostgreSQL even without the per-course advisory lock:
    the request row is locked so two refills can't place the same student twice, and the target group's row is
    locked before capacity and fit are re-checked, so two students can never take the last seat.
    """
    open_groups = open_matched_groups(db, req.course_id) if open_groups is None else open_groups
    locked = db.scalar(select(MatchRequest).where(MatchRequest.id == req.id).with_for_update()
                       .execution_options(populate_existing=True))
    if locked is None or locked.status != "waiting":
        return False
    student = to_student(req)
    candidates = {gid: reqs for gid, reqs in open_groups.items() if gid not in (req.left_group_ids or [])}
    while candidates:
        gid = best_insertion_for(student, {g: [to_student(r) for r in rs] for g, rs in candidates.items()},
                                 config(), INSTANT_FILL_MIN_QUALITY)
        if gid is None:
            return False
        group = lock_group(db, gid)
        # Re-check under the row lock: another transaction may have taken the seat (or changed the group) since
        # the snapshot above was read.
        members = matched_requests(db, gid)
        fits = best_insertion_for(student, {gid: [to_student(r) for r in members]}, config(),
                                  INSTANT_FILL_MIN_QUALITY) is not None
        if member_count(db, gid) >= group.max_members or not fits:
            candidates.pop(gid)
            open_groups[gid] = members
            continue
        _place(db, req, group)
        db.flush()
        refresh_group(db, group)
        open_groups[gid] = members + [req]
        return True
    return False


def fill_waiting(db: Session, course_id: int) -> int:
    """Try to instantly place every waiting student in the course, oldest first."""
    placed = 0
    open_groups = open_matched_groups(db, course_id)
    for req in db.scalars(select(MatchRequest).where(MatchRequest.course_id == course_id,
                                                     MatchRequest.status == "waiting")
                          .order_by(MatchRequest.created_at, MatchRequest.id)).all():
        if try_instant_fill(db, req, open_groups):
            placed += 1
    return placed


def run_course_matching(db: Session, course_id: int, trigger: str) -> MatchRun | None:
    """Batch-match all waiting students in a course. Returns the recorded run (None if the pool is too small)."""
    lock_course(db, course_id)
    course = db.get(Course, course_id)
    cfg = config()
    pool = list(db.scalars(select(MatchRequest).where(MatchRequest.course_id == course_id,
                                                      MatchRequest.status == "waiting")
                           .order_by(MatchRequest.created_at, MatchRequest.id)))
    run = None
    if len(pool) >= cfg.min_size:
        by_id = {r.id: r for r in pool}
        results = solve_all([to_student(r) for r in pool], cfg)
        g_sol, g_eval = results["greedy"]
        _, ls_eval = results["local_search"]
        ilp_sol, ilp_eval = results["ilp"]
        exam = active_exam(db, course_id)
        run = MatchRun(course_id=course_id, exam_id=exam.id if exam else None, trigger=trigger, algorithm="ilp",
                       students=len(pool), assigned=ilp_eval["assigned"], groups_created=len(ilp_sol.groups),
                       greedy_quality=round(g_eval["avg_quality"], 4),
                       local_search_quality=round(ls_eval["avg_quality"], 4),
                       ilp_quality=round(ilp_eval["avg_quality"], 4),
                       greedy_overlap_hours=round(g_eval["avg_common_hours"], 3),
                       ilp_overlap_hours=round(ilp_eval["avg_common_hours"], 3),
                       runtime_ms=sum(e["runtime_ms"] for _, e in results.values()))
        db.add(run)
        db.flush()
        for g in ilp_sol.groups:
            reqs = [by_id[i] for i in g]
            exam_ids = {r.exam_id for r in reqs}
            _create_group(db, course, reqs, run, exam_ids.pop() if len(exam_ids) == 1 else None)
        db.flush()
    fill_waiting(db, course_id)
    db.commit()
    return run


def _depart(db: Session, req: MatchRequest, group: StudyGroup, *, requeue: bool, voluntary: bool) -> None:
    db.query(Membership).filter(Membership.group_id == group.id, Membership.user_id == req.user_id).delete()
    req.group_id, req.matched_at = None, None
    req.status = "waiting" if requeue else "withdrawn"
    if voluntary:
        req.left_group_ids = [*(req.left_group_ids or []), group.id]
    db.flush()


def _after_departure(db: Session, group: StudyGroup) -> list[MatchRequest]:
    """Dissolve a group that became too small (requeueing members) or refill its vacancy from the waiting pool."""
    remaining = matched_requests(db, group.id)
    requeued = []
    if len(remaining) < DISSOLVE_BELOW:
        for r in remaining:
            _depart(db, r, group, requeue=True, voluntary=False)
            requeued.append(r)
    refresh_group(db, group)
    db.flush()
    return requeued


def leave_matched_group(db: Session, group: StudyGroup, user: User, rematch: bool) -> None:
    lock_course(db, group.course_id)
    lock_group(db, group.id)
    req = db.scalar(select(MatchRequest).where(MatchRequest.group_id == group.id, MatchRequest.user_id == user.id,
                                               MatchRequest.status == "matched"))
    if req:
        _depart(db, req, group, requeue=rematch, voluntary=True)
    else:  # defensive: membership without a request
        db.query(Membership).filter(Membership.group_id == group.id, Membership.user_id == user.id).delete()
    _after_departure(db, group)
    fill_waiting(db, group.course_id)
    db.commit()


def update_request(db: Session, req: MatchRequest, changes: dict) -> None:
    """Apply preference/schedule changes; if the student's group can no longer meet, rematch them."""
    lock_course(db, req.course_id)
    for key, value in changes.items():
        setattr(req, key, value)
    db.flush()
    if req.status == "matched" and req.group_id:
        group = lock_group(db, req.group_id)
        members = [to_student(r) for r in matched_requests(db, group.id)]
        if score_group(members, config(), ignore_size=True) is None:
            _depart(db, req, group, requeue=True, voluntary=False)
            _after_departure(db, group)
        else:
            refresh_group(db, group)
    if req.status == "waiting":
        fill_waiting(db, req.course_id)
    db.commit()


def withdraw_request(db: Session, req: MatchRequest) -> None:
    lock_course(db, req.course_id)
    if req.status == "matched" and req.group_id:
        group = lock_group(db, req.group_id)
        _depart(db, req, group, requeue=False, voluntary=True)
        _after_departure(db, group)
        fill_waiting(db, req.course_id)
    req.status = "withdrawn"
    db.commit()


def submit_request(db: Session, req: MatchRequest) -> None:
    lock_course(db, req.course_id)
    exam = active_exam(db, req.course_id)
    req.exam_id = exam.id if exam else None
    db.add(req)
    db.flush()
    try_instant_fill(db, req)
    db.commit()


def courses_due(db: Session, now: datetime | None = None) -> list[int]:
    """Courses the scheduler should match now: inside an exam window, or someone has waited too long."""
    now = now or utcnow()
    due = []
    course_ids = db.scalars(select(MatchRequest.course_id).where(MatchRequest.status == "waiting").distinct()).all()
    for cid in course_ids:
        oldest = db.scalar(select(func.min(MatchRequest.created_at)).where(MatchRequest.course_id == cid,
                                                                           MatchRequest.status == "waiting"))
        if active_exam(db, cid, now.date()) or (
                oldest and now - aware(oldest) >= timedelta(hours=settings.match_max_wait_hours)):
            due.append(cid)
    return due


# ------------------------------------------------------------------------------------------------------ metrics

def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    k = (len(values) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (k - lo)


def compute_metrics(db: Session, now: datetime | None = None) -> dict:
    now = now or utcnow()
    eligible_cutoff = now - timedelta(days=7)
    matched_groups = db.scalars(select(StudyGroup).where(StudyGroup.kind == "matched")).all()
    meetings = dict(db.execute(select(MeetingCheckin.group_id, func.count(func.distinct(MeetingCheckin.met_on)))
                               .where(MeetingCheckin.met.is_(True)).group_by(MeetingCheckin.group_id)).all())
    # Only groups at least a week old have had a fair chance to meet twice.
    eligible = [g for g in matched_groups if aware(g.created_at) <= eligible_cutoff]
    met_once = sum(1 for g in eligible if meetings.get(g.id, 0) >= 1)
    met_twice = sum(1 for g in eligible if meetings.get(g.id, 0) >= 2)

    requests = db.scalars(select(MatchRequest)).all()
    cycles: dict[int, set] = {}
    for r in requests:
        cycles.setdefault(r.user_id, set()).add((r.course_id, r.exam_id))
    requesters = len(cycles)
    returning = sum(1 for c in cycles.values() if len(c) >= 2)
    waits = [(aware(r.matched_at) - aware(r.created_at)).total_seconds() / 3600 for r in requests if r.matched_at]

    runs = db.scalars(select(MatchRun).order_by(MatchRun.created_at.desc(), MatchRun.id.desc())).all()
    weighted = [(r.assigned or r.students, r) for r in runs if r.students]
    weight = sum(w for w, _ in weighted)
    g_q = sum(w * r.greedy_quality for w, r in weighted) / weight if weight else None
    i_q = sum(w * r.ilp_quality for w, r in weighted) / weight if weight else None
    g_h = sum(w * r.greedy_overlap_hours for w, r in weighted) / weight if weight else None
    i_h = sum(w * r.ilp_overlap_hours for w, r in weighted) / weight if weight else None

    def pct(a, b):
        return round(100 * a / b, 1) if b else None

    return {
        # With verification on, only accounts that confirmed their email count as users.
        "users": db.scalar(select(func.count(User.id)).where(User.email_verified_at.is_not(None))
                           if settings.require_email_verification else select(func.count(User.id))) or 0,
        "verified_users": db.scalar(select(func.count(User.id)).where(User.email_verified_at.is_not(None))) or 0,
        "students_requested_match": requesters,
        "courses_with_requests": len({r.course_id for r in requests}),
        "matched_groups": len(matched_groups),
        "groups_eligible_for_meeting_stats": len(eligible),
        "pct_groups_met_at_least_once": pct(met_once, len(eligible)),
        "pct_groups_met_at_least_twice": pct(met_twice, len(eligible)),
        "returning_students": returning,
        "retention_pct": pct(returning, requesters),
        "time_to_match_hours_median": round(statistics.median(waits), 2) if waits else None,
        "time_to_match_hours_p90": round(_percentile(waits, 0.9), 2) if waits else None,
        "students_waiting": sum(1 for r in requests if r.status == "waiting"),
        "algorithm": {
            "runs": len(runs),
            "greedy_avg_quality": round(g_q, 4) if g_q is not None else None,
            "ilp_avg_quality": round(i_q, 4) if i_q is not None else None,
            "ilp_quality_gain_pct": round(100 * (i_q - g_q) / g_q, 1) if g_q else None,
            "greedy_avg_common_hours": round(g_h, 2) if g_h is not None else None,
            "ilp_avg_common_hours": round(i_h, 2) if i_h is not None else None,
            "ilp_overlap_gain_pct": round(100 * (i_h - g_h) / g_h, 1) if g_h else None,
        },
    }
