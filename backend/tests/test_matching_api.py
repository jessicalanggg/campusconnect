from datetime import date, datetime, timedelta, timezone

from app.matching.engine import HOURS_PER_DAY
from app.models.entities import Exam, MatchRequest, StudyGroup


def auth(client, email, name="Student"):
    assert client.post("/api/auth/register", json={"email": email, "name": name,
                                                  "password": "strong-password-123"}).status_code == 201
    token = client.post("/api/auth/login", json={"email": email, "password": "strong-password-123"}).json()
    return {"Authorization": f"Bearer {token['access_token']}"}


def slots(day, start, end):
    return [day * HOURS_PER_DAY + h - 8 for h in range(start, end)]


EVENING = slots(0, 18, 21) + slots(2, 18, 21)


def request(client, headers, availability=EVENING, goal="exam_prep", size=3):
    r = client.post("/api/match/requests", headers=headers, json={
        "course_id": 1, "goal": goal, "pace": 2, "preferred_size": size, "availability": availability})
    assert r.status_code == 201, r.text
    return r.json()


def test_batch_match_instant_fill_and_metrics(client):
    admin = auth(client, "admin@example.com")
    students = [auth(client, f"s{i}@example.com") for i in range(4)]
    reqs = [request(client, h) for h in students[:3]]
    assert all(r["status"] == "waiting" for r in reqs)
    assert client.post("/api/admin/courses/1/match", headers=students[0]).status_code == 403

    run = client.post("/api/admin/courses/1/match", headers=admin).json()
    assert run["students"] == 3 and run["assigned"] == 3 and run["groups_created"] == 1
    mine = client.get("/api/groups/mine", headers=students[0]).json()
    assert len(mine) == 1 and mine[0]["kind"] == "matched" and mine[0]["member_count"] == 3
    assert mine[0]["owner_id"] is None and "Mon 18:00–21:00" in mine[0]["description"]
    gid = mine[0]["id"]

    # Matched groups are not joinable directly and don't appear in the manual explore list by default.
    assert client.post(f"/api/groups/{gid}/join", headers=students[3]).status_code == 409
    assert client.get("/api/groups").json()["total"] == 0
    assert client.get("/api/groups?kind=matched").json()["total"] == 1

    # A late student who fits is placed instantly into the open seat.
    late = request(client, students[3])
    assert late["status"] == "matched" and late["group_id"] == gid
    assert client.post("/api/match/requests", headers=students[3], json={
        "course_id": 1, "goal": "homework", "pace": 2, "preferred_size": 3, "availability": EVENING}).status_code == 409

    metrics = client.get("/api/metrics").json()
    assert metrics["matched_groups"] == 1 and metrics["students_requested_match"] == 4
    assert metrics["algorithm"]["runs"] == 1 and metrics["time_to_match_hours_median"] is not None


def test_leave_rematch_dissolve_and_schedule_change(client, session_factory):
    admin = auth(client, "admin@example.com")
    hs = [auth(client, f"s{i}@example.com") for i in range(3)]
    reqs = [request(client, h) for h in hs]
    client.post("/api/admin/courses/1/match", headers=admin)
    gid = client.get("/api/groups/mine", headers=hs[0]).json()[0]["id"]

    # Schedule change that breaks the group's shared time pulls that student out and requeues them.
    r = client.patch(f"/api/match/requests/{reqs[0]['id']}", headers=hs[0],
                     json={"availability": slots(5, 10, 14)}).json()
    assert r["status"] == "waiting" and r["group_id"] is None
    assert client.get(f"/api/groups/{gid}").json()["member_count"] == 2

    # Fixing the schedule doesn't put them back automatically unless they fit; they do, so they're refilled.
    r = client.patch(f"/api/match/requests/{reqs[0]['id']}", headers=hs[0], json={"availability": EVENING}).json()
    assert r["status"] == "matched" and r["group_id"] == gid

    # Leaving with rematch requeues the student and never returns them to the group they left.
    assert client.delete(f"/api/groups/{gid}/members/me?rematch=true", headers=hs[1]).status_code == 204
    mine = client.get("/api/match/requests", headers=hs[1]).json()[0]
    assert mine["status"] == "waiting" and mine["group_id"] is None
    with session_factory() as db:
        assert db.get(MatchRequest, mine["id"]).left_group_ids == [gid]

    # Down to 2 members: the group survives. One more leaves → dissolved, last member requeued.
    assert client.get(f"/api/groups/{gid}").json()["member_count"] == 2
    client.delete(f"/api/groups/{gid}/members/me", headers=hs[2])
    assert client.get(f"/api/groups/{gid}").json()["member_count"] == 0
    assert client.get("/api/match/requests", headers=hs[0]).json()[0]["status"] == "waiting"
    assert client.get("/api/match/requests", headers=hs[2]).json()[0]["status"] == "withdrawn"


def test_waitlist_fifo_promotion(client):
    owner, a, b, c = (auth(client, f"{n}@example.com") for n in ("owner", "a", "b", "c"))
    gid = client.post("/api/groups", headers=owner, json={"course_id": 1, "title": "Full group",
                                                          "max_members": 2}).json()["id"]
    assert client.post(f"/api/groups/{gid}/waitlist", headers=a).status_code == 409  # seats still open
    assert client.post(f"/api/groups/{gid}/join", headers=a).status_code == 200
    assert client.post(f"/api/groups/{gid}/join", headers=b).status_code == 409
    assert client.post(f"/api/groups/{gid}/waitlist", headers=b).status_code == 201
    w = client.post(f"/api/groups/{gid}/waitlist", headers=c).json()
    assert w["viewer_status"] == "waitlisted" and w["viewer_waitlist_position"] == 2 and w["waitlist_count"] == 2
    assert client.post(f"/api/groups/{gid}/waitlist", headers=c).status_code == 409

    # A seat opens → the earliest waitlisted student (b) is promoted, not c.
    assert client.delete(f"/api/groups/{gid}/members/me", headers=a).status_code == 204
    assert client.get(f"/api/groups/{gid}", headers=b).json()["viewer_status"] == "member"
    g = client.get(f"/api/groups/{gid}", headers=c).json()
    assert g["viewer_status"] == "waitlisted" and g["viewer_waitlist_position"] == 1

    # Raising capacity promotes the rest; lowering below membership is refused.
    assert client.patch(f"/api/groups/{gid}", headers=owner, json={"max_members": 3}).json()["waitlist_count"] == 0
    assert client.get(f"/api/groups/{gid}", headers=c).json()["viewer_status"] == "member"
    assert client.patch(f"/api/groups/{gid}", headers=owner, json={"max_members": 2}).status_code == 409
    assert len(client.get("/api/groups/mine", headers=c).json()) == 1


def test_checkins_feed_meeting_metrics(client, session_factory):
    admin = auth(client, "admin@example.com")
    hs = [auth(client, f"s{i}@example.com") for i in range(3)]
    for h in hs:
        request(client, h)
    client.post("/api/admin/courses/1/match", headers=admin)
    gid = client.get("/api/groups/mine", headers=hs[0]).json()[0]["id"]
    # Backdate the group so it is old enough to count toward meeting stats.
    with session_factory() as db:
        db.get(StudyGroup, gid).created_at = datetime.now(timezone.utc) - timedelta(days=10)
        db.commit()
    today = date.today()
    assert client.post(f"/api/groups/{gid}/checkins", headers=admin,
                       json={"met": True, "met_on": str(today)}).status_code == 403
    assert client.post(f"/api/groups/{gid}/checkins", headers=hs[0],
                       json={"met": True, "met_on": str(today + timedelta(days=1))}).status_code == 422
    client.post(f"/api/groups/{gid}/checkins", headers=hs[0], json={"met": True, "met_on": str(today - timedelta(days=5))})
    m = client.get("/api/metrics").json()
    assert m["pct_groups_met_at_least_once"] == 100.0 and m["pct_groups_met_at_least_twice"] == 0.0
    g = client.post(f"/api/groups/{gid}/checkins", headers=hs[1], json={"met": True, "met_on": str(today)}).json()
    assert g["meetings_reported"] == 2
    assert client.get("/api/metrics").json()["pct_groups_met_at_least_twice"] == 100.0


def test_exam_window_tags_requests_and_schedules_matching(client, session_factory):
    from app.matching.service import courses_due
    admin = auth(client, "admin@example.com")
    s = auth(client, "s@example.com")
    assert client.post("/api/admin/exams", headers=s, json={"course_id": 1, "name": "Midterm 1",
                                                            "exam_date": str(date.today())}).status_code == 403
    exam = client.post("/api/admin/exams", headers=admin, json={
        "course_id": 1, "name": "Midterm 1", "exam_date": str(date.today() + timedelta(days=10))}).json()
    assert client.get("/api/exams?course_id=1").json()[0]["name"] == "Midterm 1"
    r = request(client, s)
    assert r["exam_id"] == exam["id"]
    with session_factory() as db:
        assert courses_due(db) == [1]  # inside the exam window → matched on the next scheduler pass
        db.get(Exam, exam["id"]).exam_date = date.today() + timedelta(days=40)
        db.commit()
        assert courses_due(db) == []  # outside the window and nobody has waited 24h yet
        assert courses_due(db, datetime.now(timezone.utc) + timedelta(hours=25)) == [1]


def test_request_validation(client):
    s = auth(client, "s@example.com")
    bad = {"course_id": 1, "goal": "exam_prep", "pace": 2, "preferred_size": 3}
    assert client.post("/api/match/requests", headers=s, json={**bad, "availability": [1]}).status_code == 422
    assert client.post("/api/match/requests", headers=s, json={**bad, "availability": [1, 999]}).status_code == 422
    assert client.post("/api/match/requests", headers=s, json={**bad, "goal": "x", "availability": [1, 2]}).status_code == 422
    assert client.post("/api/match/requests", headers=s, json={**bad, "course_id": 99, "availability": [1, 2]}).status_code == 404
    rid = request(client, s)["id"]
    assert client.delete(f"/api/match/requests/{rid}", headers=s).status_code == 204
    assert client.patch(f"/api/match/requests/{rid}", headers=s, json={"pace": 1}).status_code == 409
