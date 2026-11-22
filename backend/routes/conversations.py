"""
Conversation history routes — owner-only, with per-message access re-validation.
  GET /conversations          List the caller's conversations
  GET /conversations/{id}     Load a conversation with safe history filtering
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.auth import get_current_user
from backend.database import get_db
from backend.models.db_models import Conversation, Document, DocumentVersion, Message, User
from backend.models.schemas import ConversationOut, MessageOut
from backend.services.access_policy import allowed_document_versions

router = APIRouter(prefix="/conversations", tags=["conversations"])


@router.get("", response_model=list[ConversationOut])
def list_conversations(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return all conversations owned by the current user, newest first."""
    convs = (
        db.query(Conversation)
        .filter(Conversation.owner_id == current_user.id)
        .order_by(Conversation.created_at.desc())
        .all()
    )
    return convs


@router.get("/{conversation_id}")
def get_conversation(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """
    Load a conversation.  For each assistant message, re-check whether every
    cited (document_id, version) is still accessible.  If a source is no longer
    readable, its snippet is replaced with 'Source no longer available' and it is
    excluded from any future LLM context.
    """
    conv = db.get(Conversation, conversation_id)
    if conv is None or conv.owner_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found.")

    # Compute the user's current allowed set once.
    allowed_versions_set = set(allowed_document_versions(current_user, db))

    safe_messages = []
    for msg in conv.messages:
        if msg.role == "user":
            safe_messages.append(msg)
            continue

        # For assistant messages, validate every citation.
        if not msg.citations:
            safe_messages.append(msg)
            continue

        sanitized_citations = []
        all_accessible = True
        for cite in msg.citations:
            doc_ver_key = f"{cite.get('document_id')}_v{cite.get('version')}"
            if doc_ver_key in allowed_versions_set:
                sanitized_citations.append(cite)
            else:
                all_accessible = False
                # Inject a placeholder so the UI can show "Source no longer available"
                sanitized_citations.append({
                    **cite,
                    "snippet": "Source no longer available.",
                    "unavailable": True,
                })

        # Build a safe MessageOut — replace content if source is gone.
        content = msg.content
        if not all_accessible:
            content = (
                msg.content
                + "\n\n*(Some sources cited in this answer are no longer accessible to you.)*"
            )

        safe_messages.append({
            "id": msg.id,
            "role": msg.role,
            "content": content,
            "citations": sanitized_citations,
            "abstained": msg.abstained,
            "created_at": msg.created_at.isoformat(),
        })

    return {
        "id": conv.id,
        "title": conv.title,
        "created_at": conv.created_at.isoformat(),
        "messages": safe_messages,
    }
