import { useEffect, useState } from "react";
import { apiRequest, ApiKeyCreated } from "../lib/api";
import { ruleFileFor, type Tool } from "./cognivioRule";

type ConnectorInfo = { available: boolean; filename?: string; path?: string };

const BASE = typeof window !== "undefined" ? window.location.origin : "https://your-host";

// Cross-platform uv installer (macOS/Linux). Windows: see https://docs.astral.sh/uv/
const UV_INSTALL = "curl -LsSf https://astral.sh/uv/install.sh | sh";

const TOOLS: { id: Tool; name: string }[] = [
  { id: "claude", name: "Claude Code" },
  { id: "cursor", name: "Cursor" },
  { id: "codex", name: "Codex" }
];

function Copy({ text }: { text: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      className="ws-btn sm"
      onClick={() => { navigator.clipboard?.writeText(text); setDone(true); setTimeout(() => setDone(false), 1200); }}
    >
      {done ? "Copied ✓" : "Copy"}
    </button>
  );
}

export function ConnectDialog({ token, orgId, teamId, canManage, onClose }: {
  token: string;
  orgId: string;
  teamId: string | null;
  canManage: boolean;
  onClose: () => void;
}) {
  const [tool, setTool] = useState<Tool | null>(null);
  const [transport, setTransport] = useState<"remote" | "local">("remote");
  const [created, setCreated] = useState<ApiKeyCreated | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [connector, setConnector] = useState<ConnectorInfo | null>(null);

  useEffect(() => {
    apiRequest<ConnectorInfo>("/api/connector").then(setConnector).catch(() => setConnector({ available: false }));
  }, []);

  async function choose(t: Tool) {
    setTool(t);
    setError("");
    if (created) return; // one key works for any tool
    setBusy(true);
    try {
      const k = await apiRequest<ApiKeyCreated>(`/api/orgs/${orgId}/keys`, {
        method: "POST", token,
        body: { name: "coding-agent", scopes: ["memory:read", "map:read", "memory:write"] }
      });
      setCreated(k);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not create a key");
    } finally {
      setBusy(false);
    }
  }

  if (!canManage) {
    return (
      <div className="ac-overlay" onClick={onClose}>
        <div className="ac-modal" style={{ maxWidth: 460 }} onClick={(e) => e.stopPropagation()}>
          <div className="ac-modal-head"><h2>Connect a coding tool</h2></div>
          <div className="ac-modal-body"><p>Only org owners and admins can create API keys. Ask an admin to connect a tool, or to share a key with you.</p></div>
          <div className="ac-modal-foot"><span className="spacer" /><button className="ws-btn" onClick={onClose}>Close</button></div>
        </div>
      </div>
    );
  }

  const key = created?.key ?? "ak_your_key";
  const team = teamId ?? "TEAM_ID";

  // The connector runs via `uvx`, which fetches the wheel from this server on demand,
  // so there's no separate "install the connector" step to forget (the #1 setup failure).
  // The only prerequisite is `uv` itself. pipx is the documented alternative (see Help).
  const wheelUrl = connector?.available && connector.path ? `${BASE}${connector.path}` : null;

  const setup: Record<Tool, { where: string; code: string }> = {
    claude: {
      where: "Run this once in your project:",
      code: `claude mcp add cognivio \\\n  --env KB_BASE_URL=${BASE} \\\n  --env KB_API_KEY=${key} \\\n  -- uvx --from ${wheelUrl} cognivio-mcp`
    },
    cursor: {
      where: "Create .cursor/mcp.json:",
      code: `{\n  "mcpServers": {\n    "cognivio": {\n      "command": "uvx",\n      "args": ["--from", "${wheelUrl}", "cognivio-mcp"],\n      "env": { "KB_BASE_URL": "${BASE}", "KB_API_KEY": "${key}" }\n    }\n  }\n}`
    },
    codex: {
      where: "Add to ~/.codex/config.toml:",
      code: `[mcp_servers.cognivio]\ncommand = "uvx"\nargs = ["--from", "${wheelUrl}", "cognivio-mcp"]\nenv = { KB_BASE_URL = "${BASE}", KB_API_KEY = "${key}" }`
    }
  };

  // Remote transport: the platform hosts the MCP server itself at /mcp, so there's
  // nothing to install, the tool connects over a URL with the key as a header.
  const mcpUrl = `${BASE}/mcp`;
  const remoteSetup: Record<Tool, { where: string; code: string }> = {
    claude: {
      where: "Run this once in your project:",
      code: `claude mcp add --transport http cognivio ${mcpUrl} \\\n  --header "Authorization: Bearer ${key}"`
    },
    cursor: {
      where: "Create .cursor/mcp.json:",
      code: `{\n  "mcpServers": {\n    "cognivio": {\n      "url": "${mcpUrl}",\n      "headers": { "Authorization": "Bearer ${key}" }\n    }\n  }\n}`
    },
    codex: {
      where: "Add to ~/.codex/config.toml:",
      code: `[mcp_servers.cognivio]\nurl = "${mcpUrl}"\nhttp_headers = { Authorization = "Bearer ${key}" }`
    }
  };

  // One prompt does both: install the always-on rule (via the setup_rule tool, which
  // returns the correct per-editor file) and seed the KB (via seed_plan). The agent does
  // the file writing, so the rule's format is always right (no hand-pasted Cursor file
  // missing its frontmatter) and works the same on the remote, zero-setup transport.
  const setupPrompt = `Set up Cognivio for THIS repository:

1. Call setup_rule for your editor ("claude", "cursor", or "codex") and write the file it
   returns, verbatim, at the path it gives. This makes every future session use the KB
   automatically (read before a task, write after).
2. Call list_teams to find the team id, then call seed_plan(team_id) and follow its ordered
   steps to scan the repo and write the starter docs.
3. Tell me which rule file you installed and what docs you created.`;

  // Manual fallback only (the agent-driven path above is preferred). Sourced from the same
  // canonical text the setup_rule tool serves, so the Cursor variant always carries its
  // alwaysApply frontmatter.
  const ruleSpec = tool ? ruleFileFor(tool) : null;

  return (
    <div className="ac-overlay" onClick={onClose}>
      <div className="ac-modal" style={{ maxWidth: 580 }} onClick={(e) => e.stopPropagation()}>
        <div className="ac-modal-head">
          <h2>Connect a coding tool</h2>
          <p>Pick your tool, we'll create an API key and give you the exact setup to paste.</p>
        </div>
        <div className="ac-modal-body">
          <div className="connect-tools">
            {TOOLS.map((t) => (
              <button key={t.id} className={`connect-tool${tool === t.id ? " active" : ""}`} onClick={() => choose(t.id)}>{t.name}</button>
            ))}
          </div>

          {error && <div className="ws-empty-sm" style={{ color: "#b91c1c" }}>{error}</div>}
          {busy && <div className="ws-empty-sm">Creating your key…</div>}

          {tool && created && (
            <>
              <div className="connect-transport">
                <button className={`connect-seg${transport === "remote" ? " active" : ""}`} onClick={() => setTransport("remote")}>
                  Remote <span className="seg-tag">zero-setup</span>
                </button>
                <button className={`connect-seg${transport === "local" ? " active" : ""}`} onClick={() => setTransport("local")}>
                  Local <span className="seg-tag">stdio</span>
                </button>
              </div>

              {transport === "remote" ? (
                <>
                  <h4 className="connect-h">1 · Add the MCP server</h4>
                  <p className="connect-sub">Nothing to install, the MCP server is hosted here. Your tool connects over a URL with the key as a header. {setup[tool].where}</p>
                  <pre className="connect-pre"><code>{remoteSetup[tool].code}</code></pre>
                  <Copy text={remoteSetup[tool].code} />
                  <p className="connect-sub" style={{ marginTop: 8 }}>No <code>uv</code>, no PATH, no install. (Remote MCP support varies by client/version, the <b>Local</b> tab is the universal fallback.)</p>
                </>
              ) : (
                <>
                  <h4 className="connect-h">1 · Install the runner (once)</h4>
                  <p className="connect-sub"><b>Prerequisite:</b> the connector is a small Python program. Install <a href="https://docs.astral.sh/uv/" target="_blank" rel="noreferrer">uv</a> once and step 2 fetches & runs it for you, there's nothing else to install:</p>
                  <pre className="connect-pre"><code>{UV_INSTALL}</code></pre>
                  <Copy text={UV_INSTALL} />
                  <p className="connect-note" style={{ marginTop: 8 }}>⚠ After installing, <b>restart your terminal</b> (or <code>source $HOME/.local/bin/env</code>) so <code>uvx</code> is on your PATH, then launch your tool from that shell. Check with <code>which uvx</code>, if it's empty, your tool won't be able to start the server.</p>
                  <p className="connect-sub" style={{ marginTop: 8 }}>Prefer pipx? <code>{wheelUrl ? `pipx install ${wheelUrl}` : "pipx install <connector-url>"}</code> instead, then use <code>cognivio-mcp</code> as the command. See <b>Help &amp; API</b> for both.</p>

                  {wheelUrl ? (
                    <>
                      <h4 className="connect-h">2 · Add the MCP server</h4>
                      <p className="connect-sub">{setup[tool].where}</p>
                      <pre className="connect-pre"><code>{setup[tool].code}</code></pre>
                      <Copy text={setup[tool].code} />
                    </>
                  ) : (
                    <>
                      <h4 className="connect-h">2 · Add the MCP server</h4>
                      <p className="connect-sub" style={{ color: "#b45309" }}>The connector download isn't available on this server build, so the config below can't be generated. See <code>mcp_server/README.md</code> to install from source.</p>
                    </>
                  )}
                </>
              )}

              <h4 className="connect-h">{transport === "remote" ? "2" : "3"} · Set up &amp; seed (paste once)</h4>
              <p className="connect-sub">Paste this to your agent once. It installs the always-on rule (so it uses the KB on <em>every</em> task, not just the first) and writes your starter docs:</p>
              <pre className="connect-pre"><code>{setupPrompt}</code></pre>
              <Copy text={setupPrompt} />
              {ruleSpec && (
                <details className="connect-fallback" style={{ marginTop: 10 }}>
                  <summary className="connect-sub" style={{ cursor: "pointer" }}>Prefer to add the rule file by hand? Create <code>{ruleSpec.path}</code></summary>
                  <p className="connect-sub" style={{ marginTop: 8 }}>{ruleSpec.append ? "Append this to" : "Create"} <code>{ruleSpec.path}</code> in your repo root{tool === "cursor" ? ": the alwaysApply frontmatter is what loads it every turn, so keep it" : ""}:</p>
                  <pre className="connect-pre"><code>{ruleSpec.content}</code></pre>
                  <Copy text={ruleSpec.content} />
                </details>
              )}

              <p className="connect-note">
                ⚠ This key is shown once (stored only as a hash). It includes write access so agents can record what they learn.
              </p>
            </>
          )}
        </div>
        <div className="ac-modal-foot"><span className="spacer" /><button className="ws-btn primary" onClick={onClose}>Done</button></div>
      </div>
    </div>
  );
}
