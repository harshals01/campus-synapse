"""
Access policy — the single source of truth for what a user may read.

Every route that queries documents, chat context, citations, file downloads,
or conversation history calls `allowed_document_versions()` from this module.
No route constructs its own permission filter.
"""
from sqlalchemy.orm import Session

from backend.models.db_models import Document, DocumentVersion, User


def allowed_document_versions(user: User, db: Session) -> list[str]:
    """
    Return the list of Qdrant `doc_version` keys the caller may read.

    A document version is included when ALL of these hold:
      1. The DocumentVersion.status is 'ready'.
      2. The parent Document is not soft-deleted (deleted_at IS NULL).
      3. The version is the document's active_version.
      4. Either the document is personal and owned by this user,
         OR the document is shared and its audience matches this user.
    """
    allowed: list[str] = []

    # Fetch all non-deleted documents with a ready active version.
    docs = (
        db.query(Document)
        .filter(Document.deleted_at.is_(None))
        .filter(Document.active_version.isnot(None))
        .all()
    )

    for doc in docs:
        if not _user_may_read(user, doc):
            continue

        # Fetch the active version and confirm it is ready.
        active_ver = (
            db.query(DocumentVersion)
            .filter(
                DocumentVersion.document_id == doc.id,
                DocumentVersion.version == doc.active_version,
                DocumentVersion.status == "ready",
            )
            .first()
        )
        if active_ver is None:
            continue

        allowed.append(active_ver.doc_version_key)

    return allowed


def _user_may_read(user: User, doc: Document) -> bool:
    """Return True if the user's profile satisfies the document's access rules."""

    # Personal documents: only the owner may read them.
    if doc.category == "personal":
        return doc.owner_id == user.id

    # Shared documents: apply audience rules.
    audience = doc.audience_type

    if audience == "everyone":
        return True

    if audience == "students":
        return user.role == "student"

    if audience == "teachers":
        return user.role == "teacher"

    if audience == "class":
        # Must match branch; semester and section are optional filters.
        if user.branch != doc.audience_branch:
            return False
        if doc.audience_semester is not None and user.semester != doc.audience_semester:
            return False
        if doc.audience_section is not None and user.section != doc.audience_section:
            return False
        return True

    # Admin-only or unrecognised audience — only the owner (admin) may read.
    return doc.owner_id == user.id
