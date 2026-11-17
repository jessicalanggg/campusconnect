from datetime import datetime, timedelta, timezone
import jwt
from jwt import InvalidTokenError
from pwdlib import PasswordHash
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from app.core.config import settings
from app.db.session import get_db
from app.models.entities import User

hasher = PasswordHash.recommended()
bearer = HTTPBearer(auto_error=False)

def hash_password(password: str) -> str:
    return hasher.hash(password)

def verify_password(password: str, stored: str) -> bool:
    return hasher.verify(password, stored)

def make_token(user_id: int) -> str:
    return jwt.encode({"sub": str(user_id), "exp": datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_minutes)}, settings.secret_key, algorithm="HS256")

def current_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer), db: Session = Depends(get_db)) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication required")
    try:
        payload = jwt.decode(credentials.credentials, settings.secret_key, algorithms=["HS256"])
        uid = int(payload["sub"])
    except (InvalidTokenError, KeyError, ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Invalid or expired token") from None
    user = db.get(User, uid)
    if not user:
        raise HTTPException(status_code=401, detail="Account no longer exists")
    return user

def optional_user(credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
                  db: Session = Depends(get_db)) -> User | None:
    """Like current_user, but anonymous (or expired) requests get None instead of a 401."""
    if credentials is None:
        return None
    try:
        return current_user(credentials, db)
    except HTTPException:
        return None

def admin_user(user: User = Depends(current_user)) -> User:
    if not settings.is_admin(user.email):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user
