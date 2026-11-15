"""Read-only Git host clients (GitHub / GitLab, PAT-auth) + pure coverage logic.

Used by the team repo connection (app/api/repos.py) to: validate a connection, list the
repo's files, find the last-commit date of referenced files (for server-side drift), and
build per-directory coverage from the file paths cited in a team's docs.

The pure functions (`referenced_files`, `compute_coverage`) have no network and are unit
tested; the async client functions hit the provider REST APIs and need a real token.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import datetime, timezone
from urllib.parse import quote

import httpx

# A path-like token: has a dotted extension; we only keep ones that match a real repo file.
_PATH_RE = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.\-/]*\.[A-Za-z0-9]{1,8}")


def referenced_files(doc_contents: Iterable[str], repo_files: set[str]) -> set[str]:
    """File paths cited in docs that actually exist in the repo (exact match, encourages
    citing real, full paths)."""
    refs: set[str] = set()
    for content in doc_contents:
        for tok in _PATH_RE.findall(content or ""):
            if "://" in tok:
                continue
            candidate = tok.lstrip("./")
            if candidate in repo_files:
                refs.add(candidate)
    return refs


def compute_coverage(repo_files: list[str], referenced: set[str], sample: int = 25) -> dict:
    """Per-directory documented-vs-total from the repo's files and the cited subset.
    Directories are ranked least-covered first so the gaps surface at the top."""
    files = list(dict.fromkeys(repo_files))
    by_dir: dict[str, dict] = {}
    for f in files:
        d = f.split("/")[0] if "/" in f else "(root)"
        b = by_dir.setdefault(d, {"dir": d, "total": 0, "documented": 0})
        b["total"] += 1
        if f in referenced:
            b["documented"] += 1
    dirs = sorted(by_dir.values(), key=lambda x: (x["documented"] / x["total"], -x["total"]))
    undocumented = [f for f in files if f not in referenced]
    return {
        "fileCount": len(files),
        "documentedCount": len(referenced & set(files)),
        "byDir": dirs,
        "undocumentedSample": undocumented[:sample],
    }


# --- Provider REST clients (read-only) ---


class RepoError(Exception):
    """A connection/auth/fetch problem worth surfacing to the user."""


def _api_base(cfg: dict) -> str:
    base = (cfg.get("baseUrl") or "").rstrip("/")
    if cfg["provider"] == "github":
        return base or "https://api.github.com"
    return (base or "https://gitlab.com") + "/api/v4"


def _headers(cfg: dict) -> dict:
    if cfg["provider"] == "github":
        return {"Authorization": f"Bearer {cfg['token']}", "Accept": "application/vnd.github+json"}
    return {"PRIVATE-TOKEN": cfg["token"]}


def web_file_url(cfg: dict, path: str) -> str:
    branch = cfg.get("defaultBranch") or "main"
    if cfg["provider"] == "github":
        return f"https://github.com/{cfg['projectPath']}/blob/{branch}/{path}"
    base = (cfg.get("baseUrl") or "https://gitlab.com").rstrip("/")
    return f"{base}/{cfg['projectPath']}/-/blob/{branch}/{path}"


def _gl_project(cfg: dict) -> str:
    return quote(cfg["projectPath"], safe="")


async def verify_and_default_branch(cfg: dict) -> str:
    """Validate token + repo access; return the repo's default branch. Raises RepoError."""
    async with httpx.AsyncClient(timeout=20.0, headers=_headers(cfg)) as c:
        try:
            if cfg["provider"] == "github":
                r = await c.get(f"{_api_base(cfg)}/repos/{cfg['projectPath']}")
            else:
                r = await c.get(f"{_api_base(cfg)}/projects/{_gl_project(cfg)}")
        except httpx.HTTPError as e:  # network/DNS/timeouts
            raise RepoError(f"Could not reach the Git host: {e}") from e
        if r.status_code in (401, 403):
            if cfg["provider"] == "gitlab":
                raise RepoError(
                    "Access denied. A GitLab token needs the read_api scope, read_repository "
                    "only grants Git/clone access, not the REST API the scanner uses."
                )
            raise RepoError("Access denied, check the token has read access to this repo.")
        if r.status_code == 404:
            raise RepoError("Repository not found, check the path (e.g. 'owner/repo').")
        if r.status_code >= 400:
            raise RepoError(f"Git host error {r.status_code}.")
        return r.json().get("default_branch") or "main"


async def list_tree(cfg: dict, max_files: int = 5000) -> dict[str, int]:
    """All blob paths on the default branch → size in bytes. GitHub's recursive tree
    already carries per-blob sizes (free); GitLab's tree API doesn't, so its sizes are 0
    (= unknown), `blob_sizes` fills those in for the few files that matter."""
    branch = cfg.get("defaultBranch") or "main"
    async with httpx.AsyncClient(timeout=30.0, headers=_headers(cfg)) as c:
        if cfg["provider"] == "github":
            r = await c.get(
                f"{_api_base(cfg)}/repos/{cfg['projectPath']}/git/trees/{branch}",
                params={"recursive": "1"},
            )
            if r.status_code >= 400:
                raise RepoError(f"Could not list files (HTTP {r.status_code}).")
            data = r.json()
            blobs = [t for t in data.get("tree", []) if t.get("type") == "blob"][:max_files]
            return {t["path"]: int(t.get("size") or 0) for t in blobs}
        # GitLab: paginate the recursive tree (no sizes here)
        tree: dict[str, int] = {}
        page = 1
        while len(tree) < max_files:
            r = await c.get(
                f"{_api_base(cfg)}/projects/{_gl_project(cfg)}/repository/tree",
                params={"recursive": "true", "per_page": 100, "page": page, "ref": branch},
            )
            if r.status_code >= 400:
                raise RepoError(f"Could not list files (HTTP {r.status_code}).")
            batch = r.json()
            if not batch:
                break
            for e in batch:
                if e.get("type") == "blob" and len(tree) < max_files:
                    tree[e["path"]] = 0
            if r.headers.get("X-Next-Page"):
                page = int(r.headers["X-Next-Page"])
            else:
                break
        return tree


async def list_files(cfg: dict, max_files: int = 5000) -> list[str]:
    """All blob paths on the default branch."""
    return list(await list_tree(cfg, max_files))


async def blob_sizes(cfg: dict, paths: list[str], cap: int = 60) -> dict[str, int]:
    """Byte size per path for providers whose tree listing lacks sizes (GitLab).
    Capped like `last_commit_dates`, callers only need the cited-file subset."""
    branch = cfg.get("defaultBranch") or "main"
    out: dict[str, int] = {}
    async with httpx.AsyncClient(timeout=30.0, headers=_headers(cfg)) as c:
        for path in paths[:cap]:
            try:
                r = await c.get(
                    f"{_api_base(cfg)}/projects/{_gl_project(cfg)}/repository/files/{quote(path, safe='')}",
                    params={"ref": branch},
                )
            except httpx.HTTPError:
                continue
            if r.status_code >= 400:
                continue
            size = r.json().get("size")
            if isinstance(size, int) and size > 0:
                out[path] = size
    return out


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def last_commit_dates(cfg: dict, paths: list[str], cap: int = 60) -> dict[str, datetime]:
    """Last-commit timestamp per path (capped), for comparing against doc lastVerifiedAt."""
    branch = cfg.get("defaultBranch") or "main"
    out: dict[str, datetime] = {}
    async with httpx.AsyncClient(timeout=30.0, headers=_headers(cfg)) as c:
        for path in paths[:cap]:
            try:
                if cfg["provider"] == "github":
                    r = await c.get(
                        f"{_api_base(cfg)}/repos/{cfg['projectPath']}/commits",
                        params={"path": path, "per_page": 1},
                    )
                    if r.status_code >= 400 or not r.json():
                        continue
                    dt = _parse_iso(r.json()[0]["commit"]["committer"]["date"])
                else:
                    r = await c.get(
                        f"{_api_base(cfg)}/projects/{_gl_project(cfg)}/repository/commits",
                        params={"path": path, "per_page": 1, "ref_name": branch},
                    )
                    if r.status_code >= 400 or not r.json():
                        continue
                    dt = _parse_iso(r.json()[0].get("committed_date"))
            except httpx.HTTPError:
                continue
            if dt:
                out[path] = dt
    return out
