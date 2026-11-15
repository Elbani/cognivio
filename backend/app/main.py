import asyncio
import contextlib
import logging
import time
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from fastapi.staticfiles import StaticFiles

from app.api import activity, admin, agent, apikeys, appearance, auth, folders, insights, maps, memories, orgs, project_docs, repos
from app.core.config import settings
from app.core.embeddings import warm as warm_embeddings
from app.db.database import get_db, lifespan as db_lifespan
from app.mcp_remote import mcp_lifespan, mcp_route

logger = logging.getLogger("app")


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Compose the DB lifespan (Mongo client + indexes) with the remote MCP
    # session manager (Streamable HTTP at /mcp) so both start and stop together.
    async with db_lifespan(app), mcp_lifespan():
        # Load the embedding model in the background so the first request doesn't pay the
        # (slow) model init/download. No-op when embeddings are disabled/unavailable.
        warm_task = asyncio.create_task(asyncio.to_thread(warm_embeddings))
        try:
            yield
        finally:
            warm_task.cancel()


_docs_kwargs: dict = {}
if settings.disable_docs:
    _docs_kwargs = {"docs_url": None, "redoc_url": None, "openapi_url": None}

app = FastAPI(title="Cognivio", lifespan=lifespan, **_docs_kwargs)

limiter = Limiter(key_func=get_remote_address, default_limits=[])
app.state.limiter = limiter
# Without this, a tripped @limiter.limit (e.g. on login/signup in auth.py) raises
# RateLimitExceeded and FastAPI renders it as a 500 instead of a proper 429.
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# The agent REST surface (/api/v1/*) and the remote MCP endpoint (/mcp) carry no
# per-route limits and authenticate on every call (a DB read + a lastUsedAt write, plus
# a security-event write for each *invalid* key), so an unauthenticated flood is a
# self-amplifying write-DoS. A lightweight per-IP token window caps that. In-process and
# per-worker (same model as the auth limiter); fine as an abuse ceiling, not a quota.
_AGENT_RL_PATHS = ("/api/v1", "/mcp")
_AGENT_RL_WINDOW = 60.0
_AGENT_RL_MAX = 180  # requests / IP / minute across the whole agent+MCP surface
_agent_hits: dict[str, deque[float]] = defaultdict(deque)


@app.middleware("http")
async def agent_surface_rate_limit(request: Request, call_next):  # type: ignore[type-arg]
    path = request.url.path
    if path.startswith(_AGENT_RL_PATHS):
        ip = get_remote_address(request)
        now = time.monotonic()
        hits = _agent_hits[ip]
        while hits and now - hits[0] > _AGENT_RL_WINDOW:
            hits.popleft()
        if len(hits) >= _AGENT_RL_MAX:
            return JSONResponse({"detail": "Rate limit exceeded. Slow down."}, status_code=429)
        hits.append(now)
        if len(_agent_hits) > 10000:  # opportunistic cleanup of drained IP buckets
            for k in [k for k, v in _agent_hits.items() if not v]:
                del _agent_hits[k]
    return await call_next(request)


origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next) -> Response:  # type: ignore[type-arg]
    response: Response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: https:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'"
    )
    return response


app.include_router(auth.router)
app.include_router(orgs.router)
app.include_router(folders.router)
app.include_router(memories.router)
app.include_router(maps.router)
app.include_router(apikeys.router)
app.include_router(agent.router)
app.include_router(activity.router)
app.include_router(insights.router)
app.include_router(repos.router)
app.include_router(project_docs.router)
app.include_router(admin.router)
app.include_router(appearance.router)

# Remote MCP endpoint (Streamable HTTP) at /mcp, the zero-local-setup connector.
# Registered before the SPA catch-all so it isn't shadowed by index.html.
app.router.routes.append(mcp_route())


@app.get("/api/health")
async def health() -> Response:
    """Readiness check: pings MongoDB so the platform's health probe pulls an instance
    that can't reach its DB out of rotation instead of serving failing requests."""
    try:
        await get_db().command("ping")
    except Exception as exc:  # noqa: BLE001 - any DB error means not-ready
        logger.warning("Health check failed: DB unreachable (%s)", exc)
        return JSONResponse({"status": "unavailable", "db": False}, status_code=503)
    return JSONResponse({"status": "ok", "db": True})


# --- MCP connector download ---
# Users get only the platform URL + an API key (no repo, no PyPI), so the server
# hands them the connector: the built wheel is served at /connector and this endpoint
# tells the UI its exact filename to build a copy-paste `pipx install <url>` command.
connector_dir = Path(settings.connector_dir)
if connector_dir.exists():
    app.mount("/connector", StaticFiles(directory=connector_dir), name="connector")


@app.get("/api/connector")
async def connector_info() -> dict:
    wheels = sorted(connector_dir.glob("*.whl")) if connector_dir.exists() else []
    if not wheels:
        return {"available": False}
    name = wheels[-1].name
    return {"available": True, "filename": name, "path": f"/connector/{name}"}


frontend_dist = Path(settings.frontend_dist)
if frontend_dist.exists():
    app.mount(
        "/assets",
        StaticFiles(directory=frontend_dist / "assets"),
        name="frontend-assets",
    )

    # Root-level static files (Vite copies public/ here). Must be declared before the
    # SPA catch-all below, which otherwise returns index.html for every path.
    @app.get("/favicon.svg")
    async def favicon() -> FileResponse:
        return FileResponse(frontend_dist / "favicon.svg")

    @app.get("/{full_path:path}")
    async def frontend_app(full_path: str) -> FileResponse:
        return FileResponse(frontend_dist / "index.html")

else:

    @app.get("/")
    async def missing_frontend() -> JSONResponse:
        return JSONResponse(
            {
                "message": "Frontend build not found. Run the React dev server or build assets."
            }
        )
