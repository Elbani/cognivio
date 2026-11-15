from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field

from app.models.enums import ApiScope, MemorySource, MemoryStatus, MemoryType, Role


# --- Users / auth ---


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)
    name: str = Field(min_length=1, max_length=80)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(max_length=128)


class ProfileUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class PasswordChange(BaseModel):
    currentPassword: str = Field(max_length=128)
    newPassword: str = Field(min_length=8, max_length=72)


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str = Field(min_length=8, max_length=200)
    newPassword: str = Field(min_length=8, max_length=72)


class EmailVerify(BaseModel):
    token: str = Field(min_length=8, max_length=200)


class UserOut(BaseModel):
    id: str
    email: EmailStr
    name: str
    emailVerified: bool = False
    isAdmin: bool = False


class TokenResponse(BaseModel):
    accessToken: str
    user: UserOut


# --- Organizations ---


class OrgCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class OrgUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)


class OrgOut(BaseModel):
    id: str
    name: str
    slug: str
    role: Role
    plan: str = "free"
    ssoEnabled: bool = False
    ssoRequired: bool = False
    ssoDomains: list[str] = Field(default_factory=list)
    createdAt: datetime
    updatedAt: datetime


# --- Teams ---


class TeamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class TeamUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    # When True, agent write-back lands as `draft` (held for human approval) instead
    # of going straight live. Enforced in the agent create_memory path.
    agentWriteReview: bool | None = None


class TeamOut(BaseModel):
    id: str
    orgId: str
    name: str
    slug: str
    agentWriteReview: bool = False
    createdAt: datetime
    updatedAt: datetime


# --- Memberships ---


class MemberInvite(BaseModel):
    email: EmailStr
    role: Role = Role.editor
    teamId: str | None = None


class MemberUpdate(BaseModel):
    role: Role


class MemberOut(BaseModel):
    userId: str
    email: EmailStr
    name: str
    role: Role
    teamId: str | None = None


# --- Folders (projects within a team) ---


class FolderCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    parentId: str | None = None


class FolderUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    parentId: str | None = None


class FolderOut(BaseModel):
    id: str
    teamId: str
    name: str
    parentId: str | None = None
    createdAt: datetime
    updatedAt: datetime


# --- Memories (was: notes) ---


class MemoryCreate(BaseModel):
    title: str = Field(min_length=1, max_length=180)
    content: str = Field(default="", max_length=500_000)
    type: MemoryType = MemoryType.note
    folderId: str | None = None
    tags: list[str] = Field(default_factory=list, max_length=50)
    status: MemoryStatus = MemoryStatus.active


class MemoryUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=180)
    content: str | None = Field(default=None, max_length=500_000)
    type: MemoryType | None = None
    folderId: str | None = None
    tags: list[str] | None = Field(default=None, max_length=50)
    status: MemoryStatus | None = None


class MemoryOut(BaseModel):
    id: str
    orgId: str
    teamId: str
    folderId: str | None = None
    type: MemoryType
    status: MemoryStatus
    title: str
    content: str
    tags: list[str]
    linkedMemoryIds: list[str]
    unresolvedLinks: list[str]
    source: MemorySource
    sourceRef: dict[str, Any] | None = None
    helpfulCount: int = 0
    notHelpfulCount: int = 0
    lastVerifiedAt: datetime | None = None
    verifiedBy: str | None = None
    createdBy: str | None = None
    updatedBy: str | None = None
    createdAt: datetime
    updatedAt: datetime
    lastOpenedAt: datetime | None = None
    deletedAt: datetime | None = None


class MemoryListItem(BaseModel):
    id: str
    orgId: str
    teamId: str
    folderId: str | None = None
    type: MemoryType
    status: MemoryStatus
    title: str
    tags: list[str]
    linkedMemoryIds: list[str]
    unresolvedLinks: list[str]
    source: MemorySource
    helpfulCount: int = 0
    notHelpfulCount: int = 0
    lastVerifiedAt: datetime | None = None
    createdAt: datetime
    updatedAt: datetime
    lastOpenedAt: datetime | None = None
    deletedAt: datetime | None = None


class MemoryListResponse(BaseModel):
    memories: list[MemoryListItem]


class MemoryFeedback(BaseModel):
    """An agent's signal on whether a doc it read actually helped, feeds retrieval
    ranking and the low-signal report. Posted via the `mark_helpful` MCP tool."""

    helpful: bool
    note: str | None = Field(default=None, max_length=2000)


# --- API keys (machine auth for agents) ---


class ApiKeyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    scopes: list[ApiScope] = Field(default_factory=lambda: [ApiScope.memory_read])
    teamId: str | None = None
    expiresAt: datetime | None = None


class ApiKeyOut(BaseModel):
    id: str
    orgId: str
    teamId: str | None = None
    name: str
    prefix: str
    scopes: list[ApiScope]
    createdAt: datetime
    lastUsedAt: datetime | None = None
    expiresAt: datetime | None = None
    revokedAt: datetime | None = None


class ApiKeyCreated(ApiKeyOut):
    key: str


# --- Map (agent entry point) ---


class MapNode(BaseModel):
    id: str
    title: str
    type: MemoryType
    status: MemoryStatus
    tags: list[str]


class MapEdge(BaseModel):
    source: str
    target: str


class MapResponse(BaseModel):
    teamId: str
    mapMemory: MemoryOut | None = None
    nodes: list[MapNode]
    edges: list[MapEdge]


class AuditEntryOut(BaseModel):
    id: str
    action: str
    actor: str
    keyName: str | None = None
    teamId: str | None = None
    memoryId: str | None = None
    memoryTitle: str | None = None
    memoryDeleted: bool = False
    query: str | None = None
    at: datetime


class AuditResponse(BaseModel):
    entries: list[AuditEntryOut]
    total: int | None = None
    keyNames: list[str] | None = None


def document_id(document: dict[str, Any]) -> str:
    return str(document["_id"])
