"""
Seed script — creates demo accounts for each role.
Run once after the backend has started at least once (to create the DB tables).

Usage:
    python -m backend.seed
"""
from passlib.context import CryptContext
from backend.database import SessionLocal
from backend.models.db_models import User, Base
from backend.database import engine

Base.metadata.create_all(bind=engine)

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")


DEMO_USERS = [
    # Admin
    {
        "college_id": "admin@bitmesra.ac.in",
        "name": "Admin User",
        "password": "admin123",
        "role": "admin",
        "branch": None,
        "semester": None,
        "section": None,
    },
    # Teacher
    {
        "college_id": "teacher.cse@bitmesra.ac.in",
        "name": "Dr. Sharma (CSE)",
        "password": "teacher123",
        "role": "teacher",
        "branch": "CSE",
        "semester": None,
        "section": None,
    },
    # Students
    {
        "college_id": "student.cse5a@bitmesra.ac.in",
        "name": "Alice (CSE Sem 5 A)",
        "password": "student123",
        "role": "student",
        "branch": "CSE",
        "semester": 5,
        "section": "A",
    },
    {
        "college_id": "student.ece3b@bitmesra.ac.in",
        "name": "Bob (ECE Sem 3 B)",
        "password": "student123",
        "role": "student",
        "branch": "ECE",
        "semester": 3,
        "section": "B",
    },
]


def seed():
    db = SessionLocal()
    try:
        for data in DEMO_USERS:
            existing = db.query(User).filter(User.college_id == data["college_id"]).first()
            if existing:
                print(f"[SKIP] {data['college_id']} already exists.")
                continue
            user = User(
                college_id=data["college_id"],
                name=data["name"],
                password_hash=_pwd.hash(data["password"]),
                role=data["role"],
                branch=data["branch"],
                semester=data["semester"],
                section=data["section"],
                active=True,
            )
            db.add(user)
            print(f"[CREATE] {data['college_id']} ({data['role']})")
        db.commit()
        print("\n[SUCCESS] Seed complete.")
        print("\nDemo credentials:")
        for d in DEMO_USERS:
            print(f"  {d['college_id']}  /  {d['password']}")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
