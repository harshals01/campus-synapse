"""
Secure PDF file serving.
  GET /files/{token}   Validate the preview JWT and stream the PDF.
"""
import os
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from backend.auth import decode_preview_token
from backend.database import get_db
from backend.models.db_models import Document, DocumentVersion
from backend.services.access_policy import allowed_document_versions

router = APIRouter(prefix="/files", tags=["files"])


@router.get("/{token}")
def serve_file(token: str, db: Session = Depends(get_db)):
    """
    Decode the preview JWT and serve the PDF only if all checks pass:
      1. Token signature and expiry are valid, audience is 'preview'.
      2. User account is active (re-checked from DB, not from token).
      3. Document is not deleted and the version is still active + ready.
      4. User still has access under the current audience rules.
    """
    user, document_id, version = decode_preview_token(token, db)

    # Re-run the access policy from scratch — not cached.
    allowed = set(allowed_document_versions(user, db))
    doc_ver_key = f"{document_id}_v{version}"

    if doc_ver_key not in allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied.")

    # Confirm version still exists and is ready.
    doc_version = (
        db.query(DocumentVersion)
        .filter(
            DocumentVersion.document_id == document_id,
            DocumentVersion.version == version,
            DocumentVersion.status == "ready",
        )
        .first()
    )
    if doc_version is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    # Confirm document is not deleted.
    doc = db.get(Document, document_id)
    if doc is None or doc.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    file_path = doc_version.file_path
    if not os.path.isfile(file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found on disk.",
        )

    return FileResponse(
        path=file_path,
        media_type="application/pdf",
        filename=doc.display_name,
        headers={
            "Cache-Control": "private, no-store",
            "Referrer-Policy": "no-referrer",
        },
    )
