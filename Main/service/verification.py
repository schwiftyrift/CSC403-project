"""Email verification: emailed links that prove a user controls their address."""
import hashlib
import logging
import math
import os
import secrets
import time

from fastapi import HTTPException
from . import mailer
from .database import connect

LINK_SECONDS = 24 * 60 * 60
RESEND_WAIT_SECONDS = 60
DAILY_LIMIT = 5  # emails per account per 24 hours, so one account cannot use up the provider's free quota
KEEP_EXPIRED_SECONDS = 7 * 24 * 60 * 60  # old links still say "already verified" for a week, then are deleted
SUBJECT = "Verify your email for Transcript Service"
BODY = """Hi,

Please confirm your email address for Transcript Service by opening this link:

{link}

The link expires in 24 hours. If you did not create an account, you can ignore this email.

This mailbox is not monitored, so please do not reply.
"""
log = logging.getLogger(__name__)

def hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()

def public_origin(request):
    return (os.environ.get("PUBLIC_ORIGIN") or str(request.base_url)).rstrip("/")

def is_verified(db, user_id):
    # Verification belongs to an address: if the account's email ever changes, it is unverified again.
    return db.execute("SELECT 1 FROM verified_emails v JOIN users u ON u.id=v.user_id WHERE v.user_id=? AND v.email=u.email",
                      (user_id,)).fetchone() is not None

def mark_verified(db, user_id, email):
    db.execute("INSERT INTO verified_emails VALUES (?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET email=excluded.email, verified_at=excluded.verified_at",
               (user_id, email, time.time()))

def send_link(request, user):
    """Email a new verification link. Raises 409 if already verified, 429 if too soon or too many, 503 if sending fails."""
    data_dir = request.app.state.data_dir
    token, now = secrets.token_urlsafe(32), time.time()
    with connect(data_dir) as db:
        db.execute("BEGIN IMMEDIATE")  # check the limits and reserve the send in one step
        if is_verified(db, user["id"]):
            raise HTTPException(409, "Your email is already verified.")
        db.execute("DELETE FROM email_tokens WHERE expires_at<?", (now - KEEP_EXPIRED_SECONDS,))
        recent = db.execute("SELECT created_at FROM email_tokens WHERE user_id=? AND created_at>? ORDER BY created_at DESC",
                            (user["id"], now - 24 * 60 * 60)).fetchall()
        if recent and now - recent[0]["created_at"] < RESEND_WAIT_SECONDS:
            wait = math.ceil(RESEND_WAIT_SECONDS - (now - recent[0]["created_at"]))
            raise HTTPException(429, f"Please wait {wait} seconds before requesting another email.", headers={"Retry-After": str(wait)})
        if len(recent) >= DAILY_LIMIT:
            raise HTTPException(429, "You have requested too many verification emails today. Try again tomorrow.")
        db.execute("INSERT INTO email_tokens VALUES (?, ?, ?, ?, ?)", (hash_token(token), user["id"], user["email"], now, now + LINK_SECONDS))
    try:
        mailer.send(data_dir, user["email"], SUBJECT, BODY.format(link=f"{public_origin(request)}/verify.html?token={token}"))
    except mailer.MailError:
        log.exception("verification email failed")
        with connect(data_dir) as db:  # a failed send does not count toward the limits
            db.execute("DELETE FROM email_tokens WHERE token_hash=?", (hash_token(token),))
        raise HTTPException(503, "We couldn't send the verification email right now. Try again in a few minutes.")

def verify(data_dir, token):
    """Mark the link's address verified. Returns "verified" or "already_verified"; raises 400 for unusable links."""
    with connect(data_dir) as db:
        link = db.execute("SELECT t.user_id, t.email, t.expires_at, u.email AS current_email FROM email_tokens t JOIN users u ON u.id=t.user_id WHERE t.token_hash=?",
                          (hash_token(token),)).fetchone()
        if link is None or link["email"] != link["current_email"]:
            raise HTTPException(400, "This link is not valid. Log in and use Resend to get a new one.")
        if is_verified(db, link["user_id"]):
            return "already_verified"
        if link["expires_at"] < time.time():
            raise HTTPException(400, "This link has expired. Log in and use Resend to get a new one.")
        mark_verified(db, link["user_id"], link["email"])
        return "verified"
