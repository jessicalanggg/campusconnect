"""Outgoing email.

Delivery, in order of preference:
  1. Resend's HTTPS API when RESEND_API_KEY is set (works on hosts that block outgoing SMTP ports, like Render's
     free plan),
  2. SMTP when SMTP_HOST is set,
  3. otherwise the message is logged and kept in OUTBOX (development and tests).
"""
import json
import logging
import smtplib
import threading
import urllib.error
import urllib.request
from collections import deque
from email.message import EmailMessage

from app.core.config import settings

log = logging.getLogger("campusconnect.email")
# Messages "sent" without a provider configured, newest last. Lets development and tests read verification links.
OUTBOX: deque[EmailMessage] = deque(maxlen=100)
RESEND_URL = "https://api.resend.com/emails"


def provider() -> str:
    return "resend" if settings.resend_api_key else "smtp" if settings.smtp_host else "log"


def _message(to: str, subject: str, body: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = settings.email_from
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    return msg


def _send_resend(msg: EmailMessage) -> None:
    payload = json.dumps({"from": msg["From"], "to": [msg["To"]], "subject": msg["Subject"],
                          "text": msg.get_content()}).encode()
    req = urllib.request.Request(RESEND_URL, data=payload, method="POST", headers={
        "Authorization": f"Bearer {settings.resend_api_key}", "Content-Type": "application/json",
        "User-Agent": "campusconnect"})
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read()
    except urllib.error.HTTPError as exc:  # include Resend's explanation (e.g. unverified domain)
        raise RuntimeError(f"HTTP {exc.code}: {exc.read()[:300].decode(errors='replace')}") from None


def _send_smtp(msg: EmailMessage) -> None:
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
        if settings.smtp_starttls:
            smtp.starttls()
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(msg)


def send(to: str, subject: str, body: str) -> bool:
    msg = _message(to, subject, body)
    how = provider()
    if how == "log":
        OUTBOX.append(msg)
        log.warning("No email provider configured; email to %s not sent.\nSubject: %s\n%s", to, subject, body)
        return False
    via = "Resend" if how == "resend" else f"{settings.smtp_host}:{settings.smtp_port}"
    try:
        _send_resend(msg) if how == "resend" else _send_smtp(msg)
    except Exception as exc:
        # Runs after the response (or in a background thread), so log loudly: this is the only trace of a failure.
        log.error("EMAIL FAILED to %s via %s (%s: %s)", to, via, type(exc).__name__, exc)
        return False
    log.info("EMAIL SENT to %s via %s", to, via)
    return True


def send_all(messages: list[tuple[str, str, str]]) -> None:
    """Send (to, subject, body) messages without holding up the caller: in a background thread when they go over
    the network, inline when they're only logged."""
    if not messages:
        return
    if provider() == "log":
        for m in messages:
            send(*m)
        return
    threading.Thread(target=lambda: [send(*m) for m in messages], daemon=True, name="email").start()


def send_verification(to: str, name: str, token: str) -> None:
    link = f"{settings.app_base_url.rstrip('/')}/?verify={token}"
    send(to, "Verify your Penn email for CampusConnect",
         f"Hi {name},\n\nConfirm your Penn email to start getting matched with study groups:\n\n{link}\n\n"
         f"This link expires in {settings.verify_token_hours} hours. If you didn't sign up, ignore this email.\n")
