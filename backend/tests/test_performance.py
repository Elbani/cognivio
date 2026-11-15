from __future__ import annotations

import asyncio
import time

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio

NOTE_COUNT = 200
LINKED_RATIO = 0.3


def _mem_url(ws: dict) -> str:
    return f"/api/teams/{ws['team_id']}/memories"


async def seed_memories(client: AsyncClient, headers: dict, ws: dict, count: int) -> list[str]:
    ids: list[str] = []
    for i in range(count):
        resp = await client.post(
            _mem_url(ws),
            json={"title": f"Note {i}", "content": f"Content of note {i}", "tags": [f"tag{i % 10}"]},
            headers=headers,
        )
        assert resp.status_code == 201
        ids.append(resp.json()["id"])
    return ids


async def add_wiki_links(
    client: AsyncClient, headers: dict, ids: list[str], ratio: float
) -> None:
    linked_count = max(1, int(len(ids) * ratio))
    for i in range(linked_count):
        target_idx = (i + 1) % len(ids)
        await client.patch(
            f"/api/memories/{ids[i]}",
            json={"content": f"Links to [[Note {target_idx}]] and more text about note {i}"},
            headers=headers,
        )


async def test_list_performance(client: AsyncClient, auth_headers, workspace) -> None:
    await seed_memories(client, auth_headers, workspace, NOTE_COUNT)

    times = []
    for _ in range(5):
        start = time.perf_counter()
        resp = await client.get(_mem_url(workspace), headers=auth_headers)
        times.append(time.perf_counter() - start)
        assert resp.status_code == 200

    for m in resp.json()["memories"]:
        assert "content" not in m

    avg_ms = (sum(times) / len(times)) * 1000
    p95_ms = sorted(times)[int(len(times) * 0.95)] * 1000
    assert avg_ms < 500, f"Average list latency too high: {avg_ms:.1f}ms"
    assert p95_ms < 800, f"P95 list latency too high: {p95_ms:.1f}ms"


async def test_get_performance(client: AsyncClient, auth_headers, workspace) -> None:
    ids = await seed_memories(client, auth_headers, workspace, 50)

    times = []
    for mid in ids[:20]:
        start = time.perf_counter()
        resp = await client.get(f"/api/memories/{mid}", headers=auth_headers)
        times.append(time.perf_counter() - start)
        assert resp.status_code == 200
        assert "content" in resp.json()

    avg_ms = (sum(times) / len(times)) * 1000
    assert avg_ms < 100, f"Average get latency too high: {avg_ms:.1f}ms"


async def test_update_no_content_change(client: AsyncClient, auth_headers, workspace) -> None:
    ids = await seed_memories(client, auth_headers, workspace, 20)
    await add_wiki_links(client, auth_headers, ids, 0.5)

    times = []
    for mid in ids[:10]:
        start = time.perf_counter()
        resp = await client.patch(
            f"/api/memories/{mid}", json={"tags": ["updated"]}, headers=auth_headers
        )
        times.append(time.perf_counter() - start)
        assert resp.status_code == 200

    avg_ms = (sum(times) / len(times)) * 1000
    assert avg_ms < 100, f"Average tags-only update too slow: {avg_ms:.1f}ms"


async def test_update_with_content_change(client: AsyncClient, auth_headers, workspace) -> None:
    ids = await seed_memories(client, auth_headers, workspace, 30)

    times = []
    for i, mid in enumerate(ids[:15]):
        target = f"Note {(i + 5) % 30}"
        start = time.perf_counter()
        resp = await client.patch(
            f"/api/memories/{mid}", json={"content": f"Now links to [[{target}]]"}, headers=auth_headers
        )
        times.append(time.perf_counter() - start)
        assert resp.status_code == 200

    avg_ms = (sum(times) / len(times)) * 1000
    assert avg_ms < 200, f"Average content update too slow: {avg_ms:.1f}ms"


async def test_trash_list_performance(client: AsyncClient, auth_headers, workspace) -> None:
    ids = await seed_memories(client, auth_headers, workspace, 50)
    for mid in ids[:25]:
        await client.delete(f"/api/memories/{mid}", headers=auth_headers)

    times = []
    for _ in range(5):
        start = time.perf_counter()
        resp = await client.get(f"{_mem_url(workspace)}/trash", headers=auth_headers)
        times.append(time.perf_counter() - start)
        assert resp.status_code == 200

    avg_ms = (sum(times) / len(times)) * 1000
    assert avg_ms < 300, f"Average trash list latency too high: {avg_ms:.1f}ms"


async def test_search_performance(client: AsyncClient, auth_headers, workspace) -> None:
    await seed_memories(client, auth_headers, workspace, NOTE_COUNT)

    times = []
    for q in ["Note 10", "Content", "tag5"]:
        start = time.perf_counter()
        resp = await client.get(f"{_mem_url(workspace)}?q={q}", headers=auth_headers)
        times.append(time.perf_counter() - start)
        assert resp.status_code == 200

    avg_ms = (sum(times) / len(times)) * 1000
    assert avg_ms < 500, f"Average search latency too high: {avg_ms:.1f}ms"


async def test_concurrent_creation(client: AsyncClient, auth_headers, workspace) -> None:
    async def create_one(idx: int):
        resp = await client.post(
            _mem_url(workspace),
            json={"title": f"Concurrent {idx}", "content": f"Body {idx}"},
            headers=auth_headers,
        )
        return resp.status_code

    statuses = await asyncio.gather(*[create_one(i) for i in range(20)])
    assert all(s == 201 for s in statuses), f"Some creations failed: {statuses}"


async def test_wiki_link_resolution_at_scale(client: AsyncClient, auth_headers, workspace) -> None:
    count = 50
    await seed_memories(client, auth_headers, workspace, count)

    content = " ".join(f"[[Note {i}]]" for i in range(count))
    resp = await client.post(
        _mem_url(workspace), json={"title": "Hub note", "content": content}, headers=auth_headers
    )
    assert resp.status_code == 201
    data = resp.json()
    assert len(data["linkedMemoryIds"]) == count
    assert data["unresolvedLinks"] == []
