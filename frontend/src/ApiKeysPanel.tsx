import { useCallback, useEffect, useState } from "react";
import { apiRequest, ApiKey, ApiKeyCreated, ApiScope, Team } from "./lib/api";

const ALL_SCOPES: ApiScope[] = ["memory:read", "memory:write", "map:read"];

export function ApiKeysPanel({
  token,
  orgId,
  teams,
  canManage
}: {
  token: string;
  orgId: string;
  teams: Team[];
  canManage: boolean;
}) {
  const [keys, setKeys] = useState<ApiKey[]>([]);
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<Set<ApiScope>>(new Set(["memory:read", "map:read"]));
  const [teamId, setTeamId] = useState<string>("");
  const [created, setCreated] = useState<ApiKeyCreated | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    apiRequest<ApiKey[]>(`/api/orgs/${orgId}/keys`, { token })
      .then(setKeys)
      .catch((err) => setError(err.message));
  }, [orgId, token]);

  useEffect(() => {
    if (canManage) load();
  }, [load, canManage]);

  function toggleScope(scope: ApiScope) {
    setScopes((prev) => {
      const next = new Set(prev);
      if (next.has(scope)) next.delete(scope);
      else next.add(scope);
      return next;
    });
  }

  async function createKey() {
    setError("");
    if (!name.trim() || scopes.size === 0) {
      setError("Name and at least one scope are required.");
      return;
    }
    try {
      const key = await apiRequest<ApiKeyCreated>(`/api/orgs/${orgId}/keys`, {
        method: "POST",
        token,
        body: { name: name.trim(), scopes: [...scopes], teamId: teamId || null }
      });
      setCreated(key);
      setName("");
      load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create key");
    }
  }

  async function revoke(id: string) {
    if (!window.confirm("Revoke this API key? Agents using it lose access immediately.")) return;
    await apiRequest<void>(`/api/orgs/${orgId}/keys/${id}`, { method: "DELETE", token });
    load();
  }

  if (!canManage) {
    return <div className="ws-empty-sm">Only org owners and admins can manage API keys.</div>;
  }

  return (
    <div>
      {created && (
        <div className="ws-card key-reveal">
          <strong>Copy your new key now, it won't be shown again.</strong>
          <code className="key-reveal-code">{created.key}</code>
          <div className="key-reveal-actions">
            <button className="ws-btn sm primary" onClick={() => navigator.clipboard?.writeText(created.key)}>Copy</button>
            <button className="ws-btn sm" onClick={() => setCreated(null)}>Dismiss</button>
          </div>
        </div>
      )}

      <div className="ws-card key-form-card">
        <div className="key-form-row">
          <input className="ws-input" placeholder="Key name (e.g. ci-agent)" value={name} onChange={(e) => setName(e.target.value)} />
          <select className="ws-select" value={teamId} onChange={(e) => setTeamId(e.target.value)} title="Restrict to a team">
            <option value="">All teams in org</option>
            {teams.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
          <button className="ws-btn primary" onClick={createKey}>Create key</button>
        </div>
        <div className="key-scopes">
          {ALL_SCOPES.map((s) => (
            <label key={s}>
              <input type="checkbox" checked={scopes.has(s)} onChange={() => toggleScope(s)} />
              <code>{s}</code>
            </label>
          ))}
        </div>
        {error && <div className="ws-empty-sm" style={{ color: "#ef6a6a" }}>{error}</div>}
      </div>

      {keys.length === 0 ? (
        <div className="ws-empty-sm">No API keys yet.</div>
      ) : (
        <table className="ws-table">
          <thead>
            <tr><th>Name</th><th>Prefix</th><th>Scopes</th><th>Team</th><th>Last used</th><th></th></tr>
          </thead>
          <tbody>
            {keys.map((k) => {
              const team = teams.find((t) => t.id === k.teamId);
              const revoked = k.revokedAt !== null;
              return (
                <tr key={k.id} style={revoked ? { opacity: 0.5 } : undefined}>
                  <td><b>{k.name}</b></td>
                  <td><code>{k.prefix}…</code></td>
                  <td>{k.scopes.map((s) => <span key={s} className="ty-pill" style={{ marginRight: 4 }}>{s}</span>)}</td>
                  <td>{team ? team.name : "All"}</td>
                  <td style={{ color: "var(--text-muted)" }}>{k.lastUsedAt ? new Date(k.lastUsedAt).toLocaleDateString() : "never"}</td>
                  <td style={{ textAlign: "right" }}>
                    {revoked
                      ? <span style={{ color: "var(--text-muted)", fontSize: 12 }}>revoked</span>
                      : <button className="ws-btn sm danger" onClick={() => revoke(k.id)}>Revoke</button>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}
