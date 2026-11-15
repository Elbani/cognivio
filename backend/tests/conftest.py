from __future__ import annotations

import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from motor.motor_asyncio import AsyncIOMotorClient

os.environ.setdefault("TESTING", "1")
os.environ.setdefault("MONGO_URI", "mongodb://localhost:27017")
os.environ.setdefault("MONGO_DB", "markdown_notes_test")
os.environ.setdefault("JWT_SECRET", "test-secret-not-for-production-use-only-for-testing-1234")
os.environ.setdefault("FRONTEND_DIST", "/tmp/nonexistent")
# Force transactional email OFF for the whole suite, so no test ever sends a real
# email, even via the unmocked register/forgot-password paths. Override (not
# setdefault) so a RESEND_API_KEY in a local .env can't leak real sends into tests.
os.environ["RESEND_API_KEY"] = ""

from app.main import app  # noqa: E402
from app.core.config import settings  # noqa: E402
from app.db import database as db_mod  # noqa: E402

# Belt-and-suspenders: a .env loaded at import time may already have populated the
# settings singleton, so blank it here too. send_email() no-ops when this is empty.
settings.resend_api_key = ""

_client: AsyncIOMotorClient | None = None
_db = None


@pytest.fixture(scope="session")
def event_loop_policy():
    import asyncio
    return asyncio.DefaultEventLoopPolicy()


@pytest_asyncio.fixture(scope="session", loop_scope="session")
async def mongo_db():
    global _client, _db
    _client = AsyncIOMotorClient(os.environ["MONGO_URI"])
    _db = _client[os.environ["MONGO_DB"]]
    db_mod.client = _client
    await db_mod.create_indexes(_db)
    yield _db
    await _client.drop_database(os.environ["MONGO_DB"])
    _client.close()
    db_mod.client = None


@pytest_asyncio.fixture(autouse=True, loop_scope="session")
async def clean_collections(mongo_db):
    yield
    for name in await mongo_db.list_collection_names():
        await mongo_db[name].delete_many({})


@pytest.fixture
def email_on(monkeypatch):
    """Pretend an email provider is configured, so registration requires verification."""
    monkeypatch.setattr(type(settings), "email_enabled", property(lambda self: True))


@pytest_asyncio.fixture(loop_scope="session")
async def client(mongo_db):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest_asyncio.fixture(loop_scope="session")
async def auth_headers(client: AsyncClient, mongo_db) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/register",
        json={"email": "test@example.com", "password": "password123", "name": "Test User"},
    )
    assert resp.status_code == 201, resp.text
    # New accounts start unverified and the platform gates them, mark this fixture's
    # user verified so the data-access tests it backs aren't blocked.
    await mongo_db.users.update_one(
        {"email": "test@example.com"}, {"$set": {"emailVerified": True}}
    )
    token = resp.json()["accessToken"]
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture(loop_scope="session")
async def workspace(client: AsyncClient, auth_headers: dict[str, str]) -> dict[str, str]:
    """The default org + 'Main' team auto-created for the registered user."""
    orgs = (await client.get("/api/orgs", headers=auth_headers)).json()
    org_id = orgs[0]["id"]
    teams = (await client.get(f"/api/orgs/{org_id}/teams", headers=auth_headers)).json()
    return {"org_id": org_id, "team_id": teams[0]["id"]}


@pytest_asyncio.fixture(loop_scope="session")
async def enterprise_workspace(workspace, mongo_db) -> dict[str, str]:
    """Same workspace, upgraded to the Enterprise plan, for tests that exercise
    multi-project / multi-team mechanics the Free plan deliberately gates (402)."""
    await mongo_db.organizations.update_one(
        {"_id": workspace["org_id"]}, {"$set": {"plan": "enterprise"}}
    )
    return workspace
