"""Password reset links and password-change bookkeeping. Hashing lives in auth.py."""
import hashlib
import logging
import math
import secrets
import time

from fastapi import HTTPException
from . import mailer, verification
from .database import connect

RESET_SECONDS = 60 * 60  # reset links are powerful, so they expire after an hour
RESEND_WAIT_SECONDS = 60
DAILY_LIMIT = 5  # reset emails per account per 24 hours
RESET_SUBJECT = "Reset your Transcript Service password"
RESET_BODY = """Hi,

Someone asked to reset the password for your Transcript Service account. To choose a new password, open this link:

{link}

The link works once and expires in 1 hour. If you did not ask for this, you can ignore this email; your password will not change.

This mailbox is not monitored, so please do not reply.
"""
CHANGED_SUBJECT = "Your Transcript Service password was changed"
CHANGED_BODY = """Hi,

The password for your Transcript Service account ({email}) was just changed, and other devices were signed out.

If this was you, there is nothing else to do. If it was not, reset your password right away:

{link}

This mailbox is not monitored, so please do not reply.
"""
log = logging.getLogger(__name__)

def hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()

def send_reset_link(data_dir, origin, user):
    """Email a reset link. Raises 429 if too soon or too many, 503 if sending fails."""
    token, now = secrets.token_urlsafe(32), time.time()
    with connect(data_dir) as db:
        db.execute("BEGIN IMMEDIATE")  # check the limits and reserve the send in one step
        recent = db.execute("SELECT created_at FROM password_resets WHERE user_id=? AND created_at>? ORDER BY created_at DESC",
                            (user["id"], now - 24 * 60 * 60)).fetchall()
        if recent and now - recent[0]["created_at"] < RESEND_WAIT_SECONDS:
            wait = math.ceil(RESEND_WAIT_SECONDS - (now - recent[0]["created_at"]))
            raise HTTPException(429, f"Please wait {wait} seconds before requesting another email.", headers={"Retry-After": str(wait)})
        if len(recent) >= DAILY_LIMIT:
            raise HTTPException(429, "You have requested too many password reset emails today. Try again tomorrow.")
        db.execute("DELETE FROM password_resets WHERE created_at<?", (now - 7 * 24 * 60 * 60,))
        db.execute("INSERT INTO password_resets VALUES (?, ?, ?, ?)", (hash_token(token), user["id"], now, now + RESET_SECONDS))
    try:
        mailer.send(data_dir, user["email"], RESET_SUBJECT, RESET_BODY.format(link=f"{origin}/reset.html?token={token}"))
    except mailer.MailError:
        log.exception("password reset email failed")
        with connect(data_dir) as db:  # a failed send does not count toward the limits
            db.execute("DELETE FROM password_resets WHERE token_hash=?", (hash_token(token),))
        raise HTTPException(503, "We couldn't send the email right now. Try again in a few minutes.")

def send_reset_link_quietly(data_dir, origin, email):
    """For the signed-out "forgot password" form: same result for unknown emails, limits and failures."""
    with connect(data_dir) as db:
        user = db.execute("SELECT id, email FROM users WHERE email=?", (email,)).fetchone()
    if user is None:
        return
    try:
        send_reset_link(data_dir, origin, dict(user))
    except HTTPException:
        pass  # limit reached or send failed (already logged); the response never reveals either

def use_reset_link(data_dir, token, password_hash):
    """Set the new password if the link is valid; returns the user. Signs the account out everywhere."""
    now = time.time()
    with connect(data_dir) as db:
        db.execute("BEGIN IMMEDIATE")  # so the same link cannot be used twice at once
        link = db.execute("SELECT r.user_id, u.email, u.created_at FROM password_resets r JOIN users u ON u.id=r.user_id WHERE r.token_hash=? AND r.expires_at>?",
                          (hash_token(token), now)).fetchone()
        if link is None:
            raise HTTPException(400, "This reset link is invalid, already used, or expired. Request a new one.")
        db.execute("UPDATE users SET password_hash=? WHERE id=?", (password_hash, link["user_id"]))
        forget_password(db, link["user_id"])
        # Opening a link from the inbox proves the address, so it also counts as email verification.
        verification.mark_verified(db, link["user_id"], link["email"])
        return {"id": link["user_id"], "email": link["email"], "created_at": link["created_at"]}

def forget_password(db, user_id, keep_session=None):
    """After a password change: no reset link may be used, and every other session is signed out."""
    db.execute("DELETE FROM password_resets WHERE user_id=?", (user_id,))
    db.execute("DELETE FROM sessions WHERE user_id=? AND token_hash IS NOT ?", (user_id, keep_session))

def notify_changed(data_dir, origin, email):
    try:
        mailer.send(data_dir, email, CHANGED_SUBJECT, CHANGED_BODY.format(email=email, link=f"{origin}/forgot.html"))
    except mailer.MailError:
        log.exception("password changed notice failed")  # the change itself already succeeded
