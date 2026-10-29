import re
import time

from fastapi.testclient import TestClient
from main import create_app
from service import mailer
from service.database import connect
from test_accounts import PASSWORD, client, register  # noqa: F401  (client is a fixture)

NEW_PASSWORD = "a-brand-new-password"
GENERIC = "If an account exists for that address, we've sent a password reset link. Check your inbox and spam folder."

def outbox(client):
    path = client.app.state.data_dir / "outbox.log"
    return path.read_text(encoding="utf-8") if path.exists() else ""

def reset_tokens(client):
    return re.findall(r"/reset\.html\?token=([A-Za-z0-9_-]+)", outbox(client))

def forgot(client, email="one@example.com"):
    return client.post("/auth/password-reset-request", json={"email": email})

def reset(client, token, password=NEW_PASSWORD):
    return client.post("/auth/password-reset", json={"token": token, "password": password})

def login(client, password, email="one@example.com"):
    return client.post("/auth/login", json={"email": email, "password": password})

def age_resets(client, seconds):
    with connect(client.app.state.data_dir) as db:
        db.execute("UPDATE password_resets SET created_at=created_at-?", (seconds,))

def test_forgot_password_flow(client):
    register(client)
    client.post("/auth/logout")
    response = forgot(client, "  ONE@example.com ")
    assert response.status_code == 202 and response.json() == {"message": GENERIC}
    assert "Subject: Reset your Transcript Service password" in outbox(client)
    [token] = reset_tokens(client)
    assert "http://testserver/reset.html?token=" in outbox(client)
    response = reset(client, token)
    assert response.status_code == 200 and response.json()["email"] == "one@example.com"
    assert response.json()["email_verified"] is True
    assert client.get("/auth/me").json()["email_verified"] is True  # signed in, and the inbox is proven
    assert "Subject: Your Transcript Service password was changed" in outbox(client)
    client.post("/auth/logout")
    assert login(client, PASSWORD).status_code == 401
    assert login(client, NEW_PASSWORD).status_code == 200
    assert reset(client, token, "yet-another-password").status_code == 400  # links work once

def test_unknown_email_looks_the_same(client):
    register(client)
    known, unknown = forgot(client), forgot(client, "nobody@example.com")
    assert unknown.status_code == known.status_code == 202 and unknown.json() == known.json()
    assert "nobody@example.com" not in outbox(client)
    assert forgot(client, "not-an-email").status_code == 400

def test_bad_expired_and_short_password(client):
    register(client)
    forgot(client)
    [token] = reset_tokens(client)
    for bad in ("not-a-real-token", token[:-1]):
        response = reset(client, bad)
        assert response.status_code == 400 and "invalid, already used, or expired" in response.json()["error"]
    assert reset(client, token, "too-short").status_code == 400
    assert reset(client, "", NEW_PASSWORD).status_code == 400
    with connect(client.app.state.data_dir) as db:
        db.execute("UPDATE password_resets SET expires_at=?", (time.time() - 1,))
    assert reset(client, token).status_code == 400
    client.post("/auth/logout")
    assert login(client, PASSWORD).status_code == 200  # nothing changed

def test_reset_signs_out_everywhere(client, tmp_path):
    register(client)
    other = TestClient(client.app)  # a second browser signed in to the same account
    assert login(other, PASSWORD).status_code == 200 and other.get("/auth/me").status_code == 200
    forgot(client)
    second_link = reset_tokens(client)[0]
    age_resets(client, 61)
    forgot(client)
    [first, newest] = reset_tokens(client)
    assert reset(client, newest).status_code == 200
    assert other.get("/auth/me").status_code == 401
    assert client.get("/auth/me").status_code == 200
    assert reset(client, second_link).status_code == 400  # every outstanding link died with the change

def test_change_password_in_settings(client):
    register(client)
    other = TestClient(client.app)
    login(other, PASSWORD)
    forgot(client)
    [pending_link] = reset_tokens(client)
    wrong = client.post("/auth/password", json={"current_password": "not-my-password", "new_password": NEW_PASSWORD})
    assert wrong.status_code == 400 and "incorrect" in wrong.json()["error"]
    short = client.post("/auth/password", json={"current_password": PASSWORD, "new_password": "short"})
    assert short.status_code == 400
    ok = client.post("/auth/password", json={"current_password": PASSWORD, "new_password": NEW_PASSWORD})
    assert ok.status_code == 200 and ok.json() == {"changed": True}
    assert client.get("/auth/me").status_code == 200  # this browser stays signed in
    assert other.get("/auth/me").status_code == 401  # other devices are signed out
    assert reset(client, pending_link).status_code == 400
    assert "Subject: Your Transcript Service password was changed" in outbox(client)
    client.post("/auth/logout")
    assert login(client, NEW_PASSWORD).status_code == 200
    assert client.post("/auth/logout").status_code == 204
    assert client.post("/auth/password", json={"current_password": NEW_PASSWORD, "new_password": PASSWORD}).status_code == 401

def test_email_me_a_reset_link_from_settings(client):
    assert client.post("/auth/password-reset-email").status_code == 401
    register(client)
    assert client.post("/auth/password-reset-email").json() == {"sent": True}
    response = client.post("/auth/password-reset-email")
    assert response.status_code == 429 and "wait" in response.json()["error"] and response.headers["retry-after"]
    assert len(reset_tokens(client)) == 1

def test_reset_email_limits(client):
    register(client)
    for _ in range(5):
        assert forgot(client).status_code == 202
        age_resets(client, 61)
    assert forgot(client).status_code == 202  # still the same answer...
    assert len(reset_tokens(client)) == 5  # ...but no sixth email today
    response = client.post("/auth/password-reset-email")
    assert response.status_code == 429 and "too many" in response.json()["error"]
    forgot(client)
    assert len(reset_tokens(client)) == 5

def test_failed_send(client, monkeypatch):
    register(client)
    def broken(*args):
        raise mailer.MailError("smtp down")
    monkeypatch.setattr(mailer, "send", broken)
    assert forgot(client).status_code == 202  # never reveals the failure to a signed-out visitor
    response = client.post("/auth/password-reset-email")
    assert response.status_code == 503 and "couldn't send" in response.json()["error"]
    with connect(client.app.state.data_dir) as db:
        assert db.execute("SELECT COUNT(*) FROM password_resets").fetchone()[0] == 0  # failures don't count
    assert client.post("/auth/password", json={"current_password": PASSWORD, "new_password": NEW_PASSWORD}).status_code == 200
    monkeypatch.undo()
    assert client.post("/auth/password-reset-email").status_code == 200

def test_links_stored_hashed_and_cross_site_rejected(client):
    register(client)
    forgot(client)
    [token] = reset_tokens(client)
    assert token.encode() not in (client.app.state.data_dir / "accounts.sqlite3").read_bytes()
    assert client.post("/auth/password-reset", json={"token": token, "password": NEW_PASSWORD},
                       headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post("/auth/password-reset-request", json={"email": "one@example.com"},
                       headers={"Origin": "https://evil.example"}).status_code == 403
    assert reset(client, token).status_code == 200
