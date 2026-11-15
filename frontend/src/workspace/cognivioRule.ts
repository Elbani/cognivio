// Canonical agent-rule text + per-tool file mapping for the UI (single source of truth
// on the frontend). Keep textually in sync with backend/app/core/agent_rules.py, the
// language boundary forces two copies. The agent-driven path (the `setup_rule` MCP tool)
// uses the BACKEND copy; this copy is only for the manual fallback shown in the UI, so
// they must agree. Notably Cursor needs the `alwaysApply: true` frontmatter or the rule
// is not loaded every turn (the bug this whole flow exists to prevent).

export type Tool = "claude" | "cursor" | "codex";

export const RULE_BODY = `Use the "cognivio" MCP server as the source of truth for this project. Apply this on
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
whose cited files have changed.`;

const TOOL_FILES: Record<Tool, string> = {
  claude: "CLAUDE.md",
  cursor: ".cursor/rules/cognivio.mdc",
  codex: "AGENTS.md",
};

const CURSOR_FRONTMATTER =
  "---\n" +
  "description: Use the Cognivio knowledge base (read before a task, write after)\n" +
  "alwaysApply: true\n" +
  "---\n\n";

const MARKDOWN_HEADING = "## Team knowledge base (Cognivio)\n\n";

// The exact file body to write for a tool. Cursor gets always-applied frontmatter;
// Claude Code / Codex get the body under a heading so it appends cleanly.
export function ruleContent(tool: Tool): string {
  return (tool === "cursor" ? CURSOR_FRONTMATTER : MARKDOWN_HEADING) + RULE_BODY + "\n";
}

export function ruleFileFor(tool: Tool): { path: string; content: string; append: boolean } {
  return { path: TOOL_FILES[tool], content: ruleContent(tool), append: tool !== "cursor" };
}
