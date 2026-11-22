"""
Admin-only routes:
  POST  /admin/users           Create a new account
  PATCH /admin/users/{id}      Update (activate/deactivate) an account
  GET   /admin/users           List all accounts
  GET   /admin/questions        Question log (supports ?answered=false filter)
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.auth import require_role
from app.database import get_db
from app.models.db_models import QueryLog, User
from app.models.schemas import CreateUserRequest, PatchUserRequest, QueryLogOut, UserProfile

router = APIRouter(prefix="/admin", tags=["admin"])

_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
_admin_dep = Depends(require_role("admin"))


@router.post("/users", response_model=UserProfile, dependencies=[_admin_dep])
def create_user(req: CreateUserRequest, db: Session = Depends(get_db)):
    """Create a student or teacher account. Admin only."""
    existing = db.query(User).filter(User.college_id == req.college_id).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this college ID already exists.",
        )

    user = User(
        college_id=req.college_id.strip().lower(),
        name=req.name,
        password_hash=_pwd_ctx.hash(req.password),
        role=req.role,
        branch=req.branch,
        semester=req.semester,
        section=req.section,
        active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


@router.patch("/users/{user_id}", response_model=UserProfile, dependencies=[_admin_dep])
def update_user(user_id: str, req: PatchUserRequest, db: Session = Depends(get_db)):
    """Update account fields (e.g. activate/deactivate). Admin only."""
    user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

    if req.active is not None:
        user.active = req.active
    if req.name is not None:
        user.name = req.name
    if req.branch is not None:
        user.branch = req.branch
    if req.semester is not None:
        user.semester = req.semester
    if req.section is not None:
        user.section = req.section

    db.commit()
    db.refresh(user)
    return user


@router.get("/users", response_model=list[UserProfile], dependencies=[_admin_dep])
def list_users(db: Session = Depends(get_db)):
    """List all accounts. Admin only."""
    return db.query(User).order_by(User.created_at.desc()).all()


@router.get("/questions", response_model=list[QueryLogOut], dependencies=[_admin_dep])
def question_log(
    answered: bool | None = Query(None, description="Filter: true=answered, false=unanswered"),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    """
    Return the question log. Use ?answered=false to see what students
    asked that the system could not answer.
    """
    q = db.query(QueryLog).order_by(QueryLog.created_at.desc())
    if answered is not None:
        q = q.filter(QueryLog.answered == answered)
    return q.limit(limit).all()
