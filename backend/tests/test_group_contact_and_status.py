"""Contacting your group, waiting-pool status and the classmate availability heatmap."""
from datetime import date, timedelta

from app.matching.engine import HOURS_PER_DAY, NUM_SLOTS
from app.models.entities import Exam
from tests.helpers import auth


def slots(day, start, end):
    return [day * HOURS_PER_DAY + h - 8 for h in range(start, end)]


EVENING = slots(0, 18, 21) + slots(2, 18, 21)
MORNING = slots(4, 8, 10)


def request(client, headers, availability=EVENING):
    r = client.post("/api/match/requests", headers=headers, json={
        "course_id": 1, "goal": "exam_prep", "pace": 2, "preferred_size": 3, "availability": availability})
    assert r.status_code == 201, r.text
    return r.json()


def test_members_see_each_others_email_and_shared_contact(client):
    admin = auth(client, "admin@upenn.edu")
    hs = [auth(client, f"s{i}@upenn.edu", f"Student {i}") for i in range(3)]
    outsider = auth(client, "out@upenn.edu")

    r = client.patch("/api/auth/me", headers=hs[0], json={"contact": "  discord: s0#1234  "})
    assert r.status_code == 200 and r.json()["contact"] == "discord: s0#1234"
    assert client.get("/api/auth/me", headers=hs[0]).json()["contact"] == "discord: s0#1234"
    assert client.patch("/api/auth/me", headers=hs[0], json={"contact": "x" * 121}).status_code == 422
    assert client.patch("/api/auth/me", json={"contact": "x"}).status_code == 401

    for h in hs:
        request(client, h)
    client.post("/api/admin/courses/1/match", headers=admin)
    gid = client.get("/api/groups/mine", headers=hs[1]).json()[0]["id"]

    members = {m["email"]: m for m in client.get(f"/api/groups/{gid}/members", headers=hs[1]).json()}
    assert set(members) == {"s0@upenn.edu", "s1@upenn.edu", "s2@upenn.edu"}
    assert members["s0@upenn.edu"]["contact"] == "discord: s0#1234" and members["s1@upenn.edu"]["contact"] is None
    # Contacts stay inside the group.
    assert client.get(f"/api/groups/{gid}/members", headers=outsider).status_code == 404

    # Clearing the contact removes it.
    client.patch("/api/auth/me", headers=hs[0], json={"contact": ""})
    members = {m["email"]: m for m in client.get(f"/api/groups/{gid}/members", headers=hs[1]).json()}
    assert members["s0@upenn.edu"]["contact"] is None


def test_group_reports_its_exam(client, session_factory):
    admin = auth(client, "admin@upenn.edu")
    with session_factory() as db:
        db.add(Exam(course_id=1, name="Midterm 1", exam_date=date.today() + timedelta(days=5)))
        db.commit()
    hs = [auth(client, f"s{i}@upenn.edu") for i in range(3)]
    for h in hs:
        request(client, h)
    client.post("/api/admin/courses/1/match", headers=admin)
    g = client.get("/api/groups/mine", headers=hs[0]).json()[0]
    assert g["exam_name"] == "Midterm 1" and g["exam_date"] == str(date.today() + timedelta(days=5))


def test_waiting_status_counts_compatible_classmates_and_next_round(client, session_factory):
    a, b, c, d = (auth(client, f"s{i}@upenn.edu") for i in range(4))
    ra = request(client, a)
    request(client, b)  # shares Ava's evenings
    request(client, c, slots(0, 18, 19) + MORNING)  # shares only one hour: not enough
    request(client, d, MORNING)  # shares nothing

    st = client.get(f"/api/match/requests/{ra['id']}/status", headers=a).json()
    assert st["waiting_in_course"] == 3 and st["compatible_classmates"] == 1 and st["min_common_hours"] == 2
    assert st["window_open"] is False and st["next_exam_name"] is None
    assert st["next_round_at"] is not None  # the max-wait rule guarantees a round

    with session_factory() as db:
        db.add(Exam(course_id=1, name="Midterm 1", exam_date=date.today() + timedelta(days=3)))
        db.commit()
    st = client.get(f"/api/match/requests/{ra['id']}/status", headers=a).json()
    assert st["window_open"] is True and st["next_exam_name"] == "Midterm 1"

    # Only the owner can see it, and only while waiting.
    assert client.get(f"/api/match/requests/{ra['id']}/status", headers=b).status_code == 404
    client.delete(f"/api/match/requests/{ra['id']}", headers=a)
    assert client.get(f"/api/match/requests/{ra['id']}/status", headers=a).status_code == 409


def test_availability_heatmap_is_anonymous_and_hidden_for_tiny_pools(client):
    viewer = auth(client, "viewer@upenn.edu")
    others = [auth(client, f"s{i}@upenn.edu") for i in range(3)]
    request(client, viewer)
    request(client, others[0])
    request(client, others[1])
    small = client.get("/api/courses/1/availability", headers=viewer).json()
    assert small == {"students": 2, "counts": []}  # too few classmates to show anything

    request(client, others[2], MORNING)
    heat = client.get("/api/courses/1/availability", headers=viewer).json()
    assert heat["students"] == 3 and len(heat["counts"]) == NUM_SLOTS
    assert heat["counts"][EVENING[0]] == 2 and heat["counts"][MORNING[0]] == 1  # the viewer isn't counted
    assert client.get("/api/courses/1/availability").status_code == 401
    assert client.get("/api/courses/999/availability", headers=viewer).status_code == 404
