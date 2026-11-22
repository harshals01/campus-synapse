"""
Pydantic schemas for request/response validation.
These are the shapes the API accepts and returns — separate from the ORM models.
"""
from datetime import datetime
from pydantic import BaseModel, Field, field_validator
from typing import Literal

from app import config


# ── Auth ───────────────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    college_id: str = Field(..., description="College email, e.g. john@bitmesra.ac.in")
    password: str = Field(..., min_length=6)

    @field_validator("college_id")
    @classmethod
    def must_be_college_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not v.endswith(f"@{config.COLLEGE_ID_DOMAIN}"):
            raise ValueError(f"College ID must end with @{config.COLLEGE_ID_DOMAIN}")
        return v


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserProfile(BaseModel):
    id: str
    college_id: str
    name: str
    role: str
    branch: str | None
    semester: int | None
    section: str | None
    active: bool

    model_config = {"from_attributes": True}


# ── Admin: Account management ──────────────────────────────────────────────────

class CreateUserRequest(BaseModel):
    college_id: str = Field(..., description="College email")
    name: str = Field(..., min_length=2)
    password: str = Field(..., min_length=6)
    role: Literal["student", "teacher", "admin"]
    branch: str | None = Field(None)
    semester: int | None = Field(None, ge=1, le=8)
    section: str | None = Field(None)

    @field_validator("branch")
    @classmethod
    def must_be_valid_branch(cls, v: str | None) -> str | None:
        if v is not None and v.upper() not in config.BRANCHES:
            raise ValueError(f"branch must be one of {config.BRANCHES}")
        return v.upper() if v else v

    @field_validator("section")
    @classmethod
    def must_be_valid_section(cls, v: str | None) -> str | None:
        if v is not None and v.upper() not in config.SECTIONS:
            raise ValueError(f"section must be one of {config.SECTIONS}")
        return v.upper() if v else v


class PatchUserRequest(BaseModel):
    active: bool | None = None
    name: str | None = None
    branch: str | None = None
    semester: int | None = Field(None, ge=1, le=8)
    section: str | None = None


# ── Documents ─────────────────────────────────────────────────────────────────

class DocumentVersionOut(BaseModel):
    version: int
    status: str
    page_count: int | None
    chunk_count: int | None
    created_at: datetime

    model_config = {"from_attributes": True}


class DocumentOut(BaseModel):
    id: str
    display_name: str
    category: str
    audience_type: str | None
    audience_branch: str | None
    audience_semester: int | None
    audience_section: str | None
    active_version: int | None
    created_at: datetime
    active_version_status: str | None = None   # populated by route

    model_config = {"from_attributes": True}


# ── Chat ──────────────────────────────────────────────────────────────────────

class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str


class CitationRef(BaseModel):
    """Lightweight citation stored in the Message table (no snippet text)."""
    document_id: str
    version: int
    page_number: int | None
    chunk_index: int | None


class CitationOut(BaseModel):
    """Full citation returned to the client, with snippet fetched at display time."""
    id: int
    document_id: str
    version: int
    display_name: str
    page_number: int | None
    chunk_index: int | None
    snippet: str
    score: float


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(..., min_length=1)
    top_k: int = Field(20, ge=1, le=100)
    conversation_id: str | None = Field(None, description="Continue an existing conversation")
    # Optional: list of document IDs to restrict the search scope.
    # If omitted, all documents the user may read are searched.
    document_ids: list[str] | None = Field(None)


class ChatResponse(BaseModel):
    reply: str
    abstained: bool
    llm_called: bool
    hits_used: int
    top_fusion_score: float
    top_similarity: float
    citations: list[CitationOut]
    conversation_id: str


# ── Conversations ─────────────────────────────────────────────────────────────

class ConversationOut(BaseModel):
    id: str
    title: str
    created_at: datetime

    model_config = {"from_attributes": True}


class MessageOut(BaseModel):
    id: str
    role: str
    content: str
    citations: list | None
    abstained: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Query log ─────────────────────────────────────────────────────────────────

class QueryLogOut(BaseModel):
    id: str
    user_id: str
    question: str
    answered: bool
    abstained: bool
    top_similarity: float | None
    cited_documents: list | None
    created_at: datetime

    model_config = {"from_attributes": True}
