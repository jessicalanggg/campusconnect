"""'You've been matched' emails and the Resend email provider."""
import json

from app.core import email
from app.core.config import settings
from app.matching.engine import HOURS_PER_DAY
from tests.helpers import PASSWORD, auth

EVENING = [0 * HOURS_PER_DAY + h - 8 for h in range(18, 21)] + [2 * HOURS_PER_DAY + h - 8 for h in range(18, 21)]


def request(client, headers):
    r = client.post("/api/match/requests", headers=headers, json={
        "course_id": 1, "goal": "exam_prep", "pace": 2, "preferred_size": 4, "availability": EVENING})
    assert r.status_code == 201, r.text
    return r.json()


def matched_emails():
    return {m["To"]: m for m in email.OUTBOX if m["Subject"].startswith("You're matched")}


def test_batch_match_emails_every_placed_student(client):
    admin = auth(client, "admin@upenn.edu")
    hs = [auth(client, f"s{i}@upenn.edu", f"Student {i}") for i in range(3)]
    for h in hs:
        request(client, h)
    assert matched_emails() == {}  # waiting isn't matched

    client.post("/api/admin/courses/1/match", headers=admin)
    sent = matched_emails()
    assert set(sent) == {"s0@upenn.edu", "s1@upenn.edu", "s2@upenn.edu"}
    body = sent["s1@upenn.edu"].get_content()
    assert sent["s1@upenn.edu"]["Subject"] == "You're matched: CIS 1200 study group"
    assert "Hi Student 1" in body and "2 classmates" in body and "Mon 18:00–21:00, Wed 18:00–21:00" in body
    # The email never lists the other members' addresses.
    assert "s0@upenn.edu" not in body and "s2@upenn.edu" not in body


def test_instant_placement_on_submit_sends_no_email(client):
    admin = auth(client, "admin@upenn.edu")
    hs = [auth(client, f"s{i}@upenn.edu") for i in range(4)]
    for h in hs[:3]:
        request(client, h)
    client.post("/api/admin/courses/1/match", headers=admin)
    email.OUTBOX.clear()
    assert request(client, hs[3])["status"] == "matched"  # placed into the open seat while they wait
    assert matched_emails() == {}


def test_unverified_and_disabled_get_no_email(client, monkeypatch):
    admin = auth(client, "admin@upenn.edu")
    monkeypatch.setattr(settings, "require_email_verification", False)
    hs = []
    for i in range(3):
        client.post("/api/auth/register", json={"email": f"u{i}@upenn.edu", "name": "U", "password": PASSWORD})
        token = client.post("/api/auth/login", json={"email": f"u{i}@upenn.edu", "password": PASSWORD}).json()
        client.cookies.clear()
        hs.append({"Authorization": f"Bearer {token['access_token']}"})
    for h in hs:
        request(client, h)
    email.OUTBOX.clear()
    client.post("/api/admin/courses/1/match", headers=admin)
    assert len(client.get("/api/groups/mine", headers=hs[0]).json()) == 1
    assert matched_emails() == {}  # never verified, so never emailed

    monkeypatch.setattr(settings, "require_email_verification", True)
    monkeypatch.setattr(settings, "notify_on_match", False)
    vs = [auth(client, f"v{i}@upenn.edu") for i in range(3)]
    for h in vs:
        r = client.post("/api/match/requests", headers=h, json={
            "course_id": 1, "goal": "homework", "pace": 1, "preferred_size": 3,
            "availability": [4 * HOURS_PER_DAY + h - 8 for h in (9, 10, 11)]})
        assert r.status_code == 201
    client.post("/api/admin/courses/1/match", headers=admin)
    assert matched_emails() == {}


def test_resend_provider_posts_to_the_api(monkeypatch):
    sent = {}

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"id": "abc"}'

    def fake_urlopen(req, timeout):
        sent.update(url=req.full_url, auth=req.get_header("Authorization"), body=json.loads(req.data), timeout=timeout)
        return Resp()

    monkeypatch.setattr(settings, "resend_api_key", "re_test_key")
    monkeypatch.setattr(settings, "email_from", "CampusConnect <hello@example.org>")
    monkeypatch.setattr(email.urllib.request, "urlopen", fake_urlopen)
    assert email.provider() == "resend"
    assert email.send("s@upenn.edu", "Subject", "Body") is True
    assert sent["url"] == "https://api.resend.com/emails" and sent["auth"] == "Bearer re_test_key"
    assert sent["body"]["to"] == ["s@upenn.edu"] and sent["body"]["from"] == "CampusConnect <hello@example.org>"
    assert sent["body"]["subject"] == "Subject" and sent["body"]["text"].strip() == "Body"


def test_resend_errors_are_logged_not_raised(monkeypatch, caplog):
    import io
    import urllib.error

    def failing(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, io.BytesIO(b'{"message":"domain not verified"}'))

    monkeypatch.setattr(settings, "resend_api_key", "re_test_key")
    monkeypatch.setattr(email.urllib.request, "urlopen", failing)
    with caplog.at_level("INFO", logger="campusconnect.email"):
        assert email.send("s@upenn.edu", "Subject", "Body") is False
    assert any("EMAIL FAILED to s@upenn.edu via Resend" in r.getMessage() and "domain not verified" in r.getMessage()
               for r in caplog.records)
