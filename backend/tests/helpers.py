"""Test helpers: create verified Penn accounts the way a real student would."""
import re

from app.core import email

PASSWORD = "strong-password-123"


def verification_token(address: str) -> str:
    msg = next(m for m in reversed(email.OUTBOX) if m["To"] == address)
    return re.search(r"verify=([\w.\-]+)", msg.get_content()).group(1)


def register(client, address, name="Student"):
    r = client.post("/api/auth/register", json={"email": address, "name": name, "password": PASSWORD})
    assert r.status_code == 201, r.text
    return r


def auth(client, address="one@upenn.edu", name="Student"):
    """Register, follow the emailed verification link, log in; return bearer headers.

    Login also sets session cookies on the shared TestClient; they're cleared so each test request is
    authenticated only by the headers it passes.
    """
    register(client, address, name)
    assert client.post("/api/auth/verify", json={"token": verification_token(address)}).status_code == 200
    r = client.post("/api/auth/login", json={"email": address, "password": PASSWORD})
    assert r.status_code == 200, r.text
    client.cookies.clear()
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
