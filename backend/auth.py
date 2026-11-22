"""
Authentication and authorization dependencies for FastAPI routes.

Usage
-----
- `Depends(get_current_user)`      → returns the authenticated User ORM object
- `Depends(require_role("admin"))` → raises 403 if the user is not an admin
"""
from datetime import datetime, timedelta, timezone
from typing import Annotated

import jwt
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from backend import config
from backend.database import get_db
from backend.models.db_models import User

_bearer = HTTPBearer(auto_error=False)


# ── Token creation ─────────────────────────────────────────────────────────────

def create_access_token(user_id: str) -> str:
    """Sign and return a JWT for the given user ID."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=config.JWT_EXPIRE_MINUTES)
    payload = {"sub": user_id, "exp": expire}
    return jwt.encode(payload, config.JWT_SECRET, algorithm="HS256")


def create_preview_token(user_id: str, document_id: str, version: int) -> str:
    """Sign a short-lived (5 min) preview-only JWT."""
    expire = datetime.now(timezone.utc) + timedelta(minutes=5)
    payload = {
        "sub": user_id,
        "aud": "preview",
        "document_id": document_id,
        "version": version,
        "exp": expire,
    }
    return jwt.encode(payload, config.JWT_SECRET, algorithm="HS256")


# ── Current user dependency ───────────────────────────────────────────────────

async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: Session = Depends(get_db),
) -> User:
    """
    Decode the Bearer JWT, load the User from SQLite, verify they are active.
    Raises HTTP 401 on any failure — never reveals which check failed.
    """
    exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if not credentials:
        raise exc

    try:
        payload = jwt.decode(
            credentials.credentials,
            config.JWT_SECRET,
            algorithms=["HS256"],
            options={"require": ["sub", "exp"]},
        )
        user_id: str = payload["sub"]
    except jwt.PyJWTError:
        raise exc

    user = db.get(User, user_id)
    if user is None or not user.active:
        raise exc

    return user


# ── Role guard ────────────────────────────────────────────────────────────────

def require_role(*roles: str):
    """
    Returns a FastAPI dependency that ensures the current user holds one of the
    given roles.  Use as:  `Depends(require_role("admin"))`.
    """
    async def _check(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to perform this action.",
            )
        return user
    return _check


# ── Preview token decoder ─────────────────────────────────────────────────────

def decode_preview_token(token: str, db: Session) -> tuple[User, str, int]:
    """
    Decode a preview JWT.  Returns (user, document_id, version).
    Raises HTTP 403 if the token is invalid, expired, wrong audience,
    or the user is inactive.
    """
    exc = HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")
    try:
        payload = jwt.decode(
            token,
            config.JWT_SECRET,
            algorithms=["HS256"],
            audience="preview",
            options={"require": ["sub", "exp", "aud", "document_id", "version"]},
        )
    except jwt.PyJWTError:
        raise exc

    user = db.get(User, payload["sub"])
    if user is None or not user.active:
        raise exc

    return user, payload["document_id"], payload["version"]
