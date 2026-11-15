"""Canonical agent-rule text + per-tool file mapping (single source of truth).

The "rule" is the always-on instruction that tells a coding agent WHEN to use the
Cognivio MCP tools (prime_context before a task, write_memory after). Connecting the
MCP server gives the agent the *tools*; this rule gives it the *habit*.

This used to live as copy-paste strings hard-coded in the frontend, which drifted,
notably the Cursor variant shipped without the `alwaysApply: true` frontmatter, so
Cursor treated it as a manual rule and did NOT load it every turn. The discipline then
decayed across a multi-task session (read once at the start, never again).

So the body lives here once, the `setup_rule` MCP tool / `GET /agent-rule` endpoint
hand the agent the EXACT file to write (correct path + correct content per editor), and
the agent writes it verbatim. No human transcription, no per-editor frontmatter mistakes.
Keep `frontend/src/workspace/cognivioRule.ts` textually in sync with this module (the
language boundary forces two copies; there is a cross-reference comment in both).
"""

from __future__ import annotations

# The editor-agnostic instruction body. Editors that key rules off frontmatter (Cursor)
# get this wrapped; editors that load a plain Markdown file (Claude Code, Codex) get it
# under a heading. The body itself is identical so behavior matches across tools.
RULE_BODY = """\
Use the "cognivio" MCP server as the source of truth for this project. Apply this on
EVERY task in a session, not just the first.

Before any non-trivial task (anything beyond a one-line, localized edit):
1. Call prime_context("<the task>") FIRST, it returns the index plus the most relevant
   docs in one shot, so you can skip blind exploration.
2. If prime_context returns a "setup" field (no Project Map yet = not initialized), STOP
   and ask the user "Want me to initialize Cognivio for this repo?". If yes, call
   seed_plan(team_id) (find team_id with list_teams) and follow the ordered steps it
   returns. If no, just proceed.
3. Otherwise read the returned docs (and the file/class pointers inside) before writing
   code. Prefer documented decisions over guessing.

After resolving something non-obvious, capture it with write_memory (lesson / incident /
decision), writing an existing title updates it in place (no duplicates). Link related
docs in the body with [[Exact Title]]. Periodically run check_drift and refresh any docs
whose cited files have changed."""

# Per-tool target file (relative to repo root). Cursor's rules live under .cursor/rules/
# and MUST carry `alwaysApply: true` frontmatter to be injected every turn.
_TOOL_FILES = {
    "claude": "CLAUDE.md",
    "cursor": ".cursor/rules/cognivio.mdc",
    "codex": "AGENTS.md",
}

SUPPORTED_TOOLS = tuple(_TOOL_FILES)

_CURSOR_FRONTMATTER = (
    "---\n"
    "description: Use the Cognivio knowledge base (read before a task, write after)\n"
    "alwaysApply: true\n"
    "---\n\n"
)

_MARKDOWN_HEADING = "## Team knowledge base (Cognivio)\n\n"


def rule_content(tool: str) -> str:
    """The exact file body to write for `tool`. Cursor gets the always-applied
    frontmatter; Claude Code / Codex get the body under a Markdown heading so it reads
    naturally appended to an existing CLAUDE.md / AGENTS.md."""
    if tool == "cursor":
        return _CURSOR_FRONTMATTER + RULE_BODY + "\n"
    return _MARKDOWN_HEADING + RULE_BODY + "\n"


def rule_file_for(tool: str) -> dict:
    """`{tool, path, content, append}`, everything the agent needs to install the rule.

    `append` is True for CLAUDE.md / AGENTS.md (shared files the user may already have,
    add the section rather than overwrite) and False for the dedicated Cursor .mdc file
    (Cognivio owns it; write it whole)."""
    if tool not in _TOOL_FILES:
        raise ValueError(f"unknown tool {tool!r}; expected one of {', '.join(SUPPORTED_TOOLS)}")
    return {
        "tool": tool,
        "path": _TOOL_FILES[tool],
        "content": rule_content(tool),
        "append": tool != "cursor",
    }
