from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Annotated

from bson import ObjectId
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials
from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ReturnDocument
from pymongo.errors import DuplicateKeyError

from app.api.deps import Db, bearer_scheme
from app.core.agent_rules import rule_file_for
from app.core.events import SEVERITY_WARN, log_security_event
from app.api.memories import (
    memory_list_item,
    memory_out,
    refresh_memory_links,
    snapshot_version,
)
from app.api.orgs import team_out
from app.api.repos import coverage_report
from app.core.embeddings import cosine, embed_and_store, embed_query
from app.api.project_docs import (
    RECOMMENDED_SECTIONS,
    ProjectDocsPublishIn,
    project_doc_version_out,
)
from app.core.security import decrypt_secret, hash_api_key
from app.db.database import get_db, run_atomic
from app.repo_providers import RepoError, compute_coverage, list_files, referenced_files
from app.models.enums import ApiScope, MemorySource, MemoryStatus, MemoryType
from app.models.schemas import (
    MapEdge,
    MapNode,
    MapResponse,
    MemoryCreate,
    MemoryFeedback,
    MemoryListResponse,
    MemoryOut,
    TeamOut,
    document_id,
)
from app.utils import normalize_tag, normalize_title

router = APIRouter(prefix="/api/v1", tags=["agent"])

# Drafts are agent write-back held for human approval (the review queue). They must
# never be served to agents as authoritative, so every agent READ path filters them out.
_NOT_DRAFT = {"$ne": MemoryStatus.draft.value}


@dataclass
class AgentContext:
    key: dict
    scopes: set[str]

    @property
    def org_id(self) -> str:
        return self.key["orgId"]

    @property
    def restricted_team_id(self) -> str | None:
        return self.key.get("teamId")


async def resolve_api_key(
    db: AsyncIOMotorDatabase, raw_token: str, request: Request | None = None
) -> AgentContext | None:
    """Validate an `ak_…` key and return its AgentContext, or None if missing/revoked/expired.
    Shared by the REST dependency below and the remote MCP endpoint (app.mcp_remote).
    A non-empty-but-invalid token is logged as a security event (abuse signal)."""
    if not raw_token:
        return None
    key = await db.api_keys.find_one({"keyHash": hash_api_key(raw_token)})
    if key is None or key.get("revokedAt") is not None:
        await log_security_event(
            db, "invalid_api_key", severity=SEVERITY_WARN, request=request,
            reason="revoked" if key else "unknown", prefix=raw_token[:8],
        )
        return None
    expires = key.get("expiresAt")
    if expires is not None and expires <= datetime.now(timezone.utc):
        await log_security_event(
            db, "invalid_api_key", severity=SEVERITY_WARN, request=request,
            org_id=key.get("orgId"), reason="expired", prefix=raw_token[:8],
        )
        return None
    await db.api_keys.update_one(
        {"_id": key["_id"]}, {"$set": {"lastUsedAt": datetime.now(timezone.utc)}}
    )
    return AgentContext(key=key, scopes=set(key.get("scopes", [])))


async def agent_context(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
) -> AgentContext:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing API key")
    ctx = await resolve_api_key(get_db(), credentials.credentials, request)
    if ctx is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired API key")
    return ctx


AgentCtx = Annotated[AgentContext, Depends(agent_context)]


def require_scope(ctx: AgentContext, *allowed: ApiScope) -> None:
    if not any(s.value in ctx.scopes for s in allowed):
        raise HTTPException(status_code=403, detail="API key lacks required scope")


async def _agent_team(db: AsyncIOMotorDatabase, ctx: AgentContext, team_id: str) -> dict:
    if ctx.restricted_team_id is not None and ctx.restricted_team_id != team_id:
        raise HTTPException(status_code=403, detail="API key is not scoped to this team")
    team = await db.teams.find_one({"_id": team_id, "orgId": ctx.org_id})
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    return team


async def _agent_memory(db: AsyncIOMotorDatabase, ctx: AgentContext, memory_id: str) -> dict:
    memory = await db.memories.find_one({"_id": memory_id, "orgId": ctx.org_id, "deletedAt": None})
    if memory is None:
        raise HTTPException(status_code=404, detail="Memory not found")
    if ctx.restricted_team_id is not None and memory["teamId"] != ctx.restricted_team_id:
        raise HTTPException(status_code=403, detail="API key is not scoped to this team")
    return memory


async def _audit(
    db: AsyncIOMotorDatabase, ctx: AgentContext, action: str, **extra: object
) -> None:
    await db.audit_log.insert_one(
        {
            "_id": str(ObjectId()),
            "orgId": ctx.org_id,
            "actor": "agent",
            "keyId": ctx.key["_id"],
            "keyName": ctx.key.get("name"),
            "action": action,
            "at": datetime.now(timezone.utc),
            **extra,
        }
    )


# --- Discovery ---


@router.get("/whoami")
async def whoami(ctx: AgentCtx, db: Db) -> dict:
    org = await db.organizations.find_one({"_id": ctx.org_id})
    return {
        "org": {"id": ctx.org_id, "name": org["name"] if org else None},
        "keyName": ctx.key.get("name"),
        "scopes": sorted(ctx.scopes),
        "restrictedTeamId": ctx.restricted_team_id,
    }


def agent_rule_payload(tool: str) -> dict:
    """The exact rule file the agent should install, plus a one-paragraph instruction.
    Shared by the REST endpoint and the `setup_rule` MCP tool (both transports). Raises
    ValueError on an unknown tool; callers translate that to a 400."""
    spec = rule_file_for(tool)
    how = (
        f"Write this file in the repo root so future sessions consult the knowledge base "
        f"automatically. {'Append it as a new section to' if spec['append'] else 'Create (or overwrite)'} "
        f"`{spec['path']}` with the content below, verbatim, creating any parent directories. "
        f"Then confirm to the user it's installed."
    )
    return {**spec, "instructions": how}


@router.get("/agent-rule")
async def agent_rule(tool: str, ctx: AgentCtx, db: Db) -> dict:
    """Return the always-on rule file the agent should write so it uses Cognivio on every
    task (prime_context before, write_memory after). `tool` is the editor: claude, cursor,
    or codex. The agent writes the returned `path` with the returned `content` verbatim,
    this replaces error-prone manual copy-paste and gets the per-editor format right (Cursor
    needs `alwaysApply: true` frontmatter to load every turn)."""
    try:
        return agent_rule_payload(tool)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/teams", response_model=list[TeamOut])
async def list_teams(ctx: AgentCtx, db: Db) -> list[TeamOut]:
    require_scope(ctx, ApiScope.memory_read, ApiScope.map_read)
    query: dict = {"orgId": ctx.org_id}
    if ctx.restricted_team_id is not None:
        query["_id"] = ctx.restricted_team_id
    return [team_out(t) async for t in db.teams.find(query).sort("name", 1)]


# --- The map: read this first ---


@router.get("/teams/{team_id}/map", response_model=MapResponse)
async def get_map(team_id: str, ctx: AgentCtx, db: Db) -> MapResponse:
    require_scope(ctx, ApiScope.map_read, ApiScope.memory_read)
    await _agent_team(db, ctx, team_id)

    map_doc = await db.memories.find_one(
        {"teamId": team_id, "type": MemoryType.map.value, "deletedAt": None, "status": _NOT_DRAFT},
        sort=[("updatedAt", -1)],
    )

    nodes: list[MapNode] = []
    node_ids: set[str] = set()
    links: list[tuple[str, list[str]]] = []
    cursor = db.memories.find(
        {"teamId": team_id, "deletedAt": None, "status": _NOT_DRAFT},
        {"title": 1, "type": 1, "status": 1, "tags": 1, "linkedMemoryIds": 1},
    )
    async for m in cursor:
        mid = document_id(m)
        node_ids.add(mid)
        nodes.append(
            MapNode(
                id=mid,
                title=m["title"],
                type=MemoryType(m.get("type", "note")),
                status=m.get("status", "active"),
                tags=m.get("tags", []),
            )
        )
        links.append((mid, m.get("linkedMemoryIds", [])))

    edges = [
        MapEdge(source=s, target=t) for s, targets in links for t in targets if t in node_ids
    ]
    response = MapResponse(
        teamId=team_id,
        mapMemory=memory_out(map_doc) if map_doc else None,
        nodes=nodes,
        edges=edges,
    )
    await _audit(db, ctx, "map.read", teamId=team_id)
    return response


# --- Search & read ---


@router.get("/teams/{team_id}/memories", response_model=MemoryListResponse)
async def search_memories(
    team_id: str,
    ctx: AgentCtx,
    db: Db,
    q: str | None = None,
    type: MemoryType | None = None,
    tag: str | None = None,
    status_: MemoryStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=25, ge=1, le=100),
) -> MemoryListResponse:
    require_scope(ctx, ApiScope.memory_read)
    await _agent_team(db, ctx, team_id)

    query: dict = {"teamId": team_id, "deletedAt": None}
    if type is not None:
        query["type"] = type.value
    if tag:
        query["tags"] = normalize_tag(tag)
    # Honor an explicit status filter; otherwise hide unapproved drafts from agents.
    query["status"] = status_.value if status_ is not None else _NOT_DRAFT

    # Full-text search over the (title, content, tags) text index: tokenized + stemmed,
    # ranked by relevance. This replaces a whole-phrase regex that only matched the exact
    # substring (so "aggregation calc gate" found nothing unless that literal string existed).
    projection: dict = {"content": 0}
    if q and q.strip():
        query["$text"] = {"$search": q.strip()}
        projection["score"] = {"$meta": "textScore"}
        cursor = db.memories.find(query, projection).sort(
            [("score", {"$meta": "textScore"})]
        ).limit(limit)
    else:
        cursor = db.memories.find(query, projection).sort("updatedAt", -1).limit(limit)
    items = [memory_list_item(m) async for m in cursor]
    response = MemoryListResponse(memories=items)
    # resultCount feeds the knowledge-gap report (a zero-result search = a missing doc)
    await _audit(db, ctx, "memory.search", teamId=team_id, query=q, resultCount=len(items))
    return response


@router.get("/memories/{memory_id}", response_model=MemoryOut)
async def get_memory(memory_id: str, ctx: AgentCtx, db: Db) -> MemoryOut:
    require_scope(ctx, ApiScope.memory_read)
    memory = await _agent_memory(db, ctx, memory_id)
    response = memory_out(memory)
    await _audit(db, ctx, "memory.read", memoryId=memory_id, teamId=memory["teamId"])
    return response


@router.get("/memories/{memory_id}/related", response_model=MemoryListResponse)
async def related_memories(memory_id: str, ctx: AgentCtx, db: Db) -> MemoryListResponse:
    require_scope(ctx, ApiScope.memory_read)
    memory = await _agent_memory(db, ctx, memory_id)

    outbound = memory.get("linkedMemoryIds", [])
    related_ids = set(outbound)
    # backlinks: memories that link to this one
    async for m in db.memories.find(
        {"teamId": memory["teamId"], "deletedAt": None, "linkedMemoryIds": memory_id},
        {"_id": 1},
    ):
        related_ids.add(document_id(m))
    related_ids.discard(memory_id)

    items = []
    async for m in db.memories.find({"_id": {"$in": list(related_ids)}}, {"content": 0}):
        items.append(memory_list_item(m))
    return MemoryListResponse(memories=items)


# --- Feedback: did the doc actually help? (closes the learning loop) ---


@router.post("/memories/{memory_id}/feedback")
async def submit_feedback(memory_id: str, payload: MemoryFeedback, ctx: AgentCtx, db: Db) -> dict:
    """Record whether a doc an agent read actually helped. Feeds retrieval ranking,
    helpful docs float up, ones flagged as noise sink (see _helpfulness_boost), and the
    low-signal report. Requires a memory:read key: the reading agent gives the signal."""
    require_scope(ctx, ApiScope.memory_read)
    memory = await _agent_memory(db, ctx, memory_id)  # enforces org + team scope
    field = "helpfulCount" if payload.helpful else "notHelpfulCount"
    updated = await db.memories.find_one_and_update(
        {"_id": memory_id},
        {"$inc": {field: 1}},
        return_document=ReturnDocument.AFTER,
    )
    await _audit(
        db, ctx, "memory.feedback", memoryId=memory_id, teamId=memory["teamId"],
        helpful=payload.helpful, note=payload.note or None,
    )

    return {
        "id": memory_id,
        "helpfulCount": updated.get("helpfulCount", 0),
        "notHelpfulCount": updated.get("notHelpfulCount", 0),
    }


# --- Context pack: one-shot retrieval (collapses orientation into a single call) ---


# A doc must clear this to count as a real hit (keeps loose single-word content
# matches from flooding results or masking knowledge gaps).
_RELEVANCE_FLOOR = 6

# Above this many docs in scope, context_pack stops scanning the whole collection and
# narrows candidates with the text index first (then re-scores them). Below it, the full
# scan is cheap and keeps behavior identical for typical small KBs.
_PREFILTER_THRESHOLD = 400
_PREFILTER_LIMIT = 200

# Hybrid retrieval: a doc's cosine similarity (0..1 after relu) is scaled by _SEM_WEIGHT
# and added to its lexical score, so semantics reorder results and can surface a doc whose
# wording differs from the query. A strong semantic match (>= _SEM_FLOOR) qualifies a doc
# even if it misses the lexical floor. All of this is inert when embeddings are disabled
# (cosine returns 0 / query vector is None), so behavior is then exactly the lexical path.
_SEM_WEIGHT = 16
_SEM_FLOOR = 0.55
# Days since last verification past which a doc is flagged stale to the agent (a freshness
# signal so it can weight a possibly-outdated doc, it doesn't change ranking by itself).
_STALE_DAYS = 90


def _relevance(mem: dict, terms: list[str], phrase: str) -> int:
    """Cheap lexical relevance using whole-word matching (no substring noise):
    title/tag hits dominate, content hits add a little. Fast over small KBs."""
    title = (mem.get("title") or "").lower()
    content = ((mem.get("content") or "")[:20000]).lower()
    tags = [t.lower() for t in mem.get("tags", [])]
    score = 0
    if phrase and phrase in title:
        score += 12
    elif phrase and phrase in content:
        score += 4
    for t in terms:
        word = re.compile(r"\b" + re.escape(t) + r"\b")
        if word.search(title):
            score += 8
        if any(t == tag or word.search(tag) for tag in tags):
            score += 4
        c = len(word.findall(content))
        if c:
            score += min(c, 3)
    return score


def _helpfulness_boost(mem: dict) -> int:
    """Rank adjustment from agent feedback (the mark_helpful loop): docs agents found
    useful float up, docs they flagged as noise sink. Capped and applied ONLY to docs
    that already cleared the lexical floor, so feedback reorders relevant results, it
    never surfaces an irrelevant-but-liked doc."""
    net = mem.get("helpfulCount", 0) - mem.get("notHelpfulCount", 0)
    return max(-4, min(8, net))


def _doc_age_days(mem: dict, now: datetime) -> int | None:
    ts = mem.get("lastVerifiedAt") or mem.get("updatedAt")
    if ts is None:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (now - ts).days


def _recency_boost(mem: dict, now: datetime) -> int:
    """Small nudge so a recently-verified doc edges out an equally-relevant stale one.
    Ranking only, never qualifies a doc on its own."""
    age = _doc_age_days(mem, now)
    if age is None:
        return 0
    if age <= 30:
        return 3
    if age <= 90:
        return 1
    return 0


@router.get("/context")
async def context_pack(
    ctx: AgentCtx,
    db: Db,
    q: str = Query(..., min_length=2, description="The task or question to gather context for"),
    limit: int = Query(default=6, ge=1, le=15),
) -> dict:
    """One call that returns everything needed to start a task: the index map(s)
    for orientation plus the most relevant full docs. Replaces the
    list_teams -> read_map -> search -> get_memory -> get_related round-trips
    (each of which re-reads the whole cached context) with a single response."""
    require_scope(ctx, ApiScope.memory_read)
    now = datetime.now(timezone.utc)
    phrase = " ".join(q.lower().split())
    terms = [w for w in re.findall(r"[a-z0-9]+", q.lower()) if len(w) >= 3]

    # Semantic side of hybrid retrieval: embed the query once (None when embeddings are
    # disabled/unavailable, which makes everything below fall back to pure lexical).
    qvec = await embed_query(q)

    # Exclude unapproved drafts (the review queue): agents only ever prime on live docs.
    query: dict = {"orgId": ctx.org_id, "deletedAt": None, "status": _NOT_DRAFT}
    if ctx.restricted_team_id is not None:
        query["teamId"] = ctx.restricted_team_id

    doc_total = await db.memories.count_documents(query)

    # On a small KB, scan everything (cheap, and preserves the exact prior behavior).
    # Past a threshold, streaming every doc into memory on this hot endpoint is the
    # scaling cliff, narrow the candidate set with the (title, content, tags) text index
    # first, then re-score the candidates with the lexical relevance below. Maps are few,
    # so always include them in full for the orientation index.
    candidates: list[dict] = []
    if terms and doc_total > _PREFILTER_THRESHOLD:
        async for m in db.memories.find({**query, "type": MemoryType.map.value}):
            candidates.append(m)
        doc_proj = {
            "title": 1, "content": 1, "tags": 1, "type": 1,
            "helpfulCount": 1, "notHelpfulCount": 1, "lastVerifiedAt": 1, "embedding": 1,
            "score": {"$meta": "textScore"},
        }
        text_query = {**query, "type": {"$ne": MemoryType.map.value}, "$text": {"$search": q}}
        cursor = db.memories.find(text_query, doc_proj).sort(
            [("score", {"$meta": "textScore"})]
        ).limit(_PREFILTER_LIMIT)
        async for m in cursor:
            candidates.append(m)
    else:
        candidates = [m async for m in db.memories.find(query)]

    maps_scored: list[tuple[bool, int, dict]] = []
    docs_scored: list[tuple[int, dict]] = []
    for m in candidates:
        s = _relevance(m, terms, phrase)
        if m.get("type") == MemoryType.map.value:
            is_index = "index" in [t.lower() for t in m.get("tags", [])]
            maps_scored.append((is_index, s, m))
            continue
        # Hybrid: blend the lexical score with the (relu'd) semantic similarity. A doc
        # qualifies on lexical relevance OR a strong semantic match, so paraphrased queries
        # still surface the right doc. Feedback + recency reorder within the qualified set.
        sem = max(0.0, cosine(qvec, m.get("embedding"))) if qvec else 0.0
        if s >= _RELEVANCE_FLOOR or sem >= _SEM_FLOOR:
            combined = (
                s + _helpfulness_boost(m) + _recency_boost(m, now) + round(sem * _SEM_WEIGHT)
            )
            docs_scored.append((combined, m))

    # orientation: the single best index map (full); results as short EXCERPTS, not
    # full bodies, a fat one-shot payload persists in the cached context and gets
    # re-read every turn, which costs more than the round-trips it saves.
    maps_scored.sort(key=lambda x: (x[0], x[1]), reverse=True)
    docs_scored.sort(key=lambda x: x[0], reverse=True)
    top_maps = [m for _, _, m in maps_scored[:1]]
    top_docs = docs_scored[:limit]

    def _preview(m: dict, s: int) -> dict:
        content = m.get("content") or ""
        age = _doc_age_days(m, now)
        lv = m.get("lastVerifiedAt")
        return {
            "id": document_id(m),
            "title": m["title"],
            "type": m.get("type", "note"),
            "tags": m.get("tags", []),
            "score": s,
            "excerpt": content[:700] + ("…" if len(content) > 700 else ""),
            # Quality signals so the agent can weight a doc: usefulness (feedback) and
            # freshness (how long since it was verified, and whether that's now stale).
            "helpful": m.get("helpfulCount", 0),
            "notHelpful": m.get("notHelpfulCount", 0),
            "lastVerifiedAt": lv.isoformat() if hasattr(lv, "isoformat") else None,
            "stale": age is not None and age > _STALE_DAYS,
        }

    result: dict = {
        "query": q,
        "retrievalMode": "hybrid" if qvec else "lexical",
        "index": [memory_out(m) for m in top_maps],
        "results": [_preview(m, s) for s, m in top_docs],
        "resultCount": len(top_docs),
        "hint": (
            "Orientation map + the most relevant docs as excerpts. Each result has an `id`; "
            "call get_memory(id) to read the full body for the 1-2 docs you actually need to edit. "
            "Results carry freshness/usefulness signals (`stale`, `helpful`); prefer fresh, "
            "useful docs and re-verify a `stale` one if you rely on it. "
            "Follow the file/class pointers and [[links]] inside."
        ),
    }
    # Not initialized = there's no Project Map (the entry-point doc). When that's the
    # case, have the agent OFFER to initialize before doing the work, then build on it.
    if not maps_scored:
        result["setup"] = (
            f"Cognivio isn't initialized for this repository yet, there is no Project Map (the entry-point "
            f"doc; the KB currently has {doc_total} doc(s)). Before continuing:\n"
            "1. ASK THE USER once: \"Want me to initialize Cognivio for this repo?\"\n"
            "2. If YES, scan the repo, then use write_memory to create a starter set to build on: a 'map' titled "
            "'<Project> Map' (the entry point; link the others with [[Title]]), an 'architecture' doc 'How It "
            "Works' citing real files/classes, and a 'decision' doc for each non-obvious choice. Keep them concise.\n"
            "3. Then tell the user it's initialized and suggest they review and add/update docs as the project grows.\n"
            "4. If NO, just proceed with the task.\n"
            "Either way, still write_memory anything non-obvious you do in THIS task (that's how the KB grows)."
        )

    await _audit(db, ctx, "context.pack", query=q, resultCount=len(top_docs))
    return result


# --- Insights: knowledge gaps (turns failed lookups into a doc backlog) ---


@router.get("/insights/gaps")
async def knowledge_gaps(
    ctx: AgentCtx,
    db: Db,
    days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict:
    """Queries that agents searched for but found nothing, i.e. docs worth writing.
    Aggregated from zero-result searches and context packs."""
    require_scope(ctx, ApiScope.memory_read)
    since = datetime.now(timezone.utc) - timedelta(days=days)
    counts: dict[str, int] = {}
    cursor = db.audit_log.find(
        {
            "orgId": ctx.org_id,
            "action": {"$in": ["memory.search", "context.pack"]},
            "resultCount": 0,
            "at": {"$gte": since},
        }
    )
    async for e in cursor:
        key = " ".join(str(e.get("query") or "").lower().split())
        if key:
            counts[key] = counts.get(key, 0) + 1
    gaps = sorted(
        ({"query": k, "missCount": v} for k, v in counts.items()),
        key=lambda g: g["missCount"],
        reverse=True,
    )[:limit]
    return {
        "days": days,
        "gaps": gaps,
        "note": "Agents looked for these and the KB had nothing, candidate docs to write.",
    }


# --- Drift: docs whose cited code changed → propose an update (the freshness loop) ---


@router.get("/teams/{team_id}/drift")
async def team_drift(team_id: str, ctx: AgentCtx, db: Db) -> dict:
    """Docs that have DRIFTED, they cite a repo file whose last commit is newer than the
    doc's last verification, so the doc may now be wrong. Call this after connecting a repo
    (or periodically) to keep the KB fresh: for each drifted doc, read the changed file(s),
    update the doc with write_memory (same title = in-place update), and it re-verifies.
    Returns an empty list when no repo is connected or nothing has drifted."""
    require_scope(ctx, ApiScope.memory_read)
    await _agent_team(db, ctx, team_id)
    repo = await db.repos.find_one({"teamId": team_id})
    if repo is None:
        return {"repoConnected": False, "drifted": [], "note": "No repo connected for this team."}
    try:
        report = await coverage_report(db, repo, team_id)
    except RepoError:
        return {"repoConnected": True, "drifted": [], "note": "Could not reach the Git host."}

    drifted = report.get("drifted", [])
    await _audit(db, ctx, "repo.drift", teamId=team_id, resultCount=len(drifted))
    return {
        "repoConnected": True,
        "provider": report.get("provider"),
        "projectPath": report.get("projectPath"),
        "drifted": drifted,
        "instructions": (
            "For each drifted doc: read the changed file(s) at the given paths, then call "
            "write_memory with the SAME title to update the doc's content to match the new code "
            "(this updates it in place and re-verifies it). Skip a doc if the change doesn't "
            "affect what it documents." if drifted else
            "Nothing has drifted, every doc that cites code is still current."
        ),
    }


# --- Seeding: one-shot plan to initialize / fill out a KB from the repo ---


def _seed_instructions(initialized: bool, review: bool, undocumented_dirs: list[str]) -> str:
    """The playbook the seeding agent should follow, returned with live context so the
    agent knows what already exists, whether writes will be held for review, and which
    areas to target. The agent does the scanning/drafting (it has the repo + is the LLM);
    Cognivio only orchestrates and gates."""
    lines = [
        ("Refresh/extend this knowledge base" if initialized else "Initialize this knowledge base")
        + " by scanning the repo and writing starter docs, in THIS order so links resolve:",
        "0. Install the always-on rule so future sessions use the KB automatically: call "
        "setup_rule for your editor (claude / cursor / codex) and write the file it returns, "
        "verbatim, at the path it gives. Skip only if that file already has the Cognivio rule.",
        "1. Scan the repo: README, the top-level layout, and the key entry file(s) of each major subsystem.",
        "2. write_memory a 'decision' for each non-obvious choice (title 'Decision: <X>').",
        "3. write_memory one 'architecture' doc per major subsystem, citing REAL, full file paths "
        "(e.g. backend/app/api/agent.py) so coverage and drift detection work.",
        "4. LAST, write_memory a 'map' titled '<Project> Map' tagged ['index'] that links the docs above "
        "with [[Exact Title]] references (links resolve at write time, so the map must come last).",
        "Skip any title already in existingDocs, re-writing a title updates it in place, so it's safe to re-run.",
        "Never put example [[bracket]] syntax in a doc body unless it's a real link to another doc.",
    ]
    if undocumented_dirs:
        lines.append("Prioritize these undocumented areas first: " + ", ".join(undocumented_dirs) + ".")
    if review:
        lines.append("NOTE: this team holds agent write-back for review, your docs will land as drafts the "
                     "user approves in the Review tab, so it's safe to propose generously.")
    return "\n".join(lines)


@router.get("/teams/{team_id}/seed-plan")
async def seed_plan(team_id: str, ctx: AgentCtx, db: Db) -> dict:
    """Call this FIRST when asked to initialize/seed a knowledge base. Returns a concrete
    plan: what docs already exist (don't duplicate them), which repo areas have no docs
    (if a repo is connected), whether writes will be held for review, and the exact ordered
    steps to follow. You then do the scanning + drafting and write the docs via write_memory."""
    require_scope(ctx, ApiScope.memory_read)
    team = await _agent_team(db, ctx, team_id)

    existing: list[dict] = []
    has_map = False
    contents: list[str] = []
    async for m in db.memories.find(
        {"teamId": team_id, "deletedAt": None}, {"title": 1, "type": 1, "content": 1}
    ):
        existing.append({"id": document_id(m), "title": m["title"], "type": m.get("type", "note")})
        contents.append(m.get("content", ""))
        if m.get("type") == MemoryType.map.value:
            has_map = True

    # Best-effort repo coverage: only when a repo is connected; never fail the plan on it.
    coverage: dict | None = None
    undocumented_dirs: list[str] = []
    repo = await db.repos.find_one({"teamId": team_id})
    if repo is not None:
        cfg = {
            "provider": repo["provider"],
            "projectPath": repo["projectPath"],
            "baseUrl": repo.get("baseUrl"),
            "defaultBranch": repo.get("defaultBranch"),
            "token": decrypt_secret(repo["token"]),
        }
        try:
            files = await list_files(cfg)
            referenced = referenced_files(contents, set(files))
            cov = compute_coverage(files, referenced)
            undocumented_dirs = [
                d["dir"] for d in cov["byDir"] if d["documented"] < d["total"]
            ][:15]
            coverage = {
                "fileCount": cov["fileCount"],
                "documentedCount": cov["documentedCount"],
                "undocumentedDirs": undocumented_dirs,
                "undocumentedSample": cov["undocumentedSample"],
            }
        except RepoError:
            coverage = None

    review = bool(team.get("agentWriteReview"))
    await _audit(db, ctx, "seed.plan", teamId=team_id, resultCount=len(existing))
    return {
        "teamId": team_id,
        "initialized": has_map,
        "docCount": len(existing),
        "existingDocs": existing,
        "coverage": coverage,
        "repoConnected": repo is not None,
        "reviewEnabled": review,
        "recommendedOrder": ["decision", "architecture", "map"],
        "instructions": _seed_instructions(has_map, review, undocumented_dirs),
    }


# --- Project documentation: the human-facing developer handbook (NOT agent retrieval) ---


def _project_docs_instructions(has_docs: bool, undocumented_dirs: list[str]) -> str:
    """The playbook the agent follows to produce the developer handbook. It does the
    scanning/writing (it has the repo + is the LLM); Cognivio plans, stores, and versions."""
    lines = [
        ("Refresh" if has_docs else "Generate")
        + " the project's DEVELOPER DOCUMENTATION, a human-readable handbook for engineers. "
        "This is SEPARATE from the agent knowledge base and is NEVER used for agent retrieval; "
        "it exists for people reading the codebase. Scan the repo, then publish the full set of sections:",
        "1. Read the README, the top-level layout, build/config files, and the entry point of each subsystem.",
        "2. Write clear, narrative Markdown for a developer NEW to the codebase, explain the WHY, not just the what.",
        "3. Cover at least: " + ", ".join(s["title"] for s in RECOMMENDED_SECTIONS)
        + ". Add or drop sections to fit the project.",
        "4. Cite real file paths so readers can navigate. Keep each section focused.",
        "5. Publish ALL sections in ONE call to write_project_docs(team_id, summary, sections). Each publish "
        "creates a NEW version snapshot (the prior one is kept in history), so always send the COMPLETE handbook.",
    ]
    if undocumented_dirs:
        lines.append("Pay special attention to these less-documented areas: " + ", ".join(undocumented_dirs) + ".")
    return "\n".join(lines)


@router.get("/teams/{team_id}/project-docs/plan")
async def project_docs_plan(team_id: str, ctx: AgentCtx, db: Db) -> dict:
    """Call this FIRST when asked to generate or update the project's DEVELOPER DOCUMENTATION
    (the human-facing handbook, separate from the agent KB and never used in retrieval).
    Returns the recommended section outline, the sections that already exist (so you revise
    rather than start over), and, when a repo is connected, the least-documented areas. You
    then scan the repo and publish the full handbook via write_project_docs."""
    require_scope(ctx, ApiScope.memory_read)
    await _agent_team(db, ctx, team_id)

    current = await db.project_docs.find_one({"teamId": team_id, "status": "current"})
    existing_sections = [
        {"slug": s.get("slug"), "title": s.get("title")}
        for s in sorted((current or {}).get("sections", []), key=lambda s: s.get("order", 0))
    ]

    # Best-effort repo signal: never fail the plan if the host is unreachable / no repo.
    coverage: dict | None = None
    undocumented_dirs: list[str] = []
    repo = await db.repos.find_one({"teamId": team_id})
    if repo is not None:
        try:
            report = await coverage_report(db, repo, team_id)
            undocumented_dirs = [
                d["dir"] for d in report.get("byDir", []) if d["documented"] < d["total"]
            ][:15]
            coverage = {
                "fileCount": report.get("fileCount"),
                "documentedCount": report.get("documentedCount"),
                "undocumentedDirs": undocumented_dirs,
            }
        except RepoError:
            coverage = None

    await _audit(db, ctx, "projectdocs.plan", teamId=team_id)
    return {
        "teamId": team_id,
        "hasDocs": current is not None,
        "currentVersion": current.get("version") if current else 0,
        "recommendedSections": RECOMMENDED_SECTIONS,
        "existingSections": existing_sections,
        "repoConnected": repo is not None,
        "coverage": coverage,
        "instructions": _project_docs_instructions(current is not None, undocumented_dirs),
    }


@router.post("/teams/{team_id}/project-docs", status_code=status.HTTP_201_CREATED)
async def publish_project_docs(
    team_id: str, payload: ProjectDocsPublishIn, ctx: AgentCtx, db: Db
) -> dict:
    """Publish the project's developer documentation as a NEW version snapshot. Send the
    COMPLETE set of sections (Markdown) every time, this archives the prior version and makes
    this the current one, preserving the full history. Requires a memory:write key. This
    documentation is for humans and is never surfaced in agent retrieval."""
    require_scope(ctx, ApiScope.memory_write)
    await _agent_team(db, ctx, team_id)

    now = datetime.now(timezone.utc)
    last = await db.project_docs.find_one({"teamId": team_id}, sort=[("version", -1)])
    next_version = (last["version"] + 1) if last else 1
    sections = [
        {"slug": s.slug, "title": s.title.strip(), "order": s.order, "content": s.content}
        for s in payload.sections
    ]
    doc = {
        "_id": str(ObjectId()),
        "orgId": ctx.org_id,
        "teamId": team_id,
        "version": next_version,
        "status": "current",
        "summary": payload.summary.strip(),
        "sections": sections,
        "source": MemorySource.agent.value,
        "sourceRef": {"keyName": ctx.key.get("name")},
        "createdAt": now,
        "createdBy": None,
    }

    # Flip the prior current → archived and insert the new current atomically, so a reader
    # never sees zero or two "current" snapshots. run_atomic degrades to sequential on
    # standalone Mongo; the partial-unique (teamId, status="current") index is the backstop.
    async def work(session: object | None) -> None:
        await db.project_docs.update_many(
            {"teamId": team_id, "status": "current"},
            {"$set": {"status": "archived"}},
            session=session,
        )
        await db.project_docs.insert_one(doc, session=session)

    await run_atomic(db, work)
    await _audit(db, ctx, "projectdocs.publish", teamId=team_id, version=next_version)
    return project_doc_version_out(doc)


# --- Write-back (the compounding loop) ---


@router.post("/teams/{team_id}/memories", response_model=MemoryOut, status_code=status.HTTP_201_CREATED)
async def create_memory(team_id: str, payload: MemoryCreate, ctx: AgentCtx, db: Db) -> MemoryOut:
    require_scope(ctx, ApiScope.memory_write)
    team = await _agent_team(db, ctx, team_id)

    if payload.folderId is not None:
        folder = await db.folders.find_one({"_id": payload.folderId, "teamId": team_id})
        if folder is None:
            raise HTTPException(status_code=404, detail="Project not found")

    now = datetime.now(timezone.utc)
    title_norm = normalize_title(payload.title)
    tags = [normalize_tag(t) for t in payload.tags if normalize_tag(t)]
    # Review queue: when the team requires it, agent writes are held as `draft`
    # (excluded from every agent read path) until a human approves them in the UI.
    effective_status = (
        MemoryStatus.draft.value if team.get("agentWriteReview") else payload.status.value
    )

    title_filter = {"teamId": team_id, "titleNormalized": title_norm, "deletedAt": None}

    async def _apply_update(existing: dict) -> MemoryOut:
        """Writing an existing title UPDATES that doc rather than creating a duplicate,
        agent write-back is idempotent (re-running a seed/refresh won't pile up nodes)."""
        await snapshot_version(db, existing)  # keep the pre-upsert revision recoverable
        update = {
            "title": payload.title.strip(),
            "type": payload.type.value,
            "status": effective_status,
            "content": payload.content,
            "tags": tags,
            "source": MemorySource.agent.value,
            "sourceRef": {"keyName": ctx.key.get("name")},
            "lastVerifiedAt": now,
            "updatedBy": None,
            "updatedAt": now,
        }
        if payload.folderId is not None:
            update["folderId"] = payload.folderId
        await db.memories.update_one({"_id": existing["_id"]}, {"$set": update})
        await embed_and_store(db, existing["_id"], payload.title.strip(), payload.content, tags)
        await _audit(db, ctx, "memory.update", memoryId=existing["_id"], teamId=team_id)
        fresh = await db.memories.find_one({"_id": existing["_id"]})
        return memory_out(await refresh_memory_links(db, fresh))

    # Upsert by title: update if it already exists, else insert. Titles are the [[link]]
    # target so they must stay unique within a team, the (teamId, titleNormalized) unique
    # index enforces it, and catching DuplicateKeyError converts a lost insert race into
    # the update path instead of surfacing a 500 or creating a duplicate node.
    existing = await db.memories.find_one(title_filter)
    if existing is not None:
        return await _apply_update(existing)

    memory = {
        "_id": str(ObjectId()),
        "orgId": ctx.org_id,
        "teamId": team_id,
        "folderId": payload.folderId,
        "type": payload.type.value,
        "status": effective_status,
        "title": payload.title.strip(),
        "titleNormalized": title_norm,
        "content": payload.content,
        "tags": tags,
        "linkedMemoryIds": [],
        "unresolvedLinks": [],
        "source": MemorySource.agent.value,
        "sourceRef": {"keyName": ctx.key.get("name")},
        "helpfulCount": 0,
        "notHelpfulCount": 0,
        "lastVerifiedAt": now,
        "verifiedBy": None,
        "createdBy": None,
        "updatedBy": None,
        "createdAt": now,
        "updatedAt": now,
        "lastOpenedAt": None,
        "deletedAt": None,
    }
    try:
        await db.memories.insert_one(memory)
    except DuplicateKeyError:
        # A concurrent writer created this title between our find and insert, fold into
        # the update path so the two writes converge on one doc.
        conflict = await db.memories.find_one(title_filter)
        if conflict is not None:
            return await _apply_update(conflict)
        raise
    await embed_and_store(db, memory["_id"], memory["title"], memory["content"], memory["tags"])
    await _audit(db, ctx, "memory.create", memoryId=memory["_id"], teamId=team_id)
    return memory_out(await refresh_memory_links(db, memory))


@router.delete("/memories/{memory_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_memory(memory_id: str, ctx: AgentCtx, db: Db) -> None:
    """Soft-delete (trash) a memory, for removing duplicate or obsolete docs.
    Restorable from the UI trash. Requires a memory:write key."""
    require_scope(ctx, ApiScope.memory_write)
    memory = await _agent_memory(db, ctx, memory_id)  # enforces org + team scope
    now = datetime.now(timezone.utc)
    await db.memories.update_one(
        {"_id": memory_id}, {"$set": {"deletedAt": now, "updatedAt": now}}
    )
    await _audit(db, ctx, "memory.delete", memoryId=memory_id, teamId=memory["teamId"])
