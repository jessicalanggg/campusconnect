from datetime import datetime, time, timedelta, timezone
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response
from sqlalchemy import select, func, or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from app.core.config import settings
from app.db.session import get_db
from app.core import email, ratelimit
from app.core.ratelimit import by_ip
from app.core.security import (admin_user, clear_session_cookies, current_user, hash_password, make_token,
                               make_verify_token, read_verify_token, set_session_cookies, verify_password)
from app.matching import service
from app.models.entities import User, Course, Exam, MatchRequest, MatchRun, MeetingCheckin, StudyGroup, Membership, utcnow
from app.matching.engine import NUM_SLOTS, MatchConfig
from app.schemas.api import (AvailabilityOut, CheckinCreate, ContactUpdate, EmailIn, MemberOut, PublicConfig,
                             RegisterOut, RequestStatusOut, VerifyIn, ExamCreate, ExamOut, MatchRequestCreate,
                             MatchRequestOut, MatchRequestUpdate, MatchRunOut, MeOut, UserCreate, Login, UserOut,
                             Token, CourseOut, GroupOut)

router = APIRouter(prefix="/api")


def group_out(group: StudyGroup, db: Session, viewer: User | None = None) -> GroupOut:
    meetings = db.scalar(select(func.count(func.distinct(MeetingCheckin.met_on)))
                         .where(MeetingCheckin.group_id == group.id, MeetingCheckin.met.is_(True))) or 0
    is_member = viewer is not None and is_group_member(db, group.id, viewer.id)
    exam = db.get(Exam, group.exam_id) if group.exam_id else None
    return GroupOut(id=group.id, course_id=group.course_id, course_code=group.course.code, title=group.title,
                    description=group.description, max_members=group.max_members,
                    member_count=service.member_count(db, group.id), created_at=group.created_at,
                    match_quality=group.match_quality, common_slots=group.common_slots or [],
                    meetings_reported=meetings, viewer_status="member" if is_member else None,
                    exam_name=exam.name if exam else None, exam_date=exam.exam_date if exam else None)


def is_group_member(db: Session, group_id: int, user_id: int) -> bool:
    return db.scalar(select(Membership.id).where(Membership.group_id == group_id,
                                                 Membership.user_id == user_id)) is not None


def visible_group_or_404(db: Session, group_id: int, user: User) -> StudyGroup:
    """Matched groups are private: only their members (and admins) can see them."""
    group = db.get(StudyGroup, group_id)
    if not group or not (is_group_member(db, group_id, user.id) or settings.is_admin(user.email)):
        raise HTTPException(404, "Group not found")
    return group


def request_out(req: MatchRequest) -> MatchRequestOut:
    return MatchRequestOut(id=req.id, course_id=req.course_id, course_code=req.course.code, exam_id=req.exam_id,
                           goal=req.goal, pace=req.pace, preferred_size=req.preferred_size,
                           availability=req.availability, status=req.status, group_id=req.group_id,
                           created_at=req.created_at, matched_at=req.matched_at)


# ---------------------------------------------------------------------------------------------------- auth

def domain_message() -> str:
    domains = settings.allowed_domains()
    if domains == ["upenn.edu"]:
        return "Use your Penn email address (@upenn.edu, including school addresses like @engineering.upenn.edu)"
    return "Sign up with an email address from: " + ", ".join("@" + d for d in domains)


@router.get("/config", response_model=PublicConfig)
def public_config():
    """Sign-up rules, so the frontend can label the form and skip the 'check your email' step when it's off."""
    return PublicConfig(allowed_email_domains=settings.allowed_domains(),
                        require_email_verification=settings.require_email_verification)


@router.post("/auth/register", response_model=RegisterOut, status_code=201,
             dependencies=[Depends(by_ip("register", 30, 600))])
def register(data: UserCreate, tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Create an account; when verification is required, email a verification link."""
    address = str(data.email).lower()
    if not settings.email_allowed(address):
        raise HTTPException(422, domain_message())
    user = User(email=address, name=data.name.strip(), password_hash=hash_password(data.password))
    db.add(user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Email already registered") from None
    db.refresh(user)
    if settings.require_email_verification:
        tasks.add_task(email.send_verification, user.email, user.name, make_verify_token(user))
    return RegisterOut(id=user.id, email=user.email, name=user.name,
                       verification_required=settings.require_email_verification)


@router.post("/auth/verify", response_model=UserOut, dependencies=[Depends(by_ip("verify", 30, 600))])
def verify_email(data: VerifyIn, db: Session = Depends(get_db)):
    uid, address = read_verify_token(data.token)
    user = db.get(User, uid)
    if not user or user.email != address:
        raise HTTPException(400, "This verification link is invalid or has expired")
    if user.email_verified_at is None:
        user.email_verified_at = utcnow()
        db.commit()
    return user


@router.post("/auth/resend-verification", status_code=202, dependencies=[Depends(by_ip("resend", 30, 900))])
def resend_verification(data: EmailIn, tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """Always answers 202 so the endpoint can't be used to discover which emails have accounts."""
    address = str(data.email).lower()
    ratelimit.check(f"resend:email:{address}", 3, 900)
    user = db.scalar(select(User).where(User.email == address))
    if settings.require_email_verification and user and user.email_verified_at is None:
        tasks.add_task(email.send_verification, user.email, user.name, make_verify_token(user))
    return {"detail": "If that account exists and isn't verified yet, a new link is on its way."}


@router.post("/auth/login", response_model=Token, dependencies=[Depends(by_ip("login", 60, 300))])
def login(data: Login, response: Response, db: Session = Depends(get_db)):
    """Sets the HttpOnly session cookie (browsers) and also returns the token (API clients)."""
    address = str(data.email).lower()
    ratelimit.check(f"login:email:{address}", 10, 300)
    user = db.scalar(select(User).where(User.email == address))
    if not user or not verify_password(data.password, user.password_hash):
        raise HTTPException(401, "Invalid email or password")
    if settings.require_email_verification and user.email_verified_at is None:
        raise HTTPException(403, "Verify your email first. Check your inbox for the link.")
    token = make_token(user.id)
    set_session_cookies(response, token)
    return Token(access_token=token)


@router.post("/auth/logout", status_code=204)
def logout(response: Response):
    clear_session_cookies(response)


def me_out(user: User) -> MeOut:
    return MeOut(id=user.id, email=user.email, name=user.name, is_admin=settings.is_admin(user.email),
                 contact=user.contact)


@router.get("/auth/me", response_model=MeOut)
def me(user: User = Depends(current_user)):
    return me_out(user)


@router.patch("/auth/me", response_model=MeOut)
def update_me(data: ContactUpdate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Set the optional contact (e.g. a Discord handle) shown to members of your groups."""
    user.contact = data.contact
    db.commit()
    return me_out(user)


# ------------------------------------------------------------------------------------------- courses & exams

@router.get("/courses", response_model=list[CourseOut])
def courses(q: str = Query(default="", max_length=100), db: Session = Depends(get_db)):
    stmt = select(Course)
    if q.strip():
        term = f"%{q.strip()}%"
        stmt = stmt.where(or_(Course.code.ilike(term), Course.title.ilike(term), Course.department.ilike(term)))
    return db.scalars(stmt.order_by(Course.code).limit(100)).all()


@router.get("/exams", response_model=list[ExamOut])
def exams(course_id: int | None = None, upcoming: bool = True, db: Session = Depends(get_db)):
    stmt = select(Exam)
    if course_id is not None:
        stmt = stmt.where(Exam.course_id == course_id)
    if upcoming:
        stmt = stmt.where(Exam.exam_date >= utcnow().date())
    return db.scalars(stmt.order_by(Exam.exam_date)).all()


# Fewer waiting classmates than this and the heatmap stays hidden, so it can't single anyone out.
HEATMAP_MIN_STUDENTS = 3


@router.get("/courses/{course_id}/availability", response_model=AvailabilityOut)
def course_availability(course_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """How many classmates waiting to be matched are free in each weekly hour (counts only, never who)."""
    if not db.get(Course, course_id):
        raise HTTPException(404, "Course not found")
    rows = db.scalars(select(MatchRequest.availability).where(MatchRequest.course_id == course_id,
                                                              MatchRequest.status == "waiting",
                                                              MatchRequest.user_id != user.id)).all()
    if len(rows) < HEATMAP_MIN_STUDENTS:
        return AvailabilityOut(students=len(rows), counts=[])
    counts = [0] * NUM_SLOTS
    for slots in rows:
        for s in set(slots):
            if 0 <= s < NUM_SLOTS:
                counts[s] += 1
    return AvailabilityOut(students=len(rows), counts=counts)


@router.post("/admin/exams", response_model=ExamOut, status_code=201)
def create_exam(data: ExamCreate, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    if not db.get(Course, data.course_id):
        raise HTTPException(404, "Course not found")
    exam = Exam(**data.model_dump())
    db.add(exam)
    db.commit()
    db.refresh(exam)
    return exam


@router.post("/admin/courses/{course_id}/match", response_model=MatchRunOut | None)
def trigger_match(course_id: int, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    if not db.get(Course, course_id):
        raise HTTPException(404, "Course not found")
    return service.run_course_matching(db, course_id, trigger="admin")


@router.get("/admin/match-runs", response_model=list[MatchRunOut])
def match_runs(course_id: int | None = None, _: User = Depends(admin_user), db: Session = Depends(get_db)):
    stmt = select(MatchRun)
    if course_id is not None:
        stmt = stmt.where(MatchRun.course_id == course_id)
    return db.scalars(stmt.order_by(MatchRun.created_at.desc(), MatchRun.id.desc()).limit(50)).all()


@router.get("/metrics")
def metrics(db: Session = Depends(get_db)):
    """Aggregate, non-identifying product metrics: meeting rates, retention, time to match, algorithm gains."""
    return service.compute_metrics(db)


# -------------------------------------------------------------------------------------------------- matching

@router.post("/match/requests", response_model=MatchRequestOut, status_code=201,
             dependencies=[Depends(by_ip("match_request", 60, 3600))])
def create_match_request(data: MatchRequestCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if not db.get(Course, data.course_id):
        raise HTTPException(404, "Course not found")
    active = db.scalar(select(MatchRequest).where(MatchRequest.user_id == user.id,
                                                  MatchRequest.course_id == data.course_id,
                                                  MatchRequest.status.in_(("waiting", "matched"))))
    if active:
        raise HTTPException(409, "You already have an active match request for this course")
    req = MatchRequest(user_id=user.id, left_group_ids=[], **data.model_dump())
    service.submit_request(db, req)
    db.refresh(req)
    return request_out(req)


@router.get("/match/requests", response_model=list[MatchRequestOut])
def my_match_requests(user: User = Depends(current_user), db: Session = Depends(get_db)):
    rows = db.scalars(select(MatchRequest).where(MatchRequest.user_id == user.id)
                      .order_by(MatchRequest.created_at.desc(), MatchRequest.id.desc())).all()
    return [request_out(r) for r in rows]


def own_request(db: Session, request_id: int, user: User) -> MatchRequest:
    req = db.get(MatchRequest, request_id)
    if not req or req.user_id != user.id:
        raise HTTPException(404, "Match request not found")
    if req.status == "withdrawn":
        raise HTTPException(409, "This match request was withdrawn")
    return req


@router.get("/match/requests/{request_id}/status", response_model=RequestStatusOut)
def match_request_status(request_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """For a waiting request: how big the pool is, how many classmates you could be grouped with, and roughly
    when the next matching round runs. Counts only; never who."""
    req = own_request(db, request_id, user)
    if req.status != "waiting":
        raise HTTPException(409, "This request is not waiting to be matched")
    now = utcnow()
    others = db.scalars(select(MatchRequest.availability).where(MatchRequest.course_id == req.course_id,
                                                                MatchRequest.status == "waiting",
                                                                MatchRequest.id != req.id)).all()
    mine = set(req.availability)
    need = MatchConfig().min_common_slots
    compatible = sum(1 for slots in others if len(mine & set(slots)) >= need)
    window = service.active_exam(db, req.course_id, now.date())
    upcoming = window or db.scalar(select(Exam).where(Exam.course_id == req.course_id, Exam.exam_date >= now.date())
                                   .order_by(Exam.exam_date))
    # The scheduler matches a course while it's inside an exam window, or once someone has waited too long.
    oldest = db.scalar(select(func.min(MatchRequest.created_at)).where(MatchRequest.course_id == req.course_id,
                                                                      MatchRequest.status == "waiting"))
    due = [service.aware(oldest) + timedelta(hours=settings.match_max_wait_hours)] if oldest else []
    if window:
        due.append(now)
    elif upcoming:
        start = upcoming.exam_date - timedelta(days=settings.match_window_days)
        due.append(datetime.combine(start, time.min, tzinfo=timezone.utc))
    # Rounds run on the scheduler's interval, so a round that's already due happens within one interval.
    next_round = max(min(due), now) + timedelta(minutes=settings.match_interval_minutes) if due else None
    return RequestStatusOut(waiting_in_course=len(others), compatible_classmates=compatible, min_common_hours=need,
                            window_open=window is not None, next_round_at=next_round,
                            next_exam_name=upcoming.name if upcoming else None,
                            next_exam_date=upcoming.exam_date if upcoming else None)


@router.patch("/match/requests/{request_id}", response_model=MatchRequestOut)
def update_match_request(request_id: int, data: MatchRequestUpdate, user: User = Depends(current_user),
                         db: Session = Depends(get_db)):
    req = own_request(db, request_id, user)
    changes = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}
    service.update_request(db, req, changes)
    db.refresh(req)
    return request_out(req)


@router.delete("/match/requests/{request_id}", status_code=204)
def withdraw_match_request(request_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    service.withdraw_request(db, own_request(db, request_id, user))


# ---------------------------------------------------------------------------------------------------- groups
# All groups are formed by the matcher. Joining happens through match requests, never directly.

@router.get("/groups/mine", response_model=list[GroupOut])
def my_groups(user: User = Depends(current_user), db: Session = Depends(get_db)):
    member = select(Membership.group_id).where(Membership.user_id == user.id)
    rows = db.scalars(select(StudyGroup).where(StudyGroup.id.in_(member))
                      .order_by(StudyGroup.created_at.desc(), StudyGroup.id.desc())).all()
    return [group_out(g, db, user) for g in rows]


@router.get("/groups/{group_id}", response_model=GroupOut)
def get_group(group_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return group_out(visible_group_or_404(db, group_id, user), db, user)


@router.delete("/groups/{group_id}/members/me", status_code=204)
def leave_group(group_id: int, rematch: bool = False, user: User = Depends(current_user),
                db: Session = Depends(get_db)):
    group = db.get(StudyGroup, group_id)
    if not group or not is_group_member(db, group_id, user.id):
        raise HTTPException(404, "Not a member")
    service.leave_matched_group(db, group, user, rematch)


@router.get("/groups/{group_id}/members", response_model=list[MemberOut])
def group_members(group_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    visible_group_or_404(db, group_id, user)
    return db.scalars(select(User).join(Membership).where(Membership.group_id == group_id).order_by(User.name)).all()


@router.post("/groups/{group_id}/checkins", response_model=GroupOut,
             dependencies=[Depends(by_ip("checkin", 120, 3600))])
def checkin(group_id: int, data: CheckinCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """'Did your group meet?' — members report per date; re-answering the same date updates the answer."""
    group = db.get(StudyGroup, group_id)
    if not group:
        raise HTTPException(404, "Group not found")
    if not is_group_member(db, group_id, user.id):
        raise HTTPException(403, "Only members can report meetings")
    # One day of slack: a student ahead of UTC can already be on "tomorrow" (UTC) locally.
    if data.met_on > utcnow().date() + timedelta(days=1):
        raise HTTPException(422, "Meeting date cannot be in the future")
    if data.met_on < service.aware(group.created_at).date():
        raise HTTPException(422, "Meeting date is before the group was formed")
    existing = db.scalar(select(MeetingCheckin).where(MeetingCheckin.group_id == group_id,
                                                      MeetingCheckin.user_id == user.id,
                                                      MeetingCheckin.met_on == data.met_on))
    if existing:
        existing.met = data.met
    else:
        db.add(MeetingCheckin(group_id=group_id, user_id=user.id, met=data.met, met_on=data.met_on))
    db.commit()
    return group_out(group, db, user)
