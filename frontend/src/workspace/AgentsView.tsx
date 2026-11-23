import { useEffect, useState, type ChangeEvent } from "react";
import { apiRequest } from "../lib/api";
import type { AuditEntry, MemoryListItem, Team } from "../lib/api";
import { ApiKeysPanel } from "../ApiKeysPanel";
import { ACTION_LABEL, timeAgo } from "./shared";

export function AgentsView({
  token,
  orgId,
  teams,
  canManage,
  memories,
  onOpen,
  onConnect
}: {
  token: string;
  orgId: string;
  teams: Team[];
  canManage: boolean;
  activity: AuditEntry[];
  memories: MemoryListItem[];
  onOpen: (id: string) => void;
  onConnect: () => void;
}) {
  const [tab, setTab] = useState<"keys" | "activity">("keys");
  const byId = new Map(memories.map((m) => [m.id, m.title]));
  const teamName = new Map(teams.map((t) => [t.id, t.name]));

  // Activity is org-wide (an agent's session spans teams), filtered + sorted +
  // paginated server-side so the full history is browsable, not just the latest page.
  const PAGE = 25;
  const [rows, setRows] = useState<AuditEntry[]>([]);
  const [total, setTotal] = useState(0);
  const [keyNames, setKeyNames] = useState<string[]>([]);
  const [fKey, setFKey] = useState("");
  const [fAction, setFAction] = useState("");
  const [fTeam, setFTeam] = useState("");
  const [order, setOrder] = useState<"desc" | "asc">("desc");
  const [page, setPage] = useState(0);
  const filtered = Boolean(fKey || fAction || fTeam);

  useEffect(() => {
    if (tab !== "activity") return;
    const p = new URLSearchParams({ limit: String(PAGE), offset: String(page * PAGE), order });
    if (fKey) p.set("keyName", fKey);
    if (fAction) p.set("action", fAction);
    if (fTeam) p.set("team", fTeam);
    apiRequest<{ entries: AuditEntry[]; total: number; keyNames: string[] }>(
      `/api/orgs/${orgId}/activity?${p.toString()}`,
      { token }
    )
      .then((r) => { setRows(r.entries); setTotal(r.total ?? r.entries.length); setKeyNames(r.keyNames ?? []); })
      .catch(() => undefined);
  }, [tab, orgId, token, fKey, fAction, fTeam, order, page]);

  const onFilter = (set: (v: string) => void) => (e: ChangeEvent<HTMLSelectElement>) => { set(e.target.value); setPage(0); };
  const from = total === 0 ? 0 : page * PAGE + 1;
  const to = Math.min(total, (page + 1) * PAGE);

  return (
    <div>
      <div className="ws-subtabs">
        <button className={`ws-subtab${tab === "keys" ? " active" : ""}`} onClick={() => setTab("keys")}>API keys</button>
        <button className={`ws-subtab${tab === "activity" ? " active" : ""}`} onClick={() => setTab("activity")}>Activity</button>
      </div>

      {tab === "keys" ? (
        <div className="agents-keys">
          <div className="ws-card agents-connect">
            <div className="ac-left">
              <strong>Connect a coding tool</strong>
              <span>Claude Code, Cursor, or Codex: we'll create the key and give you the exact setup to paste.</span>
            </div>
            {canManage && <button className="ws-btn primary" onClick={onConnect}>Connect a tool</button>}
          </div>
          <h3 className="agents-sub">Or create a key manually</h3>
          <p className="agents-note">Keys let agents read and write this org's memory via the MCP server or the <code>/api/v1</code> API.</p>
          <ApiKeysPanel token={token} orgId={orgId} teams={teams} canManage={canManage} />
        </div>
      ) : (
        <>
          <p style={{ color: "var(--text-secondary)", fontSize: 14, marginTop: 0 }}>
            What your agents have been reading and writing across <b>all teams</b>. Full history is kept. Filter, sort, and page through it below.
          </p>

          <div className="ws-filters">
            <select className="ws-select" value={fKey} onChange={onFilter(setFKey)} title="Filter by key">
              <option value="">All keys</option>
              {keyNames.map((k) => <option key={k} value={k}>{k}</option>)}
            </select>
            <select className="ws-select" value={fAction} onChange={onFilter(setFAction)} title="Filter by action">
              <option value="">All actions</option>
              {Object.entries(ACTION_LABEL).map(([k, label]) => <option key={k} value={k}>{label}</option>)}
            </select>
            <select className="ws-select" value={fTeam} onChange={onFilter(setFTeam)} title="Filter by team">
              <option value="">All teams</option>
              <option value="__org__">org-wide</option>
              {teams.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
            {filtered && <button className="ws-btn sm" onClick={() => { setFKey(""); setFAction(""); setFTeam(""); setPage(0); }}>Clear</button>}
          </div>

          {total === 0 ? (
            <div className="ws-empty-sm">{filtered ? "No activity matches these filters." : "No agent activity yet."}</div>
          ) : (
            <>
              <table className="ws-table">
                <thead><tr>
                  <th>
                    <button className="ws-th-sort" onClick={() => { setOrder((o) => (o === "desc" ? "asc" : "desc")); setPage(0); }} title="Sort by time">
                      When {order === "desc" ? "↓" : "↑"}
                    </button>
                  </th>
                  <th>Key</th><th>Team</th><th>Action</th><th>Target</th>
                </tr></thead>
                <tbody>
                  {rows.map((a) => (
                    <tr key={a.id}>
                      <td style={{ color: "var(--text-muted)", whiteSpace: "nowrap" }}>{timeAgo(a.at)}</td>
                      <td data-label="Key"><b>{a.keyName ?? "agent"}</b></td>
                      <td data-label="Team" style={{ color: "var(--text-secondary)", whiteSpace: "nowrap" }}>{a.teamId ? (teamName.get(a.teamId) ?? "-") : "org-wide"}</td>
                      <td className="main">{ACTION_LABEL[a.action] ?? a.action}{a.query ? <span style={{ color: "var(--text-muted)" }}>, “{a.query}”</span> : null}</td>
                      <td className="actions">
                        {a.memoryId ? (
                          a.memoryDeleted ? (
                            <span style={{ color: "var(--text-muted)" }} title="This doc has since been deleted">
                              {a.memoryTitle ?? byId.get(a.memoryId) ?? "(doc)"} <em>(deleted)</em>
                            </span>
                          ) : (
                            <button className="ws-btn sm" onClick={() => onOpen(a.memoryId!)}>
                              {a.memoryTitle ?? byId.get(a.memoryId) ?? "Open doc"}
                            </button>
                          )
                        ) : (
                          <span style={{ color: "var(--text-muted)" }}>-</span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="ws-pager">
                <span>{from}–{to} of {total}</span>
                <span className="spacer" />
                <button className="ws-btn sm" disabled={page === 0} onClick={() => setPage((p) => Math.max(0, p - 1))}>← Prev</button>
                <button className="ws-btn sm" disabled={to >= total} onClick={() => setPage((p) => p + 1)}>Next →</button>
              </div>
            </>
          )}
        </>
      )}
    </div>
  );
}
