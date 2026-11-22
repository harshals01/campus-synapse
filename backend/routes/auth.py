"""
Auth routes:  POST /auth/login   GET /auth/me
"""
import time
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Request, status
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.auth import create_access_token, get_current_user
from app.database import get_db
from app.models.db_models import User
from app.models.schemas import LoginRequest, TokenResponse, UserProfile

router = APIRouter(tags=["auth"])

_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Simple in-memory rate limiter: {ip: [timestamp, ...]}
_login_attempts: dict[str, list[float]] = defaultdict(list)
_MAX_ATTEMPTS = 5
_WINDOW_SECONDS = 60


def _rate_limit(ip: str) -> None:
    now = time.time()
    attempts = [t for t in _login_attempts[ip] if now - t < _WINDOW_SECONDS]
    _login_attempts[ip] = attempts
    if len(attempts) >= _MAX_ATTEMPTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Please wait a minute.",
        )
    _login_attempts[ip].append(now)


@router.post("/login", response_model=TokenResponse)
def login(req: LoginRequest, request: Request, db: Session = Depends(get_db)):
    """Authenticate with college email + password, return a JWT."""
    client_ip = request.client.host if request.client else "unknown"
    _rate_limit(client_ip)

    # Generic error message — never reveal which field was wrong.
    _auth_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid credentials.",
    )

    user = db.query(User).filter(User.college_id == req.college_id).first()
    if user is None:
        raise _auth_error
    if not user.active:
        raise _auth_error
    if not _pwd_ctx.verify(req.password, user.password_hash):
        raise _auth_error

    token = create_access_token(user.id)
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserProfile)
def me(current_user: User = Depends(get_current_user)):
    """Return the authenticated user's profile."""
    return current_user
