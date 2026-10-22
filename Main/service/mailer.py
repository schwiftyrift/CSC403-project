"""Outgoing email over SMTP; without SMTP_HOST, messages go to DATA_DIR/outbox.log for development."""
import logging
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formatdate, make_msgid, parseaddr

log = logging.getLogger(__name__)
SETTINGS = ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "MAIL_FROM")

class MailError(Exception):
    """The message could not be handed to the SMTP server."""

def settings():
    # Empty values count as unset, so docker-compose can pass ${VAR:-} without breaking anything.
    return {name: (os.environ.get(name) or "").strip() for name in SETTINGS}

def check_settings():
    """Called at startup so a half-finished configuration fails immediately, not on the first sign-up."""
    config = settings()
    if not config["SMTP_HOST"]:
        log.warning("SMTP_HOST is not set; emails will be written to outbox.log instead of being sent")
        return
    if not config["MAIL_FROM"]:
        raise RuntimeError("MAIL_FROM must be set when SMTP_HOST is set")
    if config["SMTP_PORT"] and not config["SMTP_PORT"].isdigit():
        raise RuntimeError("SMTP_PORT must be a number, usually 587")

def send(data_dir, to, subject, body):
    config = settings()
    sender = config["MAIL_FROM"] or "Transcript Service <no-reply@localhost>"
    message = EmailMessage()
    message["From"] = sender
    message["To"] = to
    message["Subject"] = subject
    message["Date"] = formatdate(usegmt=True)
    # Passing the domain avoids make_msgid's hostname lookup, which can stall for seconds.
    message["Message-ID"] = make_msgid(domain=parseaddr(sender)[1].rpartition("@")[2] or "localhost")
    message.set_content(body, cte="7bit")  # plain text, so links are never split or re-encoded
    if not config["SMTP_HOST"]:
        with (data_dir / "outbox.log").open("a", encoding="utf-8") as outbox:
            outbox.write(message.as_string() + "\n" + "=" * 72 + "\n")
        return
    port = int(config["SMTP_PORT"] or 587)
    context = ssl.create_default_context()
    try:
        # Port 465 is TLS from the start; other ports (normally 587) upgrade with STARTTLS.
        if port == 465:
            server = smtplib.SMTP_SSL(config["SMTP_HOST"], port, timeout=15, context=context)
        else:
            server = smtplib.SMTP(config["SMTP_HOST"], port, timeout=15)
        with server:
            if port != 465:
                server.starttls(context=context)
            if config["SMTP_USER"]:
                server.login(config["SMTP_USER"], config["SMTP_PASSWORD"])
            server.send_message(message)
    except (OSError, smtplib.SMTPException) as exc:
        raise MailError(f"could not send email to {to}: {exc}") from exc
