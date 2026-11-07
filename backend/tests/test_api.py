def test_health_and_meta(client):
    assert client.get("/api/health").json()["status"] == "ok"
    meta = client.get("/api/meta").json()
    assert meta["features"] == {"auth": True, "uploads": False, "ai": True}


def test_items_crud(client):
    created = client.post("/api/items", json={"title": "Demo", "description": "x"})
    assert created.status_code == 201
    item_id = created.json()["id"]

    page = client.get("/api/items", params={"q": "dem"}).json()
    assert page["total"] == 1

    updated = client.patch(f"/api/items/{item_id}", json={"status": "done"}).json()
    assert updated["status"] == "done"
    assert updated["title"] == "Demo"

    assert client.delete(f"/api/items/{item_id}").status_code == 204
    missing = client.get(f"/api/items/{item_id}")
    assert missing.status_code == 404
    assert "not found" in missing.json()["detail"]


def test_items_validation(client):
    assert client.post("/api/items", json={"title": ""}).status_code == 422
    assert client.post("/api/items", json={"title": "a", "status": "nope"}).status_code == 422


def test_auth_flow(client):
    creds = {"email": "Team@Example.com", "password": "secret123", "name": "Team"}
    reg = client.post("/api/auth/register", json=creds)
    assert reg.status_code == 201
    assert client.post("/api/auth/register", json=creds).status_code == 409

    login = client.post(
        "/api/auth/login", json={"email": "team@example.com", "password": "secret123"}
    )
    token = login.json()["access_token"]
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.json()["email"] == "team@example.com"

    assert client.get("/api/auth/me").status_code == 401
    bad = client.post("/api/auth/login", json={"email": "team@example.com", "password": "wrong"})
    assert bad.status_code == 401


def test_ai_mock_without_key(client):
    res = client.post("/api/ai/chat", json={"messages": [{"role": "user", "content": "привет"}]})
    assert res.status_code == 200
    assert res.json()["mock"] is True
