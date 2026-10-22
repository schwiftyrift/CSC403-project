import time
import pytest
from fastapi.testclient import TestClient
from main import create_app
from service.database import connect
from service.jobs import ALLOWED, DEFAULT_MAX_MB

PASSWORD = "a-long-test-password"

@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        yield client

def register(client, email="one@example.com"):
    response = client.post("/auth/register", json={"email": email, "password": PASSWORD})
    assert response.status_code == 201
    return response.json()

def upload(client):
    response = client.post("/jobs", files={"file": ("audio.wav", b"audio", "audio/wav")})
    assert response.status_code == 201
    return response.json()["job_id"]

def test_login_logout_and_password_storage(client):
    user = register(client, " ONE@example.com ")
    assert user["email"] == "one@example.com"
    assert "password_hash" not in user
    cookie = client.cookies.get("transcript_session")
    with connect(client.app.state.data_dir) as db:
        stored = db.execute("SELECT password_hash FROM users").fetchone()[0]
        assert PASSWORD not in stored and stored.startswith("scrypt$")
        assert db.execute("SELECT token_hash FROM sessions").fetchone()[0] != cookie
    assert client.post("/auth/register", json={"email": user["email"], "password": PASSWORD}).status_code == 409
    assert client.post("/auth/logout").status_code == 204
    client.cookies.set("transcript_session", cookie)
    assert client.get("/auth/me").status_code == 401
    client.cookies.clear()
    assert client.post("/auth/login", json={"email": user["email"], "password": "wrong-password-value"}).status_code == 401
    assert client.post("/auth/login", json={"email": user["email"], "password": PASSWORD}).status_code == 200
    assert client.get("/auth/me").json()["id"] == user["id"]

def test_ownership_and_upload_history(client):
    register(client)
    job = upload(client)
    assert len(client.get("/jobs").json()) == 1
    assert client.get(f"/jobs/{job}/file").content == b"audio"
    client.post("/auth/logout")
    assert client.get("/jobs").status_code == 401
    register(client, "two@example.com")
    assert client.get("/jobs").json() == []
    for suffix in ("", "/file"):
        assert client.get(f"/jobs/{job}{suffix}").status_code == 404

def test_limits_expiry_and_csrf(client):
    assert client.post("/jobs", files={"file": ("a.wav", b"a")}).status_code == 401
    assert client.post("/auth/register", json={"email": "invalid", "password": PASSWORD}).status_code == 400
    assert client.post("/auth/register", json={"email": "ok@example.com", "password": "short"}).status_code == 400
    register(client)
    assert client.post("/jobs", files={"file": ("a.exe", b"a")}).status_code == 400
    client.app.state.max_bytes = 2
    assert client.post("/jobs", files={"file": ("a.wav", b"abc")}).status_code == 413
    assert list((client.app.state.data_dir / "uploads").iterdir()) == []
    assert client.get("/jobs?limit=101").status_code == 400
    assert client.get("/jobs/not-a-uuid").status_code == 400
    assert client.post("/auth/logout", headers={"Origin": "https://evil.example"}).status_code == 403
    with connect(client.app.state.data_dir) as db:
        db.execute("UPDATE sessions SET expires_at=?", (time.time() - 1,))
    assert client.get("/auth/me").status_code == 401

def test_persistence(tmp_path):
    with TestClient(create_app(tmp_path)) as first:
        register(first)
        job = upload(first)
        cookie = first.cookies.get("transcript_session")
    with TestClient(create_app(tmp_path)) as second:
        second.cookies.set("transcript_session", cookie)
        assert second.get("/auth/me").status_code == 200
        assert second.get("/jobs").json()[0]["job_id"] == job
        assert second.get(f"/jobs/{job}/file").content == b"audio"

def test_secure_cookie(tmp_path, monkeypatch):
    monkeypatch.setenv("COOKIE_SECURE", "true")
    with TestClient(create_app(tmp_path), base_url="https://testserver") as client:
        response = client.post("/auth/register", json={"email": "one@example.com", "password": PASSWORD})
        cookie = response.headers["set-cookie"].lower()
        assert "secure" in cookie and "httponly" in cookie and "samesite=strict" in cookie
        assert client.get("/auth/me").status_code == 200

def test_upload_limits_and_messages(client, tmp_path, monkeypatch):
    assert client.get("/jobs/limits").json() == {"extensions": list(ALLOWED), "max_bytes": DEFAULT_MAX_MB * 1024 * 1024}
    register(client)
    for name, content, status, message in [
        ("a.exe", b"a", 400, ".exe files are not supported"),
        ("noextension", b"a", 400, "has no extension"),
        ("empty.wav", b"", 400, "is empty"),
    ]:
        response = client.post("/jobs", files={"file": (name, content)})
        assert response.status_code == status and message in response.json()["error"]
    assert client.post("/jobs", files={"file": ("LOUD.WAV", b"a")}).status_code == 201
    client.app.state.max_bytes = 2
    response = client.post("/jobs", files={"file": ("a.wav", b"abc")})
    assert response.status_code == 413 and "Trim or compress" in response.json()["error"]
    assert len(list((client.app.state.data_dir / "uploads").iterdir())) == 1
    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    with TestClient(create_app(tmp_path / "other")) as other:
        assert other.get("/jobs/limits").json()["max_bytes"] == 1024 * 1024
