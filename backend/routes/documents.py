"""
Document listing, deletion, replacement and preview links.

  GET    /documents                            Documents the caller may read.
  DELETE /documents/{document_id}              Soft-delete own document; purge vectors and file.
  POST   /documents/{document_id}/replace      Upload a new version of own document.
  POST   /documents/{document_id}/preview-link Issue a short-lived PDF preview token.

Every read path derives its scope from `allowed_document_versions()`; no filter is
built here.
"""
import os
from datetime import datetime, timezone

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from sqlalchemy.orm import Session

from backend.auth import create_preview_token, get_current_user
from backend.config import INDEX_NAME
from backend.database import get_db
from backend.logger import get_logger
from backend.models.db_models import Document, DocumentVersion, User
from backend.models.schemas import DocumentOut, PreviewLinkResponse
from backend.routes.ingest import index_document, validate_pdf_upload, version_file_path
from backend.services.access_policy import allowed_document_versions
from backend.services.qdrant_service import delete_points_by_doc_version

router = APIRouter(prefix="/documents", tags=["documents"])
logger = get_logger()


def _own_document_or_404(document_id: str, user: User, db: Session) -> Document:
    """Load a document the caller owns, or raise 404.

    A document that exists but belongs to someone else returns the same 404 as one
    that does not exist, so document IDs cannot be probed for existence.
    """
    doc = db.get(Document, document_id)
    if doc is None or doc.deleted_at is not None or doc.owner_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )
    return doc


def _display_version(doc: Document) -> DocumentVersion | None:
    """The version whose status should be shown: the active one, else the newest."""
    if not doc.versions:
        return None
    if doc.active_version is not None:
        for ver in doc.versions:
            if ver.version == doc.active_version:
                return ver
    return max(doc.versions, key=lambda v: v.version)


@router.get("", response_model=list[DocumentOut])
def list_documents(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List every document the caller may read, newest first.

    The caller's own documents are always listed regardless of status, so they can
    watch an upload move from processing to ready or failed. Everyone else's
    documents appear only when the access policy grants them.
    """
    allowed = set(allowed_document_versions(current_user, db))

    docs = (
        db.query(Document)
        .filter(Document.deleted_at.is_(None))
        .order_by(Document.created_at.desc())
        .all()
    )

    out: list[DocumentOut] = []
    for doc in docs:
        shown = _display_version(doc)
        is_owner = doc.owner_id == current_user.id
        is_shared_with_caller = (
            shown is not None
            and doc.active_version == shown.version
            and shown.doc_version_key in allowed
        )
        if not (is_owner or is_shared_with_caller):
            continue

        item = DocumentOut.model_validate(doc)
        item.active_version_status = shown.status if shown else None
        item.chunk_count = shown.chunk_count if shown else None
        out.append(item)

    return out


@router.delete("/{document_id}")
def delete_document(
    document_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Soft-delete one of the caller's own documents.

    The row is marked deleted first, so the document stops being readable even if
    purging its vectors or file fails afterwards.
    """
    doc = _own_document_or_404(document_id, current_user, db)
    versions = list(doc.versions)

    doc.deleted_at = datetime.now(timezone.utc)
    doc.active_version = None
    db.commit()

    removed_chunks = 0
    for ver in versions:
        removed_chunks += delete_points_by_doc_version(INDEX_NAME, ver.doc_version_key)
        try:
            if ver.file_path and os.path.exists(ver.file_path):
                os.remove(ver.file_path)
        except OSError as exc:
            logger.warning(f"[DOCUMENTS] Could not remove file '{ver.file_path}': {exc}")

    doc_dir = os.path.dirname(versions[0].file_path) if versions else None
    if doc_dir and os.path.isdir(doc_dir):
        try:
            os.rmdir(doc_dir)
        except OSError:
            pass  # directory not empty or still locked; harmless

    logger.info(
        f"[DOCUMENTS] {current_user.college_id} deleted '{doc.display_name}' "
        f"({document_id}) — {removed_chunks} chunks removed."
    )
    return {
        "status": "success",
        "document_id": document_id,
        "deleted_chunks": removed_chunks,
    }


@router.post("/{document_id}/replace", status_code=status.HTTP_202_ACCEPTED)
async def replace_document(
    document_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload a new version of one of the caller's own documents.

    The existing version keeps serving until the new one finishes indexing; only
    then does the active version switch and the old version's chunks get removed.
    The audience is inherited and cannot be changed here.
    """
    doc = _own_document_or_404(document_id, current_user, db)

    raw_bytes = await file.read()
    validate_pdf_upload(file, raw_bytes)

    highest = max((v.version for v in doc.versions), default=0)
    new_version = highest + 1

    file_path = version_file_path(doc.id, new_version)
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, "wb") as fh:
        fh.write(raw_bytes)

    db.add(
        DocumentVersion(
            document_id=doc.id,
            version=new_version,
            file_path=file_path,
            status="processing",
        )
    )
    db.commit()

    logger.info(
        f"[DOCUMENTS] {current_user.college_id} queued replacement "
        f"{doc.display_name} ({doc.id} v{new_version})."
    )
    background_tasks.add_task(index_document, doc.id, new_version)

    return {
        "document_id": doc.id,
        "version": new_version,
        "status": "processing",
        "display_name": doc.display_name,
    }


@router.post("/{document_id}/preview-link", response_model=PreviewLinkResponse)
def create_preview_link(
    document_id: str,
    page: int | None = Query(None, ge=1, description="Page to open the PDF at."),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Issue a short-lived token for viewing a document's original PDF.

    The token is bound to this user, document and version and expires in five
    minutes. It grants nothing on its own: GET /files/{token} re-checks the
    account and the access policy on every request.
    """
    doc = db.get(Document, document_id)
    if doc is None or doc.deleted_at is not None or doc.active_version is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )

    version = doc.active_version
    ver = db.get(DocumentVersion, (document_id, version))
    if ver is None or ver.status != "ready":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This document is not ready to view yet.",
        )

    if ver.doc_version_key not in set(allowed_document_versions(current_user, db)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have permission to view this document.",
        )

    token = create_preview_token(current_user.id, document_id, version)
    return PreviewLinkResponse(
        token=token,
        page_fragment=f"#page={page}" if page else "",
    )
