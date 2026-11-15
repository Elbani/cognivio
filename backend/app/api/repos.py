"""Per-team repo connection (read-only PAT) → server-side coverage & drift.

Connecting a repo lets the platform answer "which parts of the codebase have no docs?"
and run drift detection server-side (so the zero-setup Remote MCP users get it too,
the local check_drift needs the user's filesystem). The token is stored to call the host
API and is never returned by any endpoint.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from datetime import datetime, timezone
from urllib.parse import urlparse

from bson import ObjectId
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import Db, TeamCtx, ensure_role
from app.core.security import decrypt_secret, encrypt_secret
from app.models.enums import Role
from app.repo_providers import (
    RepoError,
    compute_coverage,
    last_commit_dates,
    list_tree,
    referenced_files,
    verify_and_default_branch,
    web_file_url,
)

router = APIRouter(prefix="/api", tags=["repos"])


class RepoConnect(BaseModel):
    provider: str = Field(pattern="^(github|gitlab)$")
    projectPath: str = Field(min_length=1, max_length=200)  # "owner/repo" or "group/project"
    token: str = Field(min_length=1, max_length=400)
    baseUrl: str | None = None  # self-hosted GitLab/GHE; default to the public host
    defaultBranch: str | None = None  # auto-detected if omitted


def _status(repo: dict | None) -> dict:
    if repo is None:
        return {"connected": False}
    return {
        "connected": True,
        "provider": repo["provider"],
        "projectPath": repo["projectPath"],
        "baseUrl": repo.get("baseUrl"),
        "defaultBranch": repo.get("defaultBranch"),
        "connectedAt": repo.get("createdAt"),
        "updatedAt": repo.get("updatedAt"),
    }


def _cfg(repo: dict) -> dict:
    return {
        "provider": repo["provider"],
        "projectPath": repo["projectPath"],
        "baseUrl": repo.get("baseUrl"),
        "defaultBranch": repo.get("defaultBranch"),
        "token": decrypt_secret(repo["token"]),
    }


async def _validate_base_url(base_url: str) -> str:
    """Reject a self-hosted `baseUrl` that points at a private/internal address (SSRF):
    the server fetches this URL with the user's token, so it must not be coaxed into
    hitting cloud metadata endpoints (169.254.169.254), localhost, or RFC1918 hosts.
    Resolves the host and blocks any non-public address."""
    parsed = urlparse(base_url)
    if parsed.scheme != "https":
        raise HTTPException(status_code=400, detail="baseUrl must use https.")
    host = parsed.hostname
    if not host:
        raise HTTPException(status_code=400, detail="baseUrl is missing a host.")
    try:
        # getaddrinfo is blocking, run it off the event loop so a slow DNS lookup on this
        # admin-only call can't stall the worker.
        infos = await asyncio.to_thread(
            socket.getaddrinfo, host, parsed.port or 443, proto=socket.IPPROTO_TCP
        )
    except socket.gaierror as e:
        raise HTTPException(status_code=400, detail="baseUrl host does not resolve.") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        # is_global is False for private, loopback, link-local, shared (100.64/10),
        # reserved and unspecified ranges alike.
        if not ip.is_global or ip.is_multicast:
            raise HTTPException(
                status_code=400, detail="baseUrl resolves to a disallowed internal address."
            )
    return base_url.rstrip("/")


@router.get("/teams/{team_id}/repo")
async def get_repo(ctx: TeamCtx, db: Db) -> dict:
    repo = await db.repos.find_one({"teamId": ctx.team_id})
    return _status(repo)


@router.put("/teams/{team_id}/repo")
async def connect_repo(payload: RepoConnect, ctx: TeamCtx, db: Db) -> dict:
    ensure_role(ctx.role, Role.admin)
    cfg = {
        "provider": payload.provider,
        "projectPath": payload.projectPath.strip().strip("/"),
        "baseUrl": await _validate_base_url(payload.baseUrl) if payload.baseUrl else None,
        "defaultBranch": payload.defaultBranch,
        "token": payload.token,
    }
    try:
        branch = cfg["defaultBranch"] or await verify_and_default_branch(cfg)
    except RepoError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    now = datetime.now(timezone.utc)
    existing = await db.repos.find_one({"teamId": ctx.team_id})
    doc = {
        "teamId": ctx.team_id,
        "orgId": ctx.org_id,
        "provider": cfg["provider"],
        "projectPath": cfg["projectPath"],
        "baseUrl": cfg["baseUrl"],
        "defaultBranch": branch,
        "token": encrypt_secret(payload.token),  # encrypted at rest; decrypted in _cfg
        "connectedBy": ctx.user_id,
        "updatedAt": now,
    }
    if existing:
        await db.repos.update_one({"_id": existing["_id"]}, {"$set": doc})
        doc = {**existing, **doc}
    else:
        doc["_id"] = str(ObjectId())
        doc["createdAt"] = now
        await db.repos.insert_one(doc)
    return _status(doc)


@router.delete("/teams/{team_id}/repo", status_code=204, response_model=None)
async def disconnect_repo(ctx: TeamCtx, db: Db) -> None:
    ensure_role(ctx.role, Role.admin)
    await db.repos.delete_one({"teamId": ctx.team_id})


async def coverage_report(db, repo: dict, team_id: str) -> dict:
    """Compute documented-vs-undocumented coverage + drifted docs for a connected repo.
    Shared by the human coverage endpoint and the agent drift endpoint. Raises RepoError
    on a provider failure (callers translate to the right HTTP status)."""
    cfg = _cfg(repo)
    tree = await list_tree(cfg)
    files = list(tree)
    fileset = set(files)

    # gather active docs (content + verification time + which files each cites)
    docs = [
        d async for d in db.memories.find(
            {"teamId": team_id, "deletedAt": None},
            {"title": 1, "content": 1, "lastVerifiedAt": 1},
        )
    ]
    referenced = referenced_files((d.get("content", "") for d in docs), fileset)
    coverage = compute_coverage(files, referenced)

    # drift: for the files docs actually cite, fetch last-commit dates and compare
    commit_dates = await last_commit_dates(cfg, sorted(referenced)) if referenced else {}
    drifted: list[dict] = []
    for d in docs:
        cited = referenced_files([d.get("content", "")], fileset)

        verified = d.get("lastVerifiedAt")
        if verified is None:
            continue
        if verified.tzinfo is None:
            verified = verified.replace(tzinfo=timezone.utc)
        changed = []
        for path in cited:
            cd = commit_dates.get(path)
            if cd and cd > verified:
                changed.append({"file": path, "url": web_file_url(cfg, path), "changedAt": cd.isoformat()})
        if changed:
            drifted.append({"id": d["_id"], "title": d["title"], "changedFiles": changed})

    return {
        **coverage,
        "provider": repo["provider"],
        "projectPath": repo["projectPath"],
        "defaultBranch": repo.get("defaultBranch"),
        "drifted": drifted,
    }


@router.get("/teams/{team_id}/repo/coverage")
async def repo_coverage(ctx: TeamCtx, db: Db) -> dict:
    """Documented-vs-undocumented files (per directory) + docs that have drifted (a doc
    references a file whose last commit is newer than the doc's last verification)."""
    repo = await db.repos.find_one({"teamId": ctx.team_id})
    if repo is None:
        raise HTTPException(status_code=404, detail="No repo connected for this team")
    try:
        report = await coverage_report(db, repo, ctx.team_id)
    except RepoError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    report["note"] = (
        "documentedCount = repo files a doc cites by exact path. Low coverage isn't bad "
        "per se, use the per-directory breakdown to spot areas agents work in but nobody "
        "has documented. Drifted docs reference code that changed after they were verified."
    )
    return report
