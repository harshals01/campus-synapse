"""
Shared fixtures for the Campus Synapse test suite.

Environment variables are set *before* `backend` is imported, because `config.py`
reads them at import time, `qdrant_service` opens its local store at import time,
and `main.py` refuses to start without a real `JWT_SECRET`.

Two things are stubbed so the suite needs no network, no HuggingFace download and
no Groq key:

* **Embeddings** become a bag-of-words hashing vector. Chunks sharing words with
  the query get a high cosine similarity, so the `SIMILARITY_THRESHOLD` path is
  exercised deterministically. It is lexical, not semantic — these tests check
  plumbing and permissions, not retrieval quality. Retrieval quality is what
  `eval/run_eval.py` measures, with the real model.
* **The LLM call** returns a fixed string, so no request ever leaves the machine.
"""
import hashlib
import math
import os
import shutil
import tempfile

import pytest

_WORK = tempfile.mkdtemp(prefix="campus-synapse-tests-")

os.environ.update(
    JWT_SECRET="test-only-secret-" + "a1b2c3d4" * 6,
    JWT_EXPIRE_MINUTES="60",
    GROQ_API_KEY="test-key-never-used",
    QDRANT_URL="",
    QDRANT_PATH=os.path.join(_WORK, "qdrant"),
    DATABASE_URL=f"sqlite:///{os.path.join(_WORK, 'campus.db')}",
    FILE_STORAGE_PATH=os.path.join(_WORK, "files"),
    INDEX_NAME="campus_synapse_test",
    SIMILARITY_THRESHOLD="0.35",
    # The library fixture uploads documents per test; the production default of 10
    # would trip partway through the suite. The quota itself is tested by
    # monkeypatching config.MAX_FILES_PER_USER back down.
    MAX_FILES_PER_USER="500",
)
# NOTE: deliberately no os.chdir here - it confuses pytest's testpaths
# resolution. ./data and ./logs land in the repo root, both gitignored.

# ruff: noqa: E402  - imports must follow the env setup above
from fastapi.testclient import TestClient
from passlib.context import CryptContext

import backend.routes.auth as auth_routes
import backend.routes.chat as chat_module
import backend.routes.ingest as ingest_module
import backend.services.search_service as search_module
from backend.config import INDEX_NAME
from backend.database import SessionLocal
from backend.main import app
from backend.models.db_models import User

STUB_REPLY = "The late payment fine is 500 rupees per week [1]."
PASSWORD = "Passw0rd!"

ACCOUNTS = {
    "admin":   dict(college_id="test-admin@bitmesra.ac.in",   name="Admin",      role="admin",   branch=None,  semester=None, section=None),
    "teacher": dict(college_id="test-teacher@bitmesra.ac.in", name="CSE Teacher", role="teacher", branch="CSE", semester=None, section=None),
    "cse5":    dict(college_id="test-cse5@bitmesra.ac.in",    name="CSE Sem5",   role="student", branch="CSE", semester=5,    section="A"),
    "ece3":    dict(college_id="test-ece3@bitmesra.ac.in",    name="ECE Sem3",   role="student", branch="ECE", semester=3,    section="B"),
}


def stub_vector(text: str, dims: int = 384) -> list[float]:
    """Deterministic bag-of-words vector. Shared words -> high cosine similarity."""
    vec = [0.0] * dims
    for raw in text.lower().split():
        word = "".join(ch for ch in raw if ch.isalnum())
        if not word:
            continue
        vec[int(hashlib.md5(word.encode()).hexdigest(), 16) % dims] += 1.0
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


# Patch the names the modules actually bound at import, not the source module.
ingest_module.get_embeddings_batch = lambda texts: [stub_vector(t) for t in texts]
search_module.get_embedding = stub_vector
chat_module.call_llm = lambda payload, logger: STUB_REPLY


def pytest_sessionfinish(session, exitstatus):
    shutil.rmtree(_WORK, ignore_errors=True)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="session")
def client():
    return TestClient(app)


@pytest.fixture(scope="session")
def accounts():
    """Create one account per role. Returns {key: {id, college_id, ...}}."""
    pwd = CryptContext(schemes=["bcrypt"], deprecated="auto")
    db = SessionLocal()
    try:
        created = {}
        for key, spec in ACCOUNTS.items():
            user = db.query(User).filter(User.college_id == spec["college_id"]).first()
            if user is None:
                user = User(password_hash=pwd.hash(PASSWORD), active=True, **spec)
                db.add(user)
                db.commit()
            created[key] = {"id": user.id, **spec}
        return created
    finally:
        db.close()


@pytest.fixture
def login(client, accounts):
    """login("cse5") -> Authorization header dict."""
    def _login(key, password=PASSWORD):
        # The real limiter allows 5 attempts per minute per IP, and every test
        # call shares one IP, so reset it rather than testing the limiter here.
        auth_routes._login_attempts.clear()
        response = client.post(
            "/auth/login",
            json={"college_id": accounts[key]["college_id"], "password": password},
        )
        assert response.status_code == 200, f"login {key} failed: {response.text}"
        return {"Authorization": f"Bearer {response.json()['access_token']}"}
    return _login


@pytest.fixture
def db_session():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture(scope="session")
def make_pdf():
    """make_pdf("name.pdf", ["page one text", "page two text"]) -> path."""
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    counter = {"n": 0}

    def _make(name, pages):
        # Each PDF gets its own directory so the basename - and therefore the
        # document's display_name - stays exactly as the caller asked.
        counter["n"] += 1
        folder = os.path.join(_WORK, "pdfs", str(counter["n"]))
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, name)
        pdf = canvas.Canvas(path, pagesize=A4)
        for page_text in pages:
            y = 800
            for line in page_text.strip().split("\n"):
                pdf.drawString(60, y, line.strip())
                y -= 18
            pdf.showPage()
        pdf.save()
        return path
    return _make


FEE_PAGES = [
    "SEMESTER 5 FEE NOTICE\nThe tuition fee for semester 5 is 45000 rupees.\nPayable on or before 30 September.",
    "LATE PAYMENT\nLate payment attracts a fine of 500 rupees per week.\nHall tickets are withheld until dues are cleared.",
    "SCHOLARSHIPS\nThe merit scholarship covers 25 percent of tuition.\nApply at the accounts office with marksheets.",
]
CIRCULAR_PAGES = [
    "CONFIDENTIAL FACULTY CIRCULAR\nAppraisal forms are due to the dean by 15 October.\nSalary revision applies from November.",
]


@pytest.fixture
def upload(client, login):
    """upload("admin", path, audience_type="class", ...) -> response."""
    def _upload(role_key, path, headers=None, **form):
        with open(path, "rb") as handle:
            return client.post(
                "/ingest",
                headers=headers if headers is not None else login(role_key),
                files={"file": (os.path.basename(path), handle, "application/pdf")},
                data=form,
            )
    return _upload


@pytest.fixture
def library(make_pdf, upload):
    """A fee notice scoped to CSE sem 5, and a circular scoped to teachers.

    Returns {"fee": document_id, "circular": document_id}. Indexing runs in a
    FastAPI background task, which TestClient executes before the response is
    handed back, so both documents are already `ready` here.
    """
    fee = upload(
        "admin", make_pdf("fee_notice.pdf", FEE_PAGES),
        audience_type="class", audience_branch="CSE", audience_semester="5",
    )
    assert fee.status_code == 202, fee.text
    circular = upload(
        "admin", make_pdf("faculty_circular.pdf", CIRCULAR_PAGES),
        audience_type="teachers",
    )
    assert circular.status_code == 202, circular.text
    return {
        "fee": fee.json()["document_id"],
        "circular": circular.json()["document_id"],
    }


@pytest.fixture
def ask(client, login):
    """ask("cse5", "question") -> parsed /chat response body."""
    def _ask(role_key, question, headers=None, **body):
        response = client.post(
            "/chat",
            headers=headers if headers is not None else login(role_key),
            json={"messages": [{"role": "user", "content": question}], **body},
        )
        return response
    return _ask


@pytest.fixture
def fresh_student(client, login):
    """A brand-new student who owns nothing.

    The shared accounts accumulate documents as the suite runs, so a test that
    needs a genuinely empty library has to make its own user.
    """
    import uuid
    college_id = f"test-empty-{uuid.uuid4().hex[:8]}@bitmesra.ac.in"
    created = client.post(
        "/admin/users",
        headers=login("admin"),
        json={
            "college_id": college_id, "name": "Empty Student",
            "password": PASSWORD, "role": "student",
            "branch": "EEE", "semester": 2, "section": "A",
        },
    )
    assert created.status_code == 200, created.text
    import backend.routes.auth as auth_routes
    auth_routes._login_attempts.clear()
    token = client.post(
        "/auth/login", json={"college_id": college_id, "password": PASSWORD}
    ).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def index_name():
    return INDEX_NAME
