"""
PDF upload and background indexing.

  POST /ingest   Accept a PDF, record it, and index it in the background.

The upload returns as soon as the file is on disk. Extraction, embedding and the
Qdrant upsert happen in a background task, so the client polls GET /documents for
the version's status (processing -> ready | failed).
"""
import os
import uuid

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from qdrant_client.http.models import PointStruct
from sqlalchemy.orm import Session

from backend import config
from backend.auth import get_current_user
from backend.config import INDEX_NAME, INGEST_BATCH_SIZE
from backend.database import SessionLocal, get_db
from backend.logger import get_logger
from backend.models.db_models import Document, DocumentVersion, User
from backend.models.schemas import IngestResponse
from backend.services.embedding_service import get_embeddings_batch
from backend.services.qdrant_service import (
    delete_points_by_doc_version,
    ensure_collection_exists,
    qdrant_client,
)
from backend.services.text_processor import chunk_pages, extract_pages_from_bytes

router = APIRouter(tags=["ingest"])
logger = get_logger()

ALLOWED_CONTENT_TYPES = {
    "application/pdf",
    "application/x-pdf",
    "application/acrobat",
    "applications/vnd.pdf",
    "text/pdf",
    "text/x-pdf",
    "application/octet-stream",
}

_SHARED_AUDIENCES = {"everyone", "students", "teachers", "class"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def point_id(document_id: str, version: int, chunk_index: int) -> str:
    """Deterministic Qdrant point ID.

    Derived from document, version and chunk index rather than the filename, so
    two users uploading the same filename never collide and a retried index run
    overwrites its own points instead of duplicating them.
    """
    return str(
        uuid.uuid5(uuid.NAMESPACE_DNS, f"{document_id}_v{version}_{chunk_index}")
    )


def version_file_path(document_id: str, version: int) -> str:
    return os.path.join(config.FILE_STORAGE_PATH, document_id, f"v{version}.pdf")


def validate_pdf_upload(file: UploadFile, raw_bytes: bytes) -> None:
    """Reject anything that is not a PDF within the configured size limit.

    Shared by POST /ingest and POST /documents/{id}/replace so both enforce
    identical rules.
    """
    is_valid_type = file.content_type in ALLOWED_CONTENT_TYPES
    is_pdf_ext = bool(file.filename and file.filename.lower().endswith(".pdf"))
    if not (is_valid_type or is_pdf_ext):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF files are accepted.",
        )
    if not raw_bytes:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The uploaded file is empty.",
        )
    if len(raw_bytes) > config.MAX_FILE_SIZE_BYTES:
        limit_mb = config.MAX_FILE_SIZE_BYTES // (1024 * 1024)
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File exceeds the {limit_mb} MB size limit.",
        )


def _resolve_audience(
    user: User,
    audience_type: str | None,
    audience_branch: str | None,
    audience_semester: int | None,
    audience_section: str | None,
) -> tuple[str, str | None, str | None, int | None, str | None]:
    """Decide a document's category and audience from the uploader's role.

    Returns ``(category, audience_type, branch, semester, section)``. The audience
    is always derived here on the server from the uploader's own profile and role —
    never trusted from the request alone.

    Rules:
      - Anyone may upload a personal document (the default).
      - Only an admin may share with everyone, all students or all teachers.
      - A teacher may share only with a class in their own branch, optionally
        narrowed to a semester and section.
      - A student may not share at all.
    """
    if not audience_type or audience_type == "personal":
        return "personal", None, None, None, None

    if audience_type not in _SHARED_AUDIENCES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"audience_type must be 'personal' or one of {sorted(_SHARED_AUDIENCES)}.",
        )

    branch = audience_branch.strip().upper() if audience_branch else None
    section = audience_section.strip().upper() if audience_section else None

    if branch is not None and branch not in config.BRANCHES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"audience_branch must be one of {config.BRANCHES}.",
        )
    if audience_semester is not None and audience_semester not in config.SEMESTERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"audience_semester must be one of {config.SEMESTERS}.",
        )
    if section is not None and section not in config.SECTIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"audience_section must be one of {config.SECTIONS}.",
        )

    if user.role == "admin":
        if audience_type == "class":
            if not branch:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="audience_branch is required when audience_type is 'class'.",
                )
            return "shared", "class", branch, audience_semester, section
        # everyone | students | teachers are college-wide; the narrowing fields do not apply.
        return "shared", audience_type, None, None, None

    if user.role == "teacher":
        if audience_type != "class":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Teachers may only share a document with a class.",
            )
        if not user.branch:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Your account has no branch set, so it cannot share with a class.",
            )
        # Branch is forced to the teacher's own; semester and section may only narrow it.
        return "shared", "class", user.branch.upper(), audience_semester, section

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Students may only upload personal documents.",
    )


# ── Background indexing ───────────────────────────────────────────────────────

def index_document(document_id: str, version: int) -> None:
    """Extract, chunk, embed and upsert one document version, then mark it ready.

    Runs as a FastAPI background task with its own database session, because the
    request's session is already closed by the time this runs. Every failure path
    records the reason on the version row so the UI can show it and offer a retry.
    """
    db: Session = SessionLocal()
    try:
        ver = db.get(DocumentVersion, (document_id, version))
        doc = db.get(Document, document_id)
        if ver is None or doc is None:
            logger.error(f"[INGEST] Version {document_id} v{version} vanished before indexing.")
            return

        previous_active = doc.active_version

        try:
            with open(ver.file_path, "rb") as fh:
                raw_bytes = fh.read()

            pages = extract_pages_from_bytes(raw_bytes)
            if not any(p["text"].strip() for p in pages):
                ver.status = "failed"
                ver.error = (
                    "No extractable text found. Scanned or image-only PDFs are not "
                    "supported without OCR."
                )
                db.commit()
                logger.warning(f"[INGEST] {document_id} v{version}: no extractable text.")
                return

            chunks = chunk_pages(pages)
            if not chunks:
                ver.status = "failed"
                ver.error = "The document produced no indexable chunks."
                db.commit()
                return

            ensure_collection_exists(INDEX_NAME)

            doc_version_key = ver.doc_version_key
            points: list[PointStruct] = []
            for start in range(0, len(chunks), INGEST_BATCH_SIZE):
                batch = chunks[start : start + INGEST_BATCH_SIZE]
                vectors = get_embeddings_batch([c["text"] for c in batch])
                for chunk, vector in zip(batch, vectors):
                    points.append(
                        PointStruct(
                            id=point_id(document_id, version, chunk["chunk_index"]),
                            vector=vector,
                            payload={
                                "doc_version": doc_version_key,
                                "document_id": document_id,
                                "version": version,
                                "page_number": chunk["page_number"],
                                "chunk_index": chunk["chunk_index"],
                                "combined": chunk["text"],
                            },
                        )
                    )

            qdrant_client.upsert(collection_name=INDEX_NAME, points=points)

            # Mark ready and publish the version in a single commit, so a reader
            # never sees an active version whose chunks are not yet searchable.
            ver.page_count = len(pages)
            ver.chunk_count = len(points)
            ver.status = "ready"
            ver.error = None
            doc.active_version = version
            db.commit()
            logger.info(
                f"[INGEST] {doc.display_name} ({document_id} v{version}) ready — "
                f"{len(pages)} pages, {len(points)} chunks."
            )

            # Only once the new version is live, retire the one it replaced.
            if previous_active is not None and previous_active != version:
                old = db.get(DocumentVersion, (document_id, previous_active))
                if old is not None:
                    delete_points_by_doc_version(INDEX_NAME, old.doc_version_key)

        except Exception as exc:
            db.rollback()
            ver = db.get(DocumentVersion, (document_id, version))
            if ver is not None:
                ver.status = "failed"
                ver.error = str(exc)[:1000]
                db.commit()
            logger.exception(f"[INGEST] Indexing failed for {document_id} v{version}")
    finally:
        db.close()


# ── Route ─────────────────────────────────────────────────────────────────────

@router.post("/ingest", response_model=IngestResponse, status_code=status.HTTP_202_ACCEPTED)
async def ingest_pdf(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    audience_type: str | None = Form(
        None, description="personal (default) | everyone | students | teachers | class"
    ),
    audience_branch: str | None = Form(None),
    audience_semester: int | None = Form(None),
    audience_section: str | None = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Accept a PDF, store it, and queue it for indexing.

    Responds 202 with the new document's ID and a status of ``processing``.
    """
    raw_bytes = await file.read()
    validate_pdf_upload(file, raw_bytes)

    owned = (
        db.query(Document)
        .filter(Document.owner_id == current_user.id, Document.deleted_at.is_(None))
        .count()
    )
    if owned >= config.MAX_FILES_PER_USER:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"You have reached the limit of {config.MAX_FILES_PER_USER} documents. "
                "Delete one before uploading another."
            ),
        )

    category, aud_type, aud_branch, aud_semester, aud_section = _resolve_audience(
        current_user, audience_type, audience_branch, audience_semester, audience_section
    )

    display_name = os.path.basename(file.filename or "document.pdf").strip() or "document.pdf"

    document = Document(
        owner_id=current_user.id,
        category=category,
        audience_type=aud_type,
        audience_branch=aud_branch,
        audience_semester=aud_semester,
        audience_section=aud_section,
        display_name=display_name,
        active_version=None,
    )
    db.add(document)
    db.flush()          # assigns document.id without ending the transaction

    version_number = 1
    file_path = version_file_path(document.id, version_number)
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, "wb") as fh:
        fh.write(raw_bytes)

    doc_version = DocumentVersion(
        document_id=document.id,
        version=version_number,
        file_path=file_path,
        status="processing",
    )
    db.add(doc_version)
    db.commit()

    logger.info(
        f"[INGEST] Queued '{display_name}' ({document.id} v{version_number}) "
        f"for {current_user.college_id} — category={category}, audience={aud_type}."
    )
    background_tasks.add_task(index_document, document.id, version_number)

    return IngestResponse(
        document_id=document.id,
        version=version_number,
        status="processing",
        display_name=display_name,
    )
