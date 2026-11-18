from tests.helpers import auth
def test_auth_and_courses(client):
    headers = auth(client)
    assert client.get("/api/auth/me", headers=headers).json()["email"] == "one@upenn.edu"
    assert len(client.get("/api/courses?q=CIS").json()) == 1
    assert client.get("/api/auth/me").status_code == 401
    assert client.post("/api/auth/register", json={"email": "one@upenn.edu", "name": "Again", "password": "strong-password-123"}).status_code == 409

def test_open_group_endpoints_are_gone(client):
    headers = auth(client)
    assert client.post("/api/groups", json={"course_id": 1, "title": "Valid title"}, headers=headers).status_code in (404, 405)
    assert client.get("/api/groups").status_code in (404, 405)
    assert client.post("/api/groups/1/join", headers=headers).status_code == 404
    assert client.post("/api/groups/1/waitlist", headers=headers).status_code == 404
