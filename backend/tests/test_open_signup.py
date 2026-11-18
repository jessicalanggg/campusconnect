"""Open sign-up (the default): any email address, no verification step."""
import pytest

from app.core import email
from app.core.config import settings
from tests.helpers import PASSWORD


@pytest.fixture
def open_signup(monkeypatch):
    monkeypatch.setattr(settings, "allowed_email_domains", "*")
    monkeypatch.setattr(settings, "require_email_verification", False)


def test_defaults_are_open():
    from app.core.config import Settings
    defaults = Settings(_env_file=None, allowed_email_domains="*", require_email_verification=False)
    assert Settings.model_fields["allowed_email_domains"].default == "*"
    assert Settings.model_fields["require_email_verification"].default is False
    assert defaults.email_allowed("anyone@gmail.com") and defaults.allowed_domains() == []


def test_any_email_can_sign_up_and_sign_in_immediately(client, open_signup):
    assert client.get("/api/config").json() == {"allowed_email_domains": [], "require_email_verification": False}
    r = client.post("/api/auth/register", json={"email": "sam@gmail.com", "name": "Sam", "password": PASSWORD})
    assert r.status_code == 201 and r.json()["verification_required"] is False
    assert len(email.OUTBOX) == 0  # no verification email is sent
    login = client.post("/api/auth/login", json={"email": "sam@gmail.com", "password": PASSWORD})
    assert login.status_code == 200
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    client.cookies.clear()
    assert client.get("/api/auth/me", headers=headers).json()["email"] == "sam@gmail.com"
    m = client.get("/api/metrics").json()
    assert m["users"] == 1 and m["verified_users"] == 0


def test_domain_list_still_restricts_when_set(client, monkeypatch, open_signup):
    monkeypatch.setattr(settings, "allowed_email_domains", "upenn.edu,drexel.edu")
    assert client.get("/api/config").json()["allowed_email_domains"] == ["upenn.edu", "drexel.edu"]
    bad = client.post("/api/auth/register", json={"email": "x@gmail.com", "name": "X", "password": PASSWORD})
    assert bad.status_code == 422 and "@upenn.edu, @drexel.edu" in bad.json()["detail"]
    ok = client.post("/api/auth/register", json={"email": "x@drexel.edu", "name": "X", "password": PASSWORD})
    assert ok.status_code == 201
