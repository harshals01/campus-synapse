import os
import sys
from dotenv import load_dotenv

load_dotenv(override=True)

# ── Vector Store ───────────────────────────────────────────────────────────────
# Set QDRANT_URL to a URL for a remote server, or leave unset to use local-file mode.
QDRANT_URL: str = os.environ.get("QDRANT_URL", "")
QDRANT_API_KEY: str = os.environ.get("QDRANT_API_KEY", "")
# Local file mode: data stored at this path when QDRANT_URL is not set.
QDRANT_PATH: str = os.environ.get("QDRANT_PATH", "./data/qdrant")
INDEX_NAME: str = os.environ.get("INDEX_NAME", "campus_synapse")

# ── RAG Thresholds ─────────────────────────────────────────────────────────────
# Minimum cosine similarity (0–1) from dense search to avoid abstention.
SIMILARITY_THRESHOLD: float = float(os.environ.get("SIMILARITY_THRESHOLD", "0.35"))
MAX_CONTEXT_DOCS: int = int(os.environ.get("MAX_CONTEXT_DOCS", "20"))
CHAT_HISTORY_WINDOW: int = int(os.environ.get("CHAT_HISTORY_WINDOW", "6"))

# ── Groq LLM ──────────────────────────────────────────────────────────────────
GROQ_API_KEY: str = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL: str = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")

# ── Ingestion ──────────────────────────────────────────────────────────────────
INGEST_BATCH_SIZE: int = int(os.environ.get("INGEST_BATCH_SIZE", "32"))
MAX_FILE_SIZE_BYTES: int = int(os.environ.get("MAX_FILE_SIZE_MB", "5")) * 1024 * 1024
MAX_FILES_PER_USER: int = int(os.environ.get("MAX_FILES_PER_USER", "10"))
# Local disk path where original PDFs are stored.
FILE_STORAGE_PATH: str = os.environ.get("FILE_STORAGE_PATH", "./data/files")

# ── Auth ───────────────────────────────────────────────────────────────────────
JWT_SECRET: str = os.environ.get("JWT_SECRET", "")
JWT_EXPIRE_MINUTES: int = int(os.environ.get("JWT_EXPIRE_MINUTES", "60"))

# ── Database ───────────────────────────────────────────────────────────────────
DATABASE_URL: str = os.environ.get("DATABASE_URL", "sqlite:///./data/campus.db")

# ── CORS ───────────────────────────────────────────────────────────────────────
_raw_allowed_origins = os.environ.get("ALLOWED_ORIGINS", "").strip()
ALLOWED_ORIGINS: list[str] = (
    [o.strip() for o in _raw_allowed_origins.split(",") if o.strip()]
    if _raw_allowed_origins
    else ["http://localhost:5173", "http://127.0.0.1:5173"]
)

# ── Institution constants ──────────────────────────────────────────────────────
COLLEGE_ID_DOMAIN: str = "bitmesra.ac.in"
BRANCHES: list[str] = ["CSE", "ECE", "EEE", "AI", "BCA", "MCA", "BAM"]
SEMESTERS: list[int] = list(range(1, 9))   # 1 through 8
SECTIONS: list[str] = ["A", "B"]

# ── Startup guard ──────────────────────────────────────────────────────────────
_INSECURE_JWT_DEFAULTS = {"", "changeme", "secret", "your-secret-key", "jwt_secret"}

def _validate_startup() -> None:
    """Refuse to start if critical secrets are missing or obviously insecure."""
    if JWT_SECRET.lower() in _INSECURE_JWT_DEFAULTS:
        print(
            "[FATAL] JWT_SECRET is not set or is an insecure default value.\n"
            "Generate one with:  python -c \"import secrets; print(secrets.token_hex(32))\"\n"
            "Then set it in your .env file as JWT_SECRET=<value>",
            file=sys.stderr,
        )
        sys.exit(1)
