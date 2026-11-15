from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import Db, TeamCtx
from app.api.memories import memory_out
from app.models.enums import MemoryType
from app.models.schemas import MapEdge, MapNode, MapResponse, document_id
from app.templates import MEMORY_TEMPLATES

router = APIRouter(prefix="/api", tags=["map"])


@router.get("/memory-templates", response_model=dict[str, str])
async def memory_templates() -> dict[str, str]:
    return MEMORY_TEMPLATES


@router.get("/teams/{team_id}/map", response_model=MapResponse)
async def get_map(ctx: TeamCtx, db: Db) -> MapResponse:
    """The agent entry point: the team's map memory plus the full link graph
    of active memories. Read this first to skip the archaeology."""
    map_doc = await db.memories.find_one(
        {"teamId": ctx.team_id, "type": MemoryType.map.value, "deletedAt": None},
        sort=[("updatedAt", -1)],
    )

    nodes: list[MapNode] = []
    node_ids: set[str] = set()
    edges: list[MapEdge] = []
    links: list[tuple[str, list[str]]] = []

    cursor = db.memories.find(
        {"teamId": ctx.team_id, "deletedAt": None},
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

    for source, targets in links:
        for target in targets:
            if target in node_ids:
                edges.append(MapEdge(source=source, target=target))

    return MapResponse(
        teamId=ctx.team_id,
        mapMemory=memory_out(map_doc) if map_doc else None,
        nodes=nodes,
        edges=edges,
    )
