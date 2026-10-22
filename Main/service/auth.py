"""Password hashing, revocable sessions, and reusable authentication dependency."""
import hashlib
import hmac
import secrets
import sqlite3
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field, field_validator
from . import verification
from .database import connect

router = APIRouter(prefix="/auth", tags=["accounts"])
COOKIE = "transcript_session"
SESSION_SECONDS = 60 * 60 * 24 * 7

class Credentials(BaseModel):
    email: str = Field(max_length=254)
    password: str = Field(min_length=12, max_length=128)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value):
        value = value.strip().lower()
        local, separator, domain = value.partition("@")
        if not separator or not local or "." not in domain or "@" in domain or any(c.isspace() for c in value):
            raise ValueError("invalid email")
        return value

class VerificationLink(BaseModel):
    token: str = Field(min_length=1, max_length=128)

def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return f"scrypt$16384$8$1${salt}${digest}"

def verify_password(password, encoded):
    return hmac.compare_digest(hash_password(password, encoded.split("$")[4]), encoded)

DUMMY_HASH = hash_password("dummy-password-for-timing")

def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()

def current_user(request: Request):
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(401, "authentication required")
    with connect(request.app.state.data_dir) as db:
        user = db.execute("SELECT u.id, u.email, u.created_at FROM users u JOIN sessions s ON s.user_id=u.id WHERE s.token_hash=? AND s.expires_at>?", (token_hash(token), time.time())).fetchone()
    if user is None:
        raise HTTPException(401, "session expired or invalid")
    return dict(user)

def start_session(request, response, user_id):
    token = secrets.token_urlsafe(32)
    with connect(request.app.state.data_dir) as db:
        db.execute("DELETE FROM sessions WHERE expires_at<=?", (time.time(),))
        old = request.cookies.get(COOKIE)
        if old:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash(old),))
        db.execute("INSERT INTO sessions VALUES (?, ?, ?)", (token_hash(token), user_id, time.time() + SESSION_SECONDS))
    response.set_cookie(COOKIE, token, max_age=SESSION_SECONDS, httponly=True,
                        secure=request.app.state.cookie_secure, samesite="strict", path="/")
    response.headers["Cache-Control"] = "no-store"

@router.post("/register", status_code=201)
def register(body: Credentials, request: Request, response: Response):
    user = {"id": str(uuid.uuid4()), "email": body.email, "created_at": time.time()}
    password_hash = hash_password(body.password)
    try:
        with connect(request.app.state.data_dir) as db:
            db.execute("INSERT INTO users VALUES (?, ?, ?, ?)", (user["id"], user["email"], password_hash, user["created_at"]))
    except sqlite3.IntegrityError:
        raise HTTPException(409, "email already registered")
    start_session(request, response, user["id"])
    try:
        verification.send_link(request, user)
        sent = True
    except HTTPException:
        sent = False  # the account still works; the user can resend from the banner
    return {**user, "email_verified": False, "verification_sent": sent}

@router.post("/login")
def login(body: Credentials, request: Request, response: Response):
    with connect(request.app.state.data_dir) as db:
        row = db.execute("SELECT * FROM users WHERE email=?", (body.email,)).fetchone()
        verified = row is not None and verification.is_verified(db, row["id"])
    valid = verify_password(body.password, row["password_hash"] if row else DUMMY_HASH)
    if not valid or row is None:
        raise HTTPException(401, "invalid email or password")
    start_session(request, response, row["id"])
    return {**{key: row[key] for key in ("id", "email", "created_at")}, "email_verified": verified}

@router.get("/me")
def me(request: Request, user=Depends(current_user)):
    with connect(request.app.state.data_dir) as db:
        return {**user, "email_verified": verification.is_verified(db, user["id"])}

@router.post("/verify")
def verify_email(body: VerificationLink, request: Request):
    # No login needed: the link may be opened on a different device than the one signed in.
    return {"status": verification.verify(request.app.state.data_dir, body.token)}

@router.post("/verification-email")
def resend_verification(request: Request, user=Depends(current_user)):
    verification.send_link(request, user)
    return {"sent": True}

@router.post("/logout", status_code=204)
def logout(request: Request, response: Response):
    token = request.cookies.get(COOKIE)
    if token:
        with connect(request.app.state.data_dir) as db:
            db.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash(token),))
    response.delete_cookie(COOKIE, path="/", secure=request.app.state.cookie_secure, httponly=True, samesite="strict")
