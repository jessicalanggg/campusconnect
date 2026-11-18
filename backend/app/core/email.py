"""Outgoing email. Uses SMTP when configured; otherwise logs the message (development and tests)."""
import logging
import smtplib
from collections import deque
from email.message import EmailMessage

from app.core.config import settings

log = logging.getLogger("campusconnect.email")
# Messages "sent" without SMTP configured, newest last. Lets development and tests read verification links.
OUTBOX: deque[EmailMessage] = deque(maxlen=100)


def send(to: str, subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = settings.email_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    if not settings.smtp_host:
        OUTBOX.append(msg)
        log.warning("SMTP not configured; email to %s not sent.\nSubject: %s\n%s", to, subject, body)
        return
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
        if settings.smtp_starttls:
            smtp.starttls()
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(msg)


def send_verification(to: str, name: str, token: str) -> None:
    link = f"{settings.app_base_url.rstrip('/')}/?verify={token}"
    send(to, "Verify your Penn email for CampusConnect",
         f"Hi {name},\n\nConfirm your Penn email to start getting matched with study groups:\n\n{link}\n\n"
         f"This link expires in {settings.verify_token_hours} hours. If you didn't sign up, ignore this email.\n")
