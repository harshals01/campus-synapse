from dotenv import load_dotenv

load_dotenv(override=True)

# Validate critical secrets before anything else loads.
from backend import config
config._validate_startup()

from datetime import datetime, timedelta, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from backend.database import SessionLocal, engine
from backend.models import db_models
from backend.routes.auth import router as auth_router
from backend.routes.chat import router as chat_router
from backend.routes.documents import router as documents_router
from backend.routes.ingest import router as ingest_router
from backend.routes.admin import router as admin_router
from backend.routes.conversations import router as conversations_router
from backend.routes.files import router as files_router
from backend.logger import get_logger

logger = get_logger()

# Create all SQLite tables on first run.
db_models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Campus Synapse API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router, prefix="/auth")
app.include_router(chat_router)
app.include_router(ingest_router)
app.include_router(documents_router)
app.include_router(admin_router)
app.include_router(conversations_router)
app.include_router(files_router)


@app.on_event("startup")
def cleanup_stuck_ingestions() -> None:
    """
    Mark any DocumentVersion stuck in 'processing' for more than 10 minutes
    as 'failed' so users can retry without stale status badges.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)
    db: Session = SessionLocal()
    try:
        stuck = (
            db.query(db_models.DocumentVersion)
            .filter(
                db_models.DocumentVersion.status == "processing",
                db_models.DocumentVersion.created_at < cutoff,
            )
            .all()
        )
        for ver in stuck:
            ver.status = "failed"
            ver.error = "Server restarted during processing."
            logger.warning(
                f"[STARTUP] Marked stuck version {ver.document_id} v{ver.version} as failed."
            )
        if stuck:
            db.commit()
    finally:
        db.close()
