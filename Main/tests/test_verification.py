import re
import time

import pytest
from fastapi.testclient import TestClient
from main import create_app
from service import mailer
from service.database import connect
from test_accounts import PASSWORD, client, register  # noqa: F401  (client is a fixture)

def outbox(client):
    path = client.app.state.data_dir / "outbox.log"
    return path.read_text(encoding="utf-8") if path.exists() else ""

def links(client):
    return re.findall(r"(\S+/verify\.html\?token=([A-Za-z0-9_-]+))", outbox(client))

def verify(client, token):
    return client.post("/auth/verify", json={"token": token})

def age_links(client, seconds):
    with connect(client.app.state.data_dir) as db:
        db.execute("UPDATE email_tokens SET created_at=created_at-?", (seconds,))

def test_signup_sends_link_that_verifies(client):
    user = register(client)
    assert user["email_verified"] is False and user["verification_sent"] is True
    mail = outbox(client)
    assert "To: one@example.com" in mail and "Subject: Verify your email for Transcript Service" in mail
    [(link, token)] = links(client)
    assert link.startswith("http://testserver/verify.html?token=")
    assert client.get("/auth/me").json()["email_verified"] is False
    assert verify(client, token).json() == {"status": "verified"}
    assert client.get("/auth/me").json()["email_verified"] is True
    assert verify(client, token).json() == {"status": "already_verified"}
    client.post("/auth/logout")
    assert client.post("/auth/login", json={"email": "one@example.com", "password": PASSWORD}).json()["email_verified"] is True

def test_link_works_without_being_signed_in(client):
    register(client)
    client.post("/auth/logout")
    [(_, token)] = links(client)
    assert verify(client, token).json() == {"status": "verified"}

def test_bad_and_expired_links(client):
    register(client)
    [(_, token)] = links(client)
    for bad in ("not-a-real-token", token[:-1]):
        response = verify(client, bad)
        assert response.status_code == 400 and "not valid" in response.json()["error"]
    assert verify(client, "").status_code == 400
    assert verify(client, "x" * 129).status_code == 400
    with connect(client.app.state.data_dir) as db:
        db.execute("UPDATE email_tokens SET expires_at=?", (time.time() - 1,))
    response = verify(client, token)
    assert response.status_code == 400 and "expired" in response.json()["error"]
    assert client.get("/auth/me").json()["email_verified"] is False
    age_links(client, 3600)
    assert client.post("/auth/verification-email").status_code == 200
    new_token = links(client)[-1][1]
    assert verify(client, new_token).json() == {"status": "verified"}
    assert verify(client, token).json() == {"status": "already_verified"}  # expired, but nothing left to do

def test_resend_wait_and_daily_limit(client):
    assert client.post("/auth/verification-email").status_code == 401
    register(client)
    response = client.post("/auth/verification-email")
    assert response.status_code == 429 and "wait" in response.json()["error"]
    assert 1 <= int(response.headers["retry-after"]) <= 60
    for _ in range(4):  # sign-up email plus four resends = the daily limit of 5
        age_links(client, 61)
        assert client.post("/auth/verification-email").status_code == 200
    age_links(client, 61)
    response = client.post("/auth/verification-email")
    assert response.status_code == 429 and "too many" in response.json()["error"]
    assert len(links(client)) == 5
    first, last = links(client)[0][1], links(client)[-1][1]
    assert verify(client, first).json() == {"status": "verified"}  # older links keep working
    assert verify(client, last).json() == {"status": "already_verified"}
    assert client.post("/auth/verification-email").status_code == 409

def test_failed_send_does_not_block_signup_or_count(client, monkeypatch):
    def broken(*args):
        raise mailer.MailError("smtp down")
    monkeypatch.setattr(mailer, "send", broken)
    user = register(client)
    assert user["verification_sent"] is False and client.get("/auth/me").status_code == 200
    response = client.post("/auth/verification-email")
    assert response.status_code == 503 and "couldn't send" in response.json()["error"]
    with connect(client.app.state.data_dir) as db:
        assert db.execute("SELECT COUNT(*) FROM email_tokens").fetchone()[0] == 0
    monkeypatch.undo()
    assert client.post("/auth/verification-email").status_code == 200  # no wait imposed by the failures

def test_links_tied_to_address_and_stored_hashed(client):
    register(client)
    [(_, token)] = links(client)
    assert token.encode() not in (client.app.state.data_dir / "accounts.sqlite3").read_bytes()
    with connect(client.app.state.data_dir) as db:
        db.execute("UPDATE users SET email='changed@example.com'")
    assert verify(client, token).status_code == 400
    with connect(client.app.state.data_dir) as db:
        db.execute("UPDATE users SET email='one@example.com'")
    assert verify(client, token).json() == {"status": "verified"}
    with connect(client.app.state.data_dir) as db:
        db.execute("UPDATE users SET email='changed@example.com'")
    assert client.get("/auth/me").json()["email_verified"] is False

def test_existing_accounts_start_unverified(client):
    register(client)
    with connect(client.app.state.data_dir) as db:  # as if created before email verification existed
        db.execute("DELETE FROM email_tokens")
    assert client.get("/auth/me").json()["email_verified"] is False
    assert client.post("/auth/verification-email").status_code == 200

def test_verify_rejects_cross_site_requests(client):
    register(client)
    [(_, token)] = links(client)
    assert client.post("/auth/verify", json={"token": token}, headers={"Origin": "https://evil.example"}).status_code == 403

class FakeSMTP:
    sent = []
    def __init__(self, host, port, timeout=None, context=None):
        self.calls = [("connect", host, port)]
    def __enter__(self):
        return self
    def __exit__(self, *exc):
        FakeSMTP.sent.append(self.calls)
    def starttls(self, context=None):
        self.calls.append(("starttls",))
    def login(self, user, password):
        self.calls.append(("login", user, password))
    def send_message(self, message):
        self.calls.append(("send", message["From"], message["To"], message["Subject"]))

def smtp_env(monkeypatch, port):
    for name, value in {"SMTP_HOST": "smtp.resend.com", "SMTP_PORT": port, "SMTP_USER": "resend",
                        "SMTP_PASSWORD": "secret", "MAIL_FROM": "Transcript Service <no-reply@mail.example.com>"}.items():
        monkeypatch.setenv(name, value)

def test_sends_through_smtp_when_configured(tmp_path, monkeypatch):
    FakeSMTP.sent = []
    monkeypatch.setattr(mailer.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(mailer.smtplib, "SMTP_SSL", FakeSMTP)
    smtp_env(monkeypatch, "587")
    with TestClient(create_app(tmp_path)) as client:
        register(client)
        smtp_env(monkeypatch, "465")
        register(client, "two@example.com")
    assert FakeSMTP.sent[0] == [("connect", "smtp.resend.com", 587), ("starttls",), ("login", "resend", "secret"),
                                ("send", "Transcript Service <no-reply@mail.example.com>", "one@example.com", "Verify your email for Transcript Service")]
    assert FakeSMTP.sent[1][0] == ("connect", "smtp.resend.com", 465) and ("starttls",) not in FakeSMTP.sent[1]
    assert not (tmp_path / "outbox.log").exists()

def test_real_smtp_failure_is_reported(tmp_path, monkeypatch):
    smtp_env(monkeypatch, "587")
    monkeypatch.setenv("SMTP_HOST", "127.0.0.1")
    monkeypatch.setenv("SMTP_PORT", "9")  # nothing listens here: connection refused
    with TestClient(create_app(tmp_path)) as client:
        assert register(client)["verification_sent"] is False

def test_startup_rejects_half_configured_email(tmp_path, monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.resend.com")
    with pytest.raises(RuntimeError, match="MAIL_FROM"):
        with TestClient(create_app(tmp_path)):
            pass
    monkeypatch.setenv("MAIL_FROM", "no-reply@mail.example.com")
    monkeypatch.setenv("SMTP_PORT", "five-eight-seven")
    with pytest.raises(RuntimeError, match="SMTP_PORT"):
        with TestClient(create_app(tmp_path)):
            pass

def test_public_origin_setting(tmp_path, monkeypatch):
    monkeypatch.setenv("PUBLIC_ORIGIN", "")  # what docker-compose passes when it is not configured
    with TestClient(create_app(tmp_path)) as client:
        response = client.post("/auth/register", json={"email": "one@example.com", "password": PASSWORD},
                               headers={"Origin": "http://testserver"})
        assert response.status_code == 201
        assert links(client)[0][0].startswith("http://testserver/verify.html?token=")
    monkeypatch.setenv("PUBLIC_ORIGIN", "https://transcripts.example.com/")
    with TestClient(create_app(tmp_path / "other"), base_url="https://transcripts.example.com") as client:
        response = client.post("/auth/register", json={"email": "one@example.com", "password": PASSWORD},
                               headers={"Origin": "https://transcripts.example.com"})
        assert response.status_code == 201
        assert links(client)[0][0].startswith("https://transcripts.example.com/verify.html?token=")
