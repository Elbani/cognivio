from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from collections.abc import Awaitable, Callable
from typing import TypeVar

from fastapi import FastAPI
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING, TEXT
from pymongo.errors import OperationFailure

from app.core.config import settings

logger = logging.getLogger("app.db")

client: AsyncIOMotorClient | None = None

T = TypeVar("T")


async def run_atomic(
    db: AsyncIOMotorDatabase, work: Callable[[object | None], Awaitable[T]]
) -> T:
    """Run a multi-document mutation atomically when the deployment supports transactions
    (replica set / Atlas), falling back to a plain sequential run on standalone Mongo.

    `work` receives the session (or None) and MUST thread it into every db call it makes
    (`session=session`). The fallback path passes None, which is exactly the prior
    non-transactional behavior, so standalone dev/CI is never worse off than before."""
    try:
        async with await db.client.start_session() as session:
            return await session.with_transaction(lambda s: work(s))
    except OperationFailure as exc:
        msg = str(exc)
        if "Transaction numbers" in msg or "replica set" in msg or "not supported" in msg:
            logger.warning("Transactions unavailable (%s), running mutation non-atomically.", exc)
            return await work(None)
        raise


def get_client() -> AsyncIOMotorClient:
    if client is None:
        raise RuntimeError("MongoDB client has not been initialized")
    return client


def get_db() -> AsyncIOMotorDatabase:
    return get_client()[settings.mongo_db]


async def create_indexes(db: AsyncIOMotorDatabase) -> None:
    # Users
    await db.users.create_index("email", unique=True)

    # Organizations
    await db.organizations.create_index("slug", unique=True)

    # Teams: unique slug within an org
    await db.teams.create_index([("orgId", ASCENDING), ("slug", ASCENDING)], unique=True)

    # Memberships: one membership row per (user, org, team-scope)
    await db.memberships.create_index(
        [("userId", ASCENDING), ("orgId", ASCENDING), ("teamId", ASCENDING)],
        unique=True,
    )
    await db.memberships.create_index([("orgId", ASCENDING)])

    # Folders (projects within a team): unique name per parent within a team
    await db.folders.create_index(
        [("teamId", ASCENDING), ("parentId", ASCENDING), ("nameNormalized", ASCENDING)],
        unique=True,
    )

    # Memories
    # Title is the [[wiki-link]] target and the agent upsert key, so (teamId,
    # titleNormalized) must be unique among LIVE docs, a partial index keyed on
    # deletedAt:null lets a trashed doc keep its old title without blocking a new one.
    # Wrapped because an existing DB with pre-seeded duplicates would reject the unique
    # build; we fall back to the non-unique index and log, so startup never crashes (the
    # atomic upsert in create_memory is the primary guard regardless).
    try:
        await db.memories.create_index(
            [("teamId", ASCENDING), ("titleNormalized", ASCENDING)],
            unique=True,
            partialFilterExpression={"deletedAt": None},
            name="uniq_team_title_active",
        )
    except OperationFailure as exc:
        logger.warning(
            "Could not build unique (teamId, titleNormalized) index (%s), likely "
            "pre-existing duplicate titles. Falling back to non-unique; dedup to enable "
            "the constraint.", exc,
        )
        await db.memories.create_index([("teamId", ASCENDING), ("titleNormalized", ASCENDING)])
    await db.memories.create_index([("orgId", ASCENDING), ("deletedAt", ASCENDING)])
    await db.memories.create_index([("teamId", ASCENDING), ("deletedAt", ASCENDING), ("updatedAt", ASCENDING)])
    await db.memories.create_index([("teamId", ASCENDING), ("deletedAt", ASCENDING), ("folderId", ASCENDING)])
    await db.memories.create_index([("teamId", ASCENDING), ("type", ASCENDING), ("status", ASCENDING)])
    await db.memories.create_index([("teamId", ASCENDING), ("lastOpenedAt", ASCENDING)])
    await db.memories.create_index(
        [("title", TEXT), ("content", TEXT), ("tags", TEXT)],
        default_language="english",
    )

    # Memory version history (revisions per doc, newest-first)
    await db.memory_versions.create_index([("memoryId", ASCENDING), ("supersededAt", DESCENDING)])

    # Project documentation: human-facing developer handbook, versioned snapshots per team.
    # A separate collection from memories, deliberately NEVER read by agent retrieval. Each
    # publish is a new version; exactly one is "current". The partial-unique index enforces
    # the single-current invariant (wrapped like the memories one so a legacy DB never blocks
    # startup); (teamId, version) is unique so version numbers can't collide.
    await db.project_docs.create_index([("teamId", ASCENDING), ("version", DESCENDING)], unique=True)
    try:
        await db.project_docs.create_index(
            [("teamId", ASCENDING), ("status", ASCENDING)],
            unique=True,
            partialFilterExpression={"status": "current"},
            name="uniq_team_current_projectdoc",
        )
    except OperationFailure as exc:
        logger.warning(
            "Could not build unique project_docs current index (%s), falling back to "
            "non-unique.", exc,
        )
        await db.project_docs.create_index([("teamId", ASCENDING), ("status", ASCENDING)])

    # Repo connection: one per team
    await db.repos.create_index("teamId", unique=True)

    # Password reset tokens: look up by hash; auto-expire via a TTL index on expiresAt.
    await db.password_resets.create_index("tokenHash")
    await db.password_resets.create_index("expiresAt", expireAfterSeconds=0)

    # Email verification tokens: same shape (hash lookup + TTL).
    await db.email_verifications.create_index("tokenHash")
    await db.email_verifications.create_index("expiresAt", expireAfterSeconds=0)

    # Refresh tokens: hash lookup + TTL (expiry slides forward on each use).
    await db.refresh_tokens.create_index("tokenHash")
    await db.refresh_tokens.create_index("expiresAt", expireAfterSeconds=0)

    # API keys
    await db.api_keys.create_index("keyHash", unique=True)
    await db.api_keys.create_index([("orgId", ASCENDING)])

    # Audit log
    await db.audit_log.create_index([("orgId", ASCENDING), ("at", ASCENDING)])
    # Platform-wide usage analytics (admin /usage, /overview) scan the whole window by time.
    await db.audit_log.create_index([("at", DESCENDING)])

    # Security events (abuse / suspicious-behavior signals for the admin console):
    # newest-first listing, filter by type/severity, auto-expire after 90 days.
    await db.security_events.create_index([("at", DESCENDING)])
    await db.security_events.create_index([("type", ASCENDING), ("at", DESCENDING)])
    await db.security_events.create_index([("severity", ASCENDING), ("at", DESCENDING)])
    await db.security_events.create_index("at", expireAfterSeconds=90 * 24 * 3600)

    # Admin action log (who suspended/deleted what): newest-first, kept indefinitely.
    await db.admin_actions.create_index([("at", DESCENDING)])


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    global client
    # tz_aware=True so datetimes come back timezone-aware (UTC); they then serialize
    # to ISO with a +00:00 offset, so clients never misread a UTC time as local.
    client = AsyncIOMotorClient(settings.mongo_uri, tz_aware=True)
    await create_indexes(get_db())
    logger.info("MongoDB connected and indexes ensured")
    try:
        yield
    finally:
        client.close()
        client = None
