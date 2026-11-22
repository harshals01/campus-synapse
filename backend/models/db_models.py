"""
SQLAlchemy ORM models — these define all database tables.
Never import this module directly in routes; use schemas.py for Pydantic I/O.
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Boolean, DateTime, ForeignKey, Integer, String, Text, JSON
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


# ── Users ──────────────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    # College email used to log in, e.g. john@bitmesra.ac.in
    college_id: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)         # student | teacher | admin
    branch: Mapped[str | None] = mapped_column(String, nullable=True)  # CSE | ECE | EEE | AI | BCA | MCA | BAM
    semester: Mapped[int | None] = mapped_column(Integer, nullable=True)   # 1–8
    section: Mapped[str | None] = mapped_column(String, nullable=True)     # A | B
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    documents: Mapped[list["Document"]] = relationship("Document", back_populates="owner")
    conversations: Mapped[list["Conversation"]] = relationship("Conversation", back_populates="owner")
    query_logs: Mapped[list["QueryLog"]] = relationship("QueryLog", back_populates="user")


# ── Documents ─────────────────────────────────────────────────────────────────

class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    # personal = only the owner; shared = audience rules apply
    category: Mapped[str] = mapped_column(String, nullable=False, default="personal")
    # Audience for shared docs: everyone | students | teachers | class
    audience_type: Mapped[str | None] = mapped_column(String, nullable=True)
    audience_branch: Mapped[str | None] = mapped_column(String, nullable=True)
    audience_semester: Mapped[int | None] = mapped_column(Integer, nullable=True)
    audience_section: Mapped[str | None] = mapped_column(String, nullable=True)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    active_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    owner: Mapped["User"] = relationship("User", back_populates="documents")
    versions: Mapped[list["DocumentVersion"]] = relationship(
        "DocumentVersion", back_populates="document", cascade="all, delete-orphan"
    )


class DocumentVersion(Base):
    __tablename__ = "document_versions"

    document_id: Mapped[str] = mapped_column(String, ForeignKey("documents.id"), primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    file_path: Mapped[str] = mapped_column(String, nullable=False)
    # processing | ready | failed
    status: Mapped[str] = mapped_column(String, nullable=False, default="processing")
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chunk_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    document: Mapped["Document"] = relationship("Document", back_populates="versions")

    @property
    def doc_version_key(self) -> str:
        """The string used as the Qdrant payload `doc_version` field."""
        return f"{self.document_id}_v{self.version}"


# ── Conversations & Messages ───────────────────────────────────────────────────

class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    owner_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False, default="New conversation")
    # JSON list of document IDs selected for this conversation
    selected_document_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    owner: Mapped["User"] = relationship("User", back_populates="conversations")
    messages: Mapped[list["Message"]] = relationship(
        "Message", back_populates="conversation", cascade="all, delete-orphan",
        order_by="Message.created_at",
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    conversation_id: Mapped[str] = mapped_column(
        String, ForeignKey("conversations.id"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String, nullable=False)   # user | assistant
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Stored as JSON: list of {document_id, version, page_number, chunk_index}
    # Snippets are NOT stored — re-fetched at display time to prevent stale data leaks.
    citations: Mapped[list | None] = mapped_column(JSON, nullable=True)
    top_fusion_score: Mapped[float | None] = mapped_column(nullable=True)
    top_similarity: Mapped[float | None] = mapped_column(nullable=True)
    abstained: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    conversation: Mapped["Conversation"] = relationship("Conversation", back_populates="messages")


# ── Query Log ─────────────────────────────────────────────────────────────────

class QueryLog(Base):
    __tablename__ = "query_log"

    id: Mapped[str] = mapped_column(String, primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String, ForeignKey("users.id"), nullable=False, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    answered: Mapped[bool] = mapped_column(Boolean, default=False)
    abstained: Mapped[bool] = mapped_column(Boolean, default=False)
    top_similarity: Mapped[float | None] = mapped_column(nullable=True)
    # JSON list of document_ids cited in the answer
    cited_documents: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    user: Mapped["User"] = relationship("User", back_populates="query_logs")
