from tests.helpers import auth
def test_auth_and_courses(client):
    headers = auth(client)
    assert client.get("/api/auth/me", headers=headers).json()["email"] == "one@upenn.edu"
    assert len(client.get("/api/courses?q=CIS").json()) == 1
    assert client.get("/api/auth/me").status_code == 401
    assert client.post("/api/auth/register", json={"email": "one@upenn.edu", "name": "Again", "password": "strong-password-123"}).status_code == 409

def test_group_crud_membership_and_permissions(client):
    owner = auth(client)
    other = auth(client, "two@upenn.edu")
    data = {"course_id": 1, "title": "Midterm prep", "description": "Meet at library", "max_members": 2}
    assert client.post("/api/groups", json=data).status_code == 401
    created = client.post("/api/groups", json=data, headers=owner)
    assert created.status_code == 201
    gid = created.json()["id"]
    assert created.json()["member_count"] == 1
    assert client.patch(f"/api/groups/{gid}", json={"title": "Changed"}, headers=other).status_code == 403
    assert client.post(f"/api/groups/{gid}/join", headers=other).status_code == 200
    assert client.post(f"/api/groups/{gid}/join", headers=other).status_code == 409
    assert client.patch(f"/api/groups/{gid}", json={"max_members": 1}, headers=owner).status_code == 422
    assert client.get("/api/groups?q=Midterm").json()["total"] == 1
    assert len(client.get(f"/api/groups/{gid}/members").json()) == 2
    assert client.delete(f"/api/groups/{gid}/members/me", headers=owner).status_code == 409
    assert client.delete(f"/api/groups/{gid}/members/me", headers=other).status_code == 204
    assert client.patch(f"/api/groups/{gid}", json={"title": "Updated"}, headers=owner).status_code == 200
    assert client.delete(f"/api/groups/{gid}", headers=owner).status_code == 204
    assert client.get(f"/api/groups/{gid}").status_code == 404

def test_validation_and_pagination(client):
    owner = auth(client)
    assert client.post("/api/groups", json={"course_id": 999, "title": "Valid title"}, headers=owner).status_code == 404
    assert client.post("/api/groups", json={"course_id": 1, "title": "x"}, headers=owner).status_code == 422
    assert client.get("/api/groups?page=0").status_code == 422
