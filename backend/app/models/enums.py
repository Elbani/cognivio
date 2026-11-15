from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    owner = "owner"
    admin = "admin"
    editor = "editor"
    viewer = "viewer"


# Higher number = more privilege. Used for "at least this role" checks.
ROLE_RANK: dict[str, int] = {
    Role.viewer: 0,
    Role.editor: 1,
    Role.admin: 2,
    Role.owner: 3,
}


def role_at_least(have: str, need: str) -> bool:
    return ROLE_RANK.get(have, -1) >= ROLE_RANK.get(need, 99)


class MemoryType(str, Enum):
    map = "map"
    architecture = "architecture"
    playbook = "playbook"
    incident = "incident"
    decision = "decision"
    lesson = "lesson"
    note = "note"


class MemoryStatus(str, Enum):
    active = "active"
    draft = "draft"
    deprecated = "deprecated"


class MemorySource(str, Enum):
    manual = "manual"
    agent = "agent"
    ingested = "ingested"


class ApiScope(str, Enum):
    memory_read = "memory:read"
    memory_write = "memory:write"
    map_read = "map:read"
