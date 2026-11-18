from app.core import email
from tests.helpers import PASSWORD, auth, register, verification_token


def test_only_penn_addresses_can_register(client):
    bad = client.post("/api/auth/register", json={"email": "x@gmail.com", "name": "X", "password": PASSWORD})
    assert bad.status_code == 422 and "Penn email" in bad.json()["detail"]
    lookalike = client.post("/api/auth/register", json={"email": "x@notupenn.edu", "name": "X", "password": PASSWORD})
    assert lookalike.status_code == 422
    assert register(client, "student@seas.upenn.edu").json()["email"] == "student@seas.upenn.edu"
    assert register(client, "student@upenn.edu").status_code == 201


def test_unverified_accounts_cannot_sign_in_until_verified(client):
    register(client, "new@upenn.edu")
    r = client.post("/api/auth/login", json={"email": "new@upenn.edu", "password": PASSWORD})
    assert r.status_code == 403 and "Verify" in r.json()["detail"]
    token = verification_token("new@upenn.edu")
    assert client.post("/api/auth/verify", json={"token": "not-a-real-token-at-all"}).status_code == 400
    assert client.post("/api/auth/verify", json={"token": token}).status_code == 200
    assert client.post("/api/auth/verify", json={"token": token}).status_code == 200  # idempotent
    assert client.post("/api/auth/login", json={"email": "new@upenn.edu", "password": PASSWORD}).status_code == 200


def test_verification_token_is_not_a_session_token(client):
    register(client, "new@upenn.edu")
    token = verification_token("new@upenn.edu")
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_resend_does_not_reveal_accounts_and_is_rate_limited(client):
    register(client, "new@upenn.edu")
    before = len(email.OUTBOX)
    assert client.post("/api/auth/resend-verification", json={"email": "nobody@upenn.edu"}).status_code == 202
    assert len(email.OUTBOX) == before
    for _ in range(3):
        assert client.post("/api/auth/resend-verification", json={"email": "new@upenn.edu"}).status_code == 202
    assert len(email.OUTBOX) == before + 3
    assert client.post("/api/auth/resend-verification", json={"email": "new@upenn.edu"}).status_code == 429


def test_cookie_session_requires_csrf_header_for_writes(client):
    auth(client, "s@upenn.edu")  # leaves no cookies behind
    r = client.post("/api/auth/login", json={"email": "s@upenn.edu", "password": PASSWORD})
    set_cookie = r.headers.get_list("set-cookie")
    session = next(c for c in set_cookie if c.startswith("cc_session="))
    assert "HttpOnly" in session and "SameSite=lax" in session
    assert any(c.startswith("cc_csrf=") and "HttpOnly" not in c for c in set_cookie)

    assert client.get("/api/auth/me").json()["email"] == "s@upenn.edu"  # reads work with the cookie alone
    group = {"course_id": 1, "title": "Cookie group"}
    assert client.post("/api/groups", json=group).status_code == 403  # no CSRF header
    assert client.post("/api/groups", json=group, headers={"X-CSRF-Token": "wrong"}).status_code == 403
    csrf = client.cookies.get("cc_csrf")
    assert client.post("/api/groups", json=group, headers={"X-CSRF-Token": csrf}).status_code == 201

    assert client.post("/api/auth/logout").status_code == 204
    assert client.get("/api/auth/me").status_code == 401


def test_login_is_rate_limited_per_account(client):
    auth(client, "s@upenn.edu")  # its successful login counts toward the 10 attempts per 5 minutes
    for _ in range(9):
        assert client.post("/api/auth/login", json={"email": "s@upenn.edu", "password": "wrong-password"}).status_code == 401
    r = client.post("/api/auth/login", json={"email": "s@upenn.edu", "password": PASSWORD})
    assert r.status_code == 429 and "Retry-After" in r.headers
    # A different student on the same network (same IP) is unaffected.
    auth(client, "other@upenn.edu")


def test_metrics_count_only_verified_students(client):
    auth(client, "verified@upenn.edu")
    register(client, "unverified@upenn.edu")
    assert client.get("/api/metrics").json()["users"] == 1


def test_email_failures_are_logged_not_raised(monkeypatch, caplog):
    from app.core.config import settings
    monkeypatch.setattr(settings, "smtp_host", "127.0.0.1")
    monkeypatch.setattr(settings, "smtp_port", 1)  # nothing listens here
    with caplog.at_level("INFO", logger="campusconnect.email"):
        email.send("s@upenn.edu", "Subject", "Body")
    assert any("EMAIL FAILED to s@upenn.edu via 127.0.0.1:1" in r.getMessage() for r in caplog.records)
