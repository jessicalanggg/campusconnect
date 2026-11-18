"""Authentication.

Browsers authenticate with an HttpOnly session cookie (JavaScript can't read it, so an XSS bug can't steal it).
Cookie-authenticated writes must also send an X-CSRF-Token header matching the readable `cc_csrf` cookie
(double-submit), so another site can't make a logged-in student's browser act for them.
API clients and tests may instead send `Authorization: Bearer <token>`; those requests carry no ambient
credentials, so they don't need the CSRF header.
"""
import hmac
import secrets
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import InvalidTokenError
from pwdlib import PasswordHash
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.entities import User

hasher = PasswordHash.recommended()
bearer = HTTPBearer(auto_error=False)
SESSION_COOKIE = "cc_session"
CSRF_COOKIE = "cc_csrf"
CSRF_HEADER = "X-CSRF-Token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def hash_password(password: str) -> str:
    return hasher.hash(password)


def verify_password(password: str, stored: str) -> bool:
    return hasher.verify(password, stored)


def _encode(payload: dict, lifetime: timedelta) -> str:
    return jwt.encode({**payload, "exp": datetime.now(timezone.utc) + lifetime}, settings.secret_key, algorithm="HS256")


def _decode(token: str, purpose: str) -> dict:
    payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    if payload.get("purpose") != purpose:
        raise InvalidTokenError("wrong token purpose")
    return payload


def make_token(user_id: int) -> str:
    return _encode({"sub": str(user_id), "purpose": "access"}, timedelta(minutes=settings.access_token_minutes))


def make_verify_token(user: User) -> str:
    # Bound to the email so a token can't verify an address the account no longer has.
    return _encode({"sub": str(user.id), "purpose": "verify_email", "email": user.email},
                   timedelta(hours=settings.verify_token_hours))


def read_verify_token(token: str) -> tuple[int, str]:
    try:
        payload = _decode(token, "verify_email")
        return int(payload["sub"]), payload["email"]
    except (InvalidTokenError, KeyError, ValueError, TypeError):
        raise HTTPException(400, "This verification link is invalid or has expired") from None


def set_session_cookies(response: Response, token: str) -> None:
    max_age = settings.access_token_minutes * 60
    common = {"max_age": max_age, "secure": settings.cookie_secure, "samesite": "lax", "path": "/"}
    response.set_cookie(SESSION_COOKIE, token, httponly=True, **common)
    response.set_cookie(CSRF_COOKIE, secrets.token_urlsafe(32), httponly=False, **common)


def clear_session_cookies(response: Response) -> None:
    for name in (SESSION_COOKIE, CSRF_COOKIE):
        response.delete_cookie(name, path="/", secure=settings.cookie_secure, samesite="lax")


def _token_from_request(request: Request, credentials: HTTPAuthorizationCredentials | None) -> str | None:
    if credentials is not None:
        return credentials.credentials
    token = request.cookies.get(SESSION_COOKIE)
    if token and request.method not in SAFE_METHODS:
        sent, expected = request.headers.get(CSRF_HEADER, ""), request.cookies.get(CSRF_COOKIE, "")
        if not expected or not hmac.compare_digest(sent, expected):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "CSRF check failed; refresh the page and try again")
    return token


def current_user(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
                 db: Session = Depends(get_db)) -> User:
    token = _token_from_request(request, credentials)
    if token is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Authentication required")
    try:
        uid = int(_decode(token, "access")["sub"])
    except (InvalidTokenError, KeyError, ValueError, TypeError):
        raise HTTPException(401, "Invalid or expired session") from None
    user = db.get(User, uid)
    if not user:
        raise HTTPException(401, "Account no longer exists")
    if user.email_verified_at is None:  # defence in depth; login already refuses unverified accounts
        raise HTTPException(403, "Verify your Penn email first")
    return user


def optional_user(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
                  db: Session = Depends(get_db)) -> User | None:
    """Like current_user, but anonymous (or expired) requests get None instead of an error."""
    try:
        return current_user(request, credentials, db)
    except HTTPException:
        return None


def admin_user(user: User = Depends(current_user)) -> User:
    if not settings.is_admin(user.email):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin access required")
    return user
