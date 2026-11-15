# Cognivio connector (MCP server)

A small Python program that exposes your Cognivio knowledge base to coding
agents (Claude Code, Cursor, Codex) over the Model Context Protocol. It's a thin
client over the platform's `/api/v1` REST API, it stores nothing itself.

> **Prefer zero setup?** The platform also hosts a **remote** MCP server at `/mcp`
> (Streamable HTTP), point your tool at `https://<host>/mcp` with an `ak_` key in the
> `Authorization` header and skip this local install entirely. See **Agents → Connect a
> tool → Remote**. This local (stdio) connector is the fallback. Its `check_drift` reads your
> local working tree, while the remote one uses the server-side repo connection.

## 1. Install a runner (once)

The connector is a small Python program (3.10+), **you don't need this repo**; the platform
serves it. There are two ways to run it. **uv is recommended** because there's no separate
connector install to forget (the #1 setup mistake).

**Recommended, [uv](https://docs.astral.sh/uv/) (zero-install):** install uv once, and the
config in step 3 fetches & runs the connector on demand with `uvx`. Nothing else to install.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh   # macOS/Linux; Windows: see uv docs
```

**Alternative, [pipx](https://pipx.pypa.io):** install the connector itself from your server
URL (the exact URL is shown in-app under **Agents → Connect a tool**):

```bash
pipx install http://localhost:8080/connector/cognivio_mcp-0.1.0-py3-none-any.whl
```

This puts the `cognivio-mcp` command on your PATH.

> Building from a checkout instead? `pipx install "/ABS/PATH/TO/cognivio/mcp_server"` also works.

## 2. Get the two settings

| Setting | Value |
|---|---|
| `KB_BASE_URL` | the platform URL, `http://localhost:8080` for local Docker, or your deployed URL. **No trailing `/api/v1`.** |
| `KB_API_KEY` | an `ak_…` key from **Agents → Connect a tool** (or **Agents → API keys**). |

## 3. Point your tool at it

With **uv** (recommended), `uvx` fetches & runs the connector, replace `<WHEEL_URL>` with the
link from **Agents → Connect a tool** (e.g. `http://localhost:8080/connector/cognivio_mcp-0.1.0-py3-none-any.whl`):

```jsonc
// .mcp.json (Claude Code) / .cursor/mcp.json (Cursor)
{
  "mcpServers": {
    "cognivio": {
      "command": "uvx",
      "args": ["--from", "<WHEEL_URL>", "cognivio-mcp"],
      "env": {
        "KB_BASE_URL": "http://localhost:8080",
        "KB_API_KEY": "ak_…"
      }
    }
  }
}
```

Codex (`~/.codex/config.toml`):

```toml
[mcp_servers.cognivio]
command = "uvx"
args = ["--from", "<WHEEL_URL>", "cognivio-mcp"]
env = { KB_BASE_URL = "http://localhost:8080", KB_API_KEY = "ak_…" }
```

> **Installed with pipx instead?** Drop the `uvx --from <WHEEL_URL>` wrapper and use
> `"command": "cognivio-mcp"` with no `args`. (Or run from a venv: `python3 -m venv
> ~/.cognivio && ~/.cognivio/bin/pip install "/ABS/PATH/TO/cognivio/mcp_server"`,
> then `command: "~/.cognivio/bin/cognivio-mcp"`.)

## 4. Tell the agent to use it

Add a standing rule (`CLAUDE.md`, `.cursor/rules/…`, or `AGENTS.md`) so the agent
consults the KB first:

```
Before any non-trivial task, call prime_context("<the task>") first, it returns the
index plus the most relevant docs in one call. Read those (and follow the file/class
pointers and [[links]] inside) before exploring the code. After resolving something
non-obvious, capture it with write_memory.
```

## Tools exposed

- **Start here:** `prime_context` (index + most relevant docs in one call).
- **Read:** `whoami`, `list_teams`, `read_map`, `search_memory`, `get_memory`, `get_related`.
- **Write back:** `write_memory` (same title updates in place), `delete_memory`, `mark_helpful`
  (rate whether a doc helped, feeds retrieval ranking).
- **Maintain:** `knowledge_gaps`, `seed_plan` (one-shot plan to initialize/fill a KB from the repo),
  `setup_rule` (returns the always-on rule file for your editor),
  `check_drift` (this connector's version diffs your **local working tree**).
- **Project docs:** `plan_project_docs` + `write_project_docs`, generate a human-facing developer
  handbook, stored as versioned snapshots. Separate from the KB and never used in agent retrieval.

The remote `/mcp` endpoint exposes the same set. Its `check_drift` is backed by the server-side
repo connection (a read-only Git token) instead of your local filesystem.

## Troubleshooting
- **"Failed to connect" right after installing uv** → your shell hasn't picked up uv's PATH yet.
  The installer adds `uvx` to `~/.local/bin` but the *current* terminal still has the old PATH,
  so the tool you launched from it can't find `uvx`. Fix: restart the terminal (or
  `source $HOME/.local/bin/env`), confirm `which uvx` prints a path, then relaunch your tool.
- **"Failed to connect" / server won't start** → the *runner* isn't installed at all. Run
  `which uvx` (or `which cognivio-mcp` if you chose pipx); if missing, install uv/pipx, then
  restart your coding tool. Note `claude mcp add` only records the launch command, it installs
  and verifies nothing, so it "succeeds" even when the runner is absent.
- **download fails / `uvx --from <url>` can't fetch** → the platform build doesn't include the
  connector artifact, or the URL/host is wrong. The current link is in **Agents → Connect a tool**.
- **401 / "Invalid API key"** → bad/expired `KB_API_KEY`, or `KB_BASE_URL` points at the
  wrong host.
- **Tools return nothing useful** → the KB doesn't cover that area yet. Check
  **Agents → Activity** and the `knowledge_gaps` tool to see what to document.
