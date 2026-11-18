"""'You've been matched' emails.

Placements are recorded on the session while matching runs and sent only after the transaction commits, so a
rolled-back placement never sends an email. Only students with a verified email are notified: with verification
off, anyone could sign up with someone else's address, and the app shouldn't email people who never asked.
"""
from sqlalchemy.orm import Session

from app.core import email
from app.core.config import settings
from app.matching.engine import describe_slots
from app.models.entities import Course, MatchRequest, Membership, StudyGroup, User

KEY = "cc_placed"


def record(db: Session, req: MatchRequest) -> None:
    db.info.setdefault(KEY, []).append(req.id)


def forget(db: Session, req: MatchRequest) -> None:
    """Don't email this placement (e.g. the student was placed instantly and saw it on screen)."""
    db.info[KEY] = [i for i in db.info.get(KEY, []) if i != req.id]


def commit(db: Session) -> None:
    """Commit, then email everyone placed in this transaction."""
    pending = db.info.pop(KEY, [])
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    if pending and settings.notify_on_match:
        email.send_all([m for m in (_message(db, rid) for rid in dict.fromkeys(pending)) if m])


def discard(db: Session) -> None:
    db.info.pop(KEY, None)


def _message(db: Session, request_id: int) -> tuple[str, str, str] | None:
    req = db.get(MatchRequest, request_id)
    if not req or req.status != "matched" or not req.group_id:
        return None
    user, group = db.get(User, req.user_id), db.get(StudyGroup, req.group_id)
    if not user or not group or not user.email_verified_at:
        return None
    course = db.get(Course, group.course_id)
    others = db.query(Membership).filter(Membership.group_id == group.id, Membership.user_id != user.id).count()
    when = describe_slots(group.common_slots or []) or "your group's shared hours"
    link = settings.app_base_url.rstrip("/") + "/"
    body = (f"Hi {user.name},\n\n"
            f"You've been matched with {others} classmate{'s' if others != 1 else ''} in {course.code}: {group.title}.\n\n"
            f"Everyone in the group is free: {when}.\n\n"
            f"Open CampusConnect to see who's in your group, email them, and add your shared time to your calendar:\n"
            f"{link}\n\n"
            "You're getting this because you asked to be matched for this course. If the group doesn't work for you, "
            "you can ask for a new one from the group page.\n")
    return user.email, f"You're matched: {course.code} study group", body
