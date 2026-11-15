import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  apiRequest,
  type Appearance,
  type AdminAction,
  type AdminOrg,
  type AdminOrgDetail,
  type AdminOverview,
  type AdminUsage,
  type AdminUser,
  type AdminUserUsage,
  type SecurityEvent,
  type UsageTrendPoint,
  type User
} from "../lib/api";
import { ACTION_LABEL, timeAgo } from "../workspace/shared";

type Tab = "overview" | "usage" | "users" | "orgs" | "appearance" | "security" | "actions";

const TABS: { id: Tab; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "usage", label: "Usage" },
  { id: "users", label: "Users" },
  { id: "orgs", label: "Organizations" },
  { id: "appearance", label: "Appearance" },
  { id: "security", label: "Security" },
  { id: "actions", label: "Admin log" }
];

const WINDOWS = [7, 30, 90] as const;

// Shared sparkline for any daily-count series (usage trend, etc.).
function Spark({ trend }: { trend: UsageTrendPoint[] }) {
  const max = Math.max(1, ...trend.map((d) => d.count));
  return (
    <div className="adm-spark">
      {trend.map((d, i) => (
        <span key={i} className="bar" title={`${d.date}: ${d.count}`}
          style={{ height: `${Math.max(2, (d.count / max) * 100)}%` }} />
      ))}
    </div>
  );
}

// Shared horizontal bar list for a {label: count} bucket, sorted desc.
function Bars({ data, warn }: { data: [string, number][]; warn?: boolean }) {
  const max = Math.max(1, ...data.map(([, n]) => n));
  return (
    <div className="adm-bars">
      {data.map(([label, n]) => (
        <div className="adm-bar" key={label}>
          <span>{ACTION_LABEL[label] ?? label}</span>
          <span className="track"><span className={`fill${warn ? " warn" : ""}`} style={{ width: `${(n / max) * 100}%` }} /></span>
          <span className="v">{n}</span>
        </div>
      ))}
    </div>
  );
}

function WindowPicker({ days, onChange }: { days: number; onChange: (d: number) => void }) {
  return (
    <div className="adm-window">
      {WINDOWS.map((w) => (
        <button key={w} className={`adm-window-btn${days === w ? " on" : ""}`} onClick={() => onChange(w)}>{w}d</button>
      ))}
    </div>
  );
}

function pct(r: { hitRate: number | null }): string {
  return r.hitRate === null ? "-" : `${Math.round(r.hitRate * 100)}%`;
}

const SEC_LABEL: Record<string, string> = {
  failed_login: "Failed login",
  suspended_login_attempt: "Suspended login attempt",
  invalid_api_key: "Invalid API key"
};

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  const units = ["KB", "MB", "GB", "TB", "PB"];
  let v = n / 1024;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return `${v >= 100 || Number.isInteger(v) ? Math.round(v) : v.toFixed(1)} ${units[i]}`;
}

function fmtDate(iso: string | null): string {
  if (!iso) return "-";
  const hasTz = /([zZ]|[+-]\d\d:?\d\d)$/.test(iso);
  return new Date(hasTz ? iso : iso + "Z").toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric"
  });
}

export function AdminView({ token, user, appearance, onAppearanceChanged, onLogout }: {
  token: string;
  user: User | null;
  appearance: Appearance;
  onAppearanceChanged: (a: Appearance) => void;
  onLogout: () => void;
}) {
  const [tab, setTab] = useState<Tab>("overview");

  return (
    <div className="adm">
      <style>{adminCss}</style>
      <header className="adm-top">
        <div className="adm-brand">
          <Link to="/app" className="adm-logo">Cognivio</Link>
          <span className="adm-badge">admin</span>
        </div>
        <div className="adm-who">
          <span>{user?.email}</span>
          <Link to="/app" className="adm-link">← Workspace</Link>
          <button className="adm-link" onClick={onLogout}>Log out</button>
        </div>
      </header>

      <nav className="adm-tabs">
        {TABS.map((t) => (
          <button
            key={t.id}
            className={`adm-tab${tab === t.id ? " on" : ""}`}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </nav>

      <main className="adm-main">
        {tab === "overview" && <OverviewTab token={token} showPlans={!appearance.selfHosted} />}
        {tab === "usage" && <UsageTab token={token} />}
        {tab === "users" && <UsersTab token={token} />}
        {tab === "orgs" && <OrgsTab token={token} showPlans={!appearance.selfHosted} />}
        {tab === "appearance" && <AppearanceTab token={token} appearance={appearance} onChanged={onAppearanceChanged} />}
        {tab === "security" && <SecurityTab token={token} />}
        {tab === "actions" && <ActionsTab token={token} />}
      </main>
    </div>
  );
}

function useAdmin<T>(path: string, token: string, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const reload = useCallback(() => {
    setLoading(true);
    apiRequest<T>(path, { token })
      .then((d) => { setData(d); setError(""); })
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load"))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, token, ...deps]);
  useEffect(reload, [reload]);
  return { data, error, loading, reload };
}

// --- Overview ---

function StorageCard({ storage }: { storage: NonNullable<AdminOverview["storage"]> }) {
  const hasFs = storage.fsTotalSize !== null && storage.fsFreeSize !== null;
  // Prefer real filesystem free space; fall back to DB-allocated size when the host
  // doesn't expose it (some managed tiers).
  const usedPct = hasFs ? (storage.fsUsedSize! / storage.fsTotalSize!) * 100 : null;
  const warn = usedPct !== null && usedPct >= 85;

  return (
    <div className="adm-card">
      <h3>Database storage</h3>
      {hasFs ? (
        <>
          <div className="adm-storage-head">
            <span className="adm-storage-free">
              <strong className={warn ? "warn" : ""}>{fmtBytes(storage.fsFreeSize!)}</strong> free
            </span>
            <span className="adm-muted">
              {fmtBytes(storage.fsUsedSize!)} of {fmtBytes(storage.fsTotalSize!)} used · {Math.round(usedPct!)}%
            </span>
          </div>
          <div className="adm-storage-track">
            <span className={`fill${warn ? " warn" : ""}`} style={{ width: `${Math.min(100, usedPct!)}%` }} />
          </div>
        </>
      ) : (
        <div className="adm-storage-head">
          <span className="adm-storage-free"><strong>{fmtBytes(storage.totalSize)}</strong> on disk</span>
          <span className="adm-muted">host doesn't report free space</span>
        </div>
      )}
      <div className="adm-storage-legend">
        <span><i className="dot data" /> Data {fmtBytes(storage.dataSize)}</span>
        <span><i className="dot index" /> Indexes {fmtBytes(storage.indexSize)}</span>
        {storage.freeStorageSize > 0 && <span><i className="dot reuse" /> Reusable {fmtBytes(storage.freeStorageSize)}</span>}
      </div>
    </div>
  );
}

function OverviewTab({ token, showPlans }: { token: string; showPlans: boolean }) {
  const { data, error, loading } = useAdmin<AdminOverview>("/api/admin/overview?days=30", token);
  if (loading) return <div className="adm-empty">Loading…</div>;
  if (error) return <div className="adm-error">{error}</div>;
  if (!data) return null;

  const t = data.totals;
  const act = data.agentActivity;
  const maxTrend = Math.max(1, ...data.signupTrend.map((d) => d.count));
  const actions = Object.entries(act.byAction).sort((a, b) => b[1] - a[1]);
  const maxAction = Math.max(1, ...actions.map(([, n]) => n));
  const sec = Object.entries(data.security.byType).sort((a, b) => b[1] - a[1]);

  // Week-over-week signup momentum (real signups only).
  const prev7d = data.signups.prev7d ?? 0;
  const wow = data.signups.last7d - prev7d;
  const wowStr = prev7d === 0 && wow === 0 ? "no signups last week"
    : `${wow >= 0 ? "▲" : "▼"} ${Math.abs(wow)} vs prior week`;

  const cards: { n: number | string; l: string; sub: string; warn?: boolean }[] = [
    { n: t.users, l: "users", sub: `${t.verifiedUsers} verified` },
    { n: data.signups.last7d, l: "new this week", sub: wowStr, warn: wow < 0 },
    { n: t.orgs, l: "organizations", sub: `${act.activeOrgs} active (30d) · ${t.teams} teams` },
    { n: t.memories, l: "memories", sub: "active docs" },
    {
      n: pct(data.retrieval), l: "retrieval hit-rate",
      sub: `${data.retrieval.hits}/${data.retrieval.lookups} lookups found a doc`
    },
    { n: act.totalEvents, l: "agent actions (30d)", sub: `${act.activeKeys} of ${t.apiKeys} keys active` },
    ...(showPlans ? [{ n: data.plans?.enterprise ?? 0, l: "orgs on Teams", sub: `${data.plans?.free ?? 0} on free` }] : []),
    {
      n: t.suspendedUsers,
      l: "suspended",
      sub: `${data.security.totalEvents} abuse signals (30d)`,
      warn: t.suspendedUsers > 0 || data.security.totalEvents > 0
    }
  ];

  return (
    <div className="adm-grid">
      <div className="adm-stats">
        {cards.map((c, i) => (
          <div className="adm-stat" key={i}>
            <div className={`n${c.warn ? " warn" : ""}`}>{c.n}</div>
            <div className="l">{c.l}</div>
            <div className="sub">{c.sub}</div>
          </div>
        ))}
      </div>

      {data.storage && <StorageCard storage={data.storage} />}

      <div className="adm-cols2">
        <div className="adm-card">
          <h3>New users (30 days)</h3>
          <div className="adm-spark">
            {data.signupTrend.map((d, i) => (
              <span
                key={i}
                className="bar"
                title={`${d.date}: ${d.count}`}
                style={{ height: `${Math.max(2, (d.count / maxTrend) * 100)}%` }}
              />
            ))}
          </div>
        </div>

        <div className="adm-card">
          <h3>Abuse signals (30 days)</h3>
          {sec.length === 0 ? (
            <div className="adm-empty-sm">No suspicious activity recorded. ✓</div>
          ) : (
            <div className="adm-bars">
              {sec.map(([type, n]) => (
                <div className="adm-bar" key={type}>
                  <span>{SEC_LABEL[type] ?? type}</span>
                  <span className="track"><span className="fill warn" style={{ width: `${(n / Math.max(1, ...sec.map(([, x]) => x))) * 100}%` }} /></span>
                  <span className="v">{n}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="adm-card">
        <h3>Agent activity: {data.agentActivity.totalEvents} actions · {data.agentActivity.activeKeys} active keys (30d)</h3>
        {actions.length === 0 ? (
          <div className="adm-empty-sm">No agent activity in this window.</div>
        ) : (
          <div className="adm-bars">
            {actions.map(([action, n]) => (
              <div className="adm-bar" key={action}>
                <span>{ACTION_LABEL[action] ?? action}</span>
                <span className="track"><span className="fill" style={{ width: `${(n / maxAction) * 100}%` }} /></span>
                <span className="v">{n}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// --- Usage ---

function UsageTab({ token }: { token: string }) {
  const [days, setDays] = useState(30);
  const { data, error, loading } = useAdmin<AdminUsage>(`/api/admin/usage?days=${days}`, token, [days]);

  const actions = data ? Object.entries(data.byAction).sort((a, b) => b[1] - a[1]) : [];

  const cards = data ? [
    { n: data.totals.actions, l: "agent actions", sub: `last ${days} days` },
    { n: data.totals.activeOrgs, l: "active orgs", sub: `${data.totals.activeUsers} active members` },
    { n: data.totals.activeKeys, l: "active keys", sub: "made ≥1 call" },
    { n: pct(data.retrieval), l: "retrieval hit-rate", sub: `${data.retrieval.hits}/${data.retrieval.lookups} lookups found a doc` },
  ] : [];

  return (
    <div className="adm-grid">
      <div className="adm-toolbar">
        <h2 className="adm-h2">Platform usage</h2>
        <WindowPicker days={days} onChange={setDays} />
      </div>
      {error && <div className="adm-error">{error}</div>}
      {loading || !data ? <div className="adm-empty">Loading…</div> : (
        <>
          <div className="adm-stats">
            {cards.map((c, i) => (
              <div className="adm-stat" key={i}>
                <div className="n">{c.n}</div>
                <div className="l">{c.l}</div>
                <div className="sub">{c.sub}</div>
              </div>
            ))}
          </div>

          <div className="adm-card">
            <h3>Agent activity: {data.totals.actions} actions over {days} days</h3>
            {data.totals.actions === 0 ? <div className="adm-empty-sm">No activity in this window.</div> : <Spark trend={data.trend} />}
          </div>

          <div className="adm-cols2">
            <div className="adm-card">
              <h3>Top organizations</h3>
              {data.topOrgs.length === 0 ? <div className="adm-empty-sm">No activity.</div> : (
                <div className="adm-bars">
                  {data.topOrgs.map((o) => {
                    const max = Math.max(1, ...data.topOrgs.map((x) => x.actions));
                    return (
                      <div className="adm-bar wide" key={o.orgId}>
                        <span title={o.name || o.orgId}>{o.name || o.orgId}{o.plan === "enterprise" && <span className="adm-pill admin" style={{ marginLeft: 6 }}>teams</span>}</span>
                        <span className="track"><span className="fill" style={{ width: `${(o.actions / max) * 100}%` }} /></span>
                        <span className="v">{o.actions}</span>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            <div className="adm-card">
              <h3>Top API keys</h3>
              {data.topKeys.length === 0 ? <div className="adm-empty-sm">No activity.</div> : (
                <div className="adm-bars">
                  {data.topKeys.map((k) => {
                    const max = Math.max(1, ...data.topKeys.map((x) => x.actions));
                    return (
                      <div className="adm-bar wide" key={k.keyId}>
                        <span title={`${k.keyName || "key"} · ${k.orgName || ""}`}>{k.keyName || "-"} <span className="adm-muted">{k.orgName || ""}</span></span>
                        <span className="track"><span className="fill" style={{ width: `${(k.actions / max) * 100}%` }} /></span>
                        <span className="v">{k.actions}</span>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          </div>

          <div className="adm-card">
            <h3>By action</h3>
            {actions.length === 0 ? <div className="adm-empty-sm">No activity.</div> : <Bars data={actions} />}
          </div>
        </>
      )}
    </div>
  );
}

// --- Users ---

function UsersTab({ token }: { token: string }) {
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [onlySuspended, setOnlySuspended] = useState(false);
  const path = `/api/admin/users?limit=100${query ? `&q=${encodeURIComponent(query)}` : ""}${onlySuspended ? "&suspended=true" : ""}`;
  const { data, error, loading, reload } = useAdmin<{ users: AdminUser[]; total: number }>(path, token);
  const [busy, setBusy] = useState<string | null>(null);
  const [usageUser, setUsageUser] = useState<AdminUser | null>(null);

  async function suspend(u: AdminUser) {
    const reason = window.prompt(`Suspend ${u.email}? Optionally give a reason (the user will be logged out and blocked from signing in):`, "");
    if (reason === null) return;
    setBusy(u.id);
    try {
      await apiRequest(`/api/admin/users/${u.id}/suspend?reason=${encodeURIComponent(reason)}`, { method: "POST", token });
      reload();
    } catch (e) { window.alert(e instanceof Error ? e.message : "Failed"); }
    finally { setBusy(null); }
  }

  async function unsuspend(u: AdminUser) {
    setBusy(u.id);
    try {
      await apiRequest(`/api/admin/users/${u.id}/unsuspend`, { method: "POST", token });
      reload();
    } catch (e) { window.alert(e instanceof Error ? e.message : "Failed"); }
    finally { setBusy(null); }
  }

  async function remove(u: AdminUser) {
    if (!window.confirm(`Permanently DELETE ${u.email} and all ${u.orgCount} org(s) they own, including every memory, team, and API key? This cannot be undone.`)) return;
    setBusy(u.id);
    try {
      await apiRequest(`/api/admin/users/${u.id}`, { method: "DELETE", token });
      reload();
    } catch (e) { window.alert(e instanceof Error ? e.message : "Failed"); }
    finally { setBusy(null); }
  }

  async function verify(u: AdminUser) {
    setBusy(u.id);
    try {
      await apiRequest(`/api/admin/users/${u.id}/verify`, { method: "POST", token });
      reload();
    } catch (e) { window.alert(e instanceof Error ? e.message : "Failed"); }
    finally { setBusy(null); }
  }

  return (
    <div className="adm-grid">
      <form className="adm-toolbar" onSubmit={(e) => { e.preventDefault(); setQuery(q.trim()); }}>
        <input className="adm-input" placeholder="Search email or name…" value={q} onChange={(e) => setQ(e.target.value)} />
        <button className="adm-btn">Search</button>
        <label className="adm-check">
          <input type="checkbox" checked={onlySuspended} onChange={(e) => setOnlySuspended(e.target.checked)} /> Suspended only
        </label>
        {data && <span className="adm-count">{data.total} total</span>}
      </form>

      {error && <div className="adm-error">{error}</div>}
      {loading ? <div className="adm-empty">Loading…</div> : (
        <div className="adm-card adm-tablewrap">
          <table className="adm-table">
            <thead>
              <tr><th>User</th><th>Status</th><th>Orgs</th><th>Joined</th><th></th></tr>
            </thead>
            <tbody>
              {data?.users.map((u) => (
                <tr key={u.id} className={u.suspendedAt ? "suspended" : ""}>
                  <td>
                    <div className="adm-u-name">{u.name || "-"}{u.isAdmin && <span className="adm-pill admin">admin</span>}</div>
                    <div className="adm-u-email">{u.email}</div>
                  </td>
                  <td>
                    {u.suspendedAt ? (
                      <span className="adm-pill danger" title={u.suspendedReason || ""}>suspended</span>
                    ) : u.emailVerified ? (
                      <span className="adm-pill ok">verified</span>
                    ) : (
                      <span className="adm-pill">unverified</span>
                    )}
                  </td>
                  <td>{u.orgCount}</td>
                  <td className="adm-muted">{fmtDate(u.createdAt)}</td>
                  <td className="adm-actions-cell">
                    <button className="adm-mini" onClick={() => setUsageUser(u)}>Usage</button>
                    {!u.emailVerified && (
                      <button className="adm-mini" disabled={busy === u.id} onClick={() => verify(u)}>Verify</button>
                    )}
                    {!u.isAdmin && (
                      u.suspendedAt ? (
                        <button className="adm-mini" disabled={busy === u.id} onClick={() => unsuspend(u)}>Unsuspend</button>
                      ) : (
                        <button className="adm-mini" disabled={busy === u.id} onClick={() => suspend(u)}>Suspend</button>
                      )
                    )}
                    {!u.isAdmin && (
                      <button className="adm-mini danger" disabled={busy === u.id} onClick={() => remove(u)}>Delete</button>
                    )}
                  </td>
                </tr>
              ))}
              {data?.users.length === 0 && <tr><td colSpan={5} className="adm-empty-sm">No users match.</td></tr>}
            </tbody>
          </table>
        </div>
      )}

      {usageUser && <UserUsageModal token={token} user={usageUser} onClose={() => setUsageUser(null)} />}
    </div>
  );
}

function UserUsageModal({ token, user, onClose }: { token: string; user: AdminUser; onClose: () => void }) {
  const [days, setDays] = useState(30);
  const { data, error, loading } = useAdmin<AdminUserUsage>(`/api/admin/users/${user.id}/usage?days=${days}`, token, [days]);
  const actions = data ? Object.entries(data.byAction).sort((a, b) => b[1] - a[1]) : [];

  return (
    <div className="adm-overlay" onClick={onClose}>
      <div className="adm-modal" onClick={(e) => e.stopPropagation()}>
        <div className="adm-modal-head">
          <h2>{user.name || user.email}<span className="adm-muted" style={{ fontSize: 13, marginLeft: 8 }}>usage</span></h2>
          <button className="adm-link" onClick={onClose}>✕ Close</button>
        </div>
        <div className="adm-modal-body">
          <div className="adm-toolbar" style={{ marginBottom: 4 }}>
            <span className="adm-detail-meta">Activity across this user's organizations</span>
            <span style={{ marginLeft: "auto" }}><WindowPicker days={days} onChange={setDays} /></span>
          </div>
          {error && <div className="adm-error">{error}</div>}
          {loading || !data ? <div className="adm-empty">Loading…</div> : (
            <>
              <div className="adm-stats" style={{ marginTop: 12 }}>
                <div className="adm-stat"><div className="n">{data.totals.actions}</div><div className="l">actions</div><div className="sub">last {days} days</div></div>
                <div className="adm-stat"><div className="n">{data.totals.activeKeys}</div><div className="l">active keys</div><div className="sub">made ≥1 call</div></div>
                <div className="adm-stat"><div className="n">{pct(data.retrieval)}</div><div className="l">hit-rate</div><div className="sub">{data.retrieval.hits}/{data.retrieval.lookups} found a doc</div></div>
                <div className="adm-stat"><div className="n" style={{ fontSize: 15 }}>{data.totals.lastActiveAt ? timeAgo(data.totals.lastActiveAt) : "never"}</div><div className="l">last active</div><div className="sub">most recent call</div></div>
              </div>

              {data.totals.actions > 0 && (
                <div className="adm-card" style={{ marginTop: 14 }}>
                  <h3>Activity ({days} days)</h3>
                  <Spark trend={data.trend} />
                </div>
              )}

              <h3>By organization</h3>
              {data.perOrg.length === 0 ? <div className="adm-empty-sm">No organizations.</div> : data.perOrg.map((o) => (
                <div className="adm-detail-row" key={o.orgId}>
                  <span>{o.name || o.orgId}<span className="adm-pill" style={{ marginLeft: 6 }}>{o.role}</span>{o.plan === "enterprise" && <span className="adm-pill admin" style={{ marginLeft: 6 }}>teams</span>}</span>
                  <span className="adm-muted">{o.actions} actions</span>
                </div>
              ))}

              <h3>By API key</h3>
              {data.perKey.length === 0 ? <div className="adm-empty-sm">No key activity in this window.</div> : data.perKey.map((k) => (
                <div className="adm-detail-row" key={k.keyId}>
                  <span>
                    {k.prefix ? <code>{k.prefix}…</code> : null} {k.keyName || "-"}
                    {k.revoked && <span className="adm-pill danger" style={{ marginLeft: 6 }}>revoked</span>}
                    <span className="adm-muted" style={{ marginLeft: 8 }}>{k.orgName || ""}</span>
                  </span>
                  <span className="adm-muted">{k.actions} actions</span>
                </div>
              ))}

              {actions.length > 0 && (
                <>
                  <h3>By action</h3>
                  <Bars data={actions} />
                </>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// --- Orgs ---

function OrgsTab({ token, showPlans }: { token: string; showPlans: boolean }) {
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const path = `/api/admin/orgs?limit=100${query ? `&q=${encodeURIComponent(query)}` : ""}`;
  const { data, error, loading, reload } = useAdmin<{ orgs: AdminOrg[]; total: number }>(path, token);
  const [busy, setBusy] = useState<string | null>(null);
  const [detailId, setDetailId] = useState<string | null>(null);

  async function remove(o: AdminOrg) {
    if (!window.confirm(`Permanently DELETE "${o.name}": ${o.memories} memories, ${o.teams} teams, ${o.apiKeys} API keys, ${o.members} members? This cannot be undone.`)) return;
    setBusy(o.id);
    try {
      await apiRequest(`/api/admin/orgs/${o.id}`, { method: "DELETE", token });
      reload();
    } catch (e) { window.alert(e instanceof Error ? e.message : "Failed"); }
    finally { setBusy(null); }
  }

  async function setPlan(o: AdminOrg, plan: string) {
    if (plan === o.plan) return;
    setBusy(o.id);
    try {
      await apiRequest(`/api/admin/orgs/${o.id}/plan?plan=${plan}`, { method: "POST", token });
      reload();
    } catch (e) { window.alert(e instanceof Error ? e.message : "Failed"); }
    finally { setBusy(null); }
  }

  return (
    <div className="adm-grid">
      <form className="adm-toolbar" onSubmit={(e) => { e.preventDefault(); setQuery(q.trim()); }}>
        <input className="adm-input" placeholder="Search organization name…" value={q} onChange={(e) => setQ(e.target.value)} />
        <button className="adm-btn">Search</button>
        {data && <span className="adm-count">{data.total} total</span>}
      </form>

      {error && <div className="adm-error">{error}</div>}
      {loading ? <div className="adm-empty">Loading…</div> : (
        <div className="adm-card adm-tablewrap">
          <table className="adm-table">
            <thead>
              <tr><th>Organization</th><th>Owner</th>{showPlans && <th>Plan</th>}<th>Members</th><th>Memories</th><th>Keys</th><th>Created</th><th></th></tr>
            </thead>
            <tbody>
              {data?.orgs.map((o) => (
                <tr key={o.id}>
                  <td><div className="adm-u-name">{o.name}</div><div className="adm-u-email">{o.slug}</div></td>
                  <td className="adm-muted">{o.ownerEmail || "-"}</td>
                  {showPlans && (
                  <td>
                    <select className="adm-plan" value={o.plan} disabled={busy === o.id} onChange={(e) => setPlan(o, e.target.value)}>
                      <option value="free">free</option>
                      <option value="enterprise">teams</option>
                    </select>
                  </td>
                  )}
                  <td>{o.members}</td>
                  <td>{o.memories}</td>
                  <td>{o.apiKeys}</td>
                  <td className="adm-muted">{fmtDate(o.createdAt)}</td>
                  <td className="adm-actions-cell">
                    <button className="adm-mini" onClick={() => setDetailId(o.id)}>View</button>
                    <button className="adm-mini danger" disabled={busy === o.id} onClick={() => remove(o)}>Delete</button>
                  </td>
                </tr>
              ))}
              {data?.orgs.length === 0 && <tr><td colSpan={8} className="adm-empty-sm">No organizations match.</td></tr>}
            </tbody>
          </table>
        </div>
      )}

      {detailId && <OrgDetailModal token={token} orgId={detailId} onClose={() => setDetailId(null)} />}
    </div>
  );
}

function OrgDetailModal({ token, orgId, onClose }: { token: string; orgId: string; onClose: () => void }) {
  const { data, error, loading, reload } = useAdmin<AdminOrgDetail>(`/api/admin/orgs/${orgId}`, token);
  const [busy, setBusy] = useState<string | null>(null);

  async function revokeKey(keyId: string) {
    if (!window.confirm("Revoke this API key? Any agent using it stops working immediately.")) return;
    setBusy(keyId);
    try {
      await apiRequest(`/api/admin/keys/${keyId}/revoke`, { method: "POST", token });
      reload();
    } catch (e) { window.alert(e instanceof Error ? e.message : "Failed"); }
    finally { setBusy(null); }
  }

  return (
    <div className="adm-overlay" onClick={onClose}>
      <div className="adm-modal" onClick={(e) => e.stopPropagation()}>
        <div className="adm-modal-head">
          <h2>{data?.name ?? "Organization"}{data && <span className={`adm-pill ${data.plan === "enterprise" ? "admin" : ""}`} style={{ marginLeft: 8 }}>{data.plan === "enterprise" ? "teams" : data.plan}</span>}</h2>
          <button className="adm-link" onClick={onClose}>✕ Close</button>
        </div>
        {error && <div className="adm-error">{error}</div>}
        {loading || !data ? <div className="adm-empty">Loading…</div> : (
          <div className="adm-modal-body">
            <div className="adm-detail-meta">
              {data.members.length} member{data.members.length === 1 ? "" : "s"} · {data.teams.length} team{data.teams.length === 1 ? "" : "s"} · {data.activity30d} agent actions (30d)
            </div>

            <h3>Members</h3>
            {data.members.map((m) => (
              <div className="adm-detail-row" key={m.userId}>
                <span>{m.email || m.userId}{m.suspended && <span className="adm-pill danger" style={{ marginLeft: 6 }}>suspended</span>}</span>
                <span className="adm-pill">{m.role}</span>
              </div>
            ))}

            <h3>Teams</h3>
            {data.teams.length === 0 ? <div className="adm-empty-sm">No teams.</div> : data.teams.map((t) => (
              <div className="adm-detail-row" key={t.id}>
                <span>{t.name}</span>
                <span className="adm-muted">{t.memories} memories</span>
              </div>
            ))}

            <h3>API keys</h3>
            {data.keys.length === 0 ? <div className="adm-empty-sm">No API keys.</div> : data.keys.map((k) => (
              <div className="adm-detail-row" key={k.id}>
                <span>
                  <code>{k.prefix}…</code> {k.name}
                  {k.revokedAt && <span className="adm-pill danger" style={{ marginLeft: 6 }}>revoked</span>}
                  <span className="adm-muted" style={{ marginLeft: 8 }}>{k.lastUsedAt ? `used ${timeAgo(k.lastUsedAt)}` : "never used"}</span>
                </span>
                {!k.revokedAt && (
                  <button className="adm-mini danger" disabled={busy === k.id} onClick={() => revokeKey(k.id)}>Revoke</button>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// --- Security ---

function SecurityTab({ token }: { token: string }) {
  const [type, setType] = useState("");
  const path = `/api/admin/security?limit=200${type ? `&type=${type}` : ""}`;
  const { data, error, loading } = useAdmin<{ events: SecurityEvent[]; total: number }>(path, token);

  return (
    <div className="adm-grid">
      <div className="adm-toolbar">
        <select className="adm-input" value={type} onChange={(e) => setType(e.target.value)}>
          <option value="">All event types</option>
          <option value="failed_login">Failed login</option>
          <option value="suspended_login_attempt">Suspended login attempt</option>
          <option value="invalid_api_key">Invalid API key</option>
        </select>
        {data && <span className="adm-count">{data.total} total</span>}
      </div>

      {error && <div className="adm-error">{error}</div>}
      {loading ? <div className="adm-empty">Loading…</div> : (
        <div className="adm-card adm-tablewrap">
          <table className="adm-table">
            <thead><tr><th>When</th><th>Event</th><th>Who</th><th>IP</th><th>Detail</th></tr></thead>
            <tbody>
              {data?.events.map((e) => (
                <tr key={e.id} className={e.severity === "warn" || e.severity === "critical" ? "suspended" : ""}>
                  <td className="adm-muted" title={e.at || ""}>{e.at ? timeAgo(e.at) : "-"}</td>
                  <td><span className={`adm-pill ${e.severity === "info" ? "" : "danger"}`}>{SEC_LABEL[e.type] ?? e.type}</span></td>
                  <td className="adm-u-email">{e.email || e.userId || "-"}</td>
                  <td className="adm-muted">{e.ip || "-"}</td>
                  <td className="adm-muted">{e.detail ? JSON.stringify(e.detail) : "-"}</td>
                </tr>
              ))}
              {data?.events.length === 0 && <tr><td colSpan={5} className="adm-empty-sm">No events. ✓</td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// --- Admin actions log ---

function ActionsTab({ token }: { token: string }) {
  const { data, error, loading } = useAdmin<{ actions: AdminAction[]; total: number }>("/api/admin/actions?limit=200", token);
  return (
    <div className="adm-grid">
      <p className="adm-note">Every moderation action taken in this console, kept for accountability.</p>
      {error && <div className="adm-error">{error}</div>}
      {loading ? <div className="adm-empty">Loading…</div> : (
        <div className="adm-card adm-tablewrap">
          <table className="adm-table">
            <thead><tr><th>When</th><th>Action</th><th>By</th><th>Target</th><th>Reason</th></tr></thead>
            <tbody>
              {data?.actions.map((a) => (
                <tr key={a.id}>
                  <td className="adm-muted" title={a.at || ""}>{a.at ? timeAgo(a.at) : "-"}</td>
                  <td><span className="adm-pill">{a.action}</span></td>
                  <td className="adm-u-email">{a.adminEmail || "-"}</td>
                  <td className="adm-u-email">{a.targetEmail || a.targetOrgName || a.targetUserId || a.targetOrgId || "-"}</td>
                  <td className="adm-muted">{a.reason || (a.removed ? Object.entries(a.removed).map(([k, v]) => `${v} ${k}`).join(", ") : "-")}</td>
                </tr>
              ))}
              {data?.actions.length === 0 && <tr><td colSpan={5} className="adm-empty-sm">No admin actions yet.</td></tr>}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

// --- Appearance ---

const THEMES: { id: Appearance["userTheme"]; label: string; blurb: string }[] = [
  { id: "editorial", label: "Editorial", blurb: "White page, Helvetica, black buttons. Matches the \"Read. Write. Know.\" landing page." },
  { id: "terminal", label: "Terminal", blurb: "Dark console, monospace, green accent. The original look." }
];

function AppearanceTab({ token, appearance, onChanged }: {
  token: string;
  appearance: Appearance;
  onChanged: (a: Appearance) => void;
}) {
  const [theme, setTheme] = useState(appearance.userTheme);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const dirty = theme !== appearance.userTheme;

  async function save() {
    setBusy(true);
    setError("");
    setMsg("");
    try {
      const next = await apiRequest<Appearance>("/api/admin/appearance", {
        method: "PUT", token, body: { userTheme: theme }
      });
      onChanged(next);
      setMsg("Saved. Everyone gets the new look on their next page load.");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not save");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="adm-grid">
      <p className="adm-note">
        What visitors and users see. The theme applies to everyone, so preview before you save.
        {appearance.updatedAt && appearance.updatedBy && (
          <> Last changed by {appearance.updatedBy}, {timeAgo(appearance.updatedAt)}.</>
        )}
      </p>

      <div className="adm-cols2">
        <div className="adm-card">
          <h3>User theme</h3>
          <p className="adm-note" style={{ marginBottom: 12 }}>The look of the login, register and reset pages and the workspace after sign-in. Users keep their own dark/light choice inside the theme.</p>
          <div className="adm-radios">
            {THEMES.map((t) => (
              <label key={t.id} className={`adm-radio${theme === t.id ? " on" : ""}`}>
                <input type="radio" name="theme" checked={theme === t.id} onChange={() => setTheme(t.id)} />
                <span><strong>{t.label}</strong><br /><span className="adm-muted">{t.blurb}</span></span>
              </label>
            ))}
          </div>
          <div className="adm-toolbar" style={{ marginTop: 14 }}>
            <a className="adm-mini" href="/login" target="_blank" rel="noreferrer">Preview login</a>
            <a className="adm-mini" href="/app" target="_blank" rel="noreferrer">Open the workspace</a>
          </div>
        </div>
      </div>

      <div className="adm-toolbar">
        <button className="adm-btn" disabled={!dirty || busy} onClick={save}>{busy ? "Saving…" : "Save for everyone"}</button>
        {dirty && !busy && <button className="adm-mini" onClick={() => setTheme(appearance.userTheme)}>Reset</button>}
        {msg && <span className="adm-ok">{msg}</span>}
      </div>
      {error && <div className="adm-error">{error}</div>}
    </div>
  );
}

const adminCss = `
.adm{min-height:100vh;background:#0a0e12;color:#cdd6e0;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
.adm *{box-sizing:border-box}
.adm-top{display:flex;align-items:center;justify-content:space-between;padding:14px 24px;border-bottom:1px solid #1c2530;background:#0d1217}
.adm-brand{display:flex;align-items:center;gap:10px}
.adm-logo{color:#3ddc84;font-weight:600;font-size:16px;text-decoration:none}
.adm-badge{font-size:11px;color:#ffbd2e;border:1px solid #3a3320;background:rgba(255,189,46,.08);padding:2px 7px;border-radius:5px;text-transform:uppercase;letter-spacing:.08em}
.adm-who{display:flex;align-items:center;gap:16px;font-size:13px;color:#7d8da0}
.adm-link{background:none;border:0;color:#7d8da0;cursor:pointer;font:inherit;font-size:13px;text-decoration:none}
.adm-link:hover{color:#3ddc84}
.adm-tabs{display:flex;gap:4px;padding:0 18px;border-bottom:1px solid #1c2530;background:#0d1217;overflow-x:auto}
.adm-tab{background:none;border:0;border-bottom:2px solid transparent;color:#7d8da0;cursor:pointer;font:inherit;font-size:13px;padding:12px 14px;white-space:nowrap}
.adm-tab:hover{color:#cdd6e0}
.adm-tab.on{color:#3ddc84;border-bottom-color:#3ddc84}
.adm-main{padding:24px;max-width:1100px;margin:0 auto}
.adm-grid{display:flex;flex-direction:column;gap:18px}
.adm-stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
.adm-stat{border:1px solid #1c2530;border-radius:9px;background:#0d1217;padding:16px}
.adm-stat .n{font-size:28px;font-weight:600;color:#eef2f6}
.adm-stat .n.warn{color:#ffbd2e}
.adm-stat .l{font-size:13px;color:#9fb0c3;margin-top:2px}
.adm-stat .sub{font-size:11px;color:#566476;margin-top:4px}
.adm-cols2{display:grid;grid-template-columns:1fr 1fr;gap:18px}
@media(max-width:760px){.adm-cols2{grid-template-columns:1fr}}
.adm-card{border:1px solid #1c2530;border-radius:9px;background:#0d1217;padding:16px}
.adm-card h3{margin:0 0 14px;font-size:13px;font-weight:600;color:#9fb0c3}
.adm-spark{display:flex;align-items:flex-end;gap:3px;height:80px}
.adm-spark .bar{flex:1;background:#1d3a2a;border-radius:2px 2px 0 0;min-height:2px}
.adm-spark .bar:hover{background:#3ddc84}
.adm-bars{display:flex;flex-direction:column;gap:9px}
.adm-bar{display:grid;grid-template-columns:160px 1fr 40px;align-items:center;gap:10px;font-size:12px;color:#9fb0c3}
.adm-bar .track{height:7px;background:#121922;border-radius:4px;overflow:hidden}
.adm-bar .fill{display:block;height:100%;background:#3ddc84;border-radius:4px}
.adm-bar .fill.warn{background:#ffbd2e}
.adm-bar .v{text-align:right;color:#cdd6e0}
.adm-bar.wide{grid-template-columns:1fr 90px 44px}
.adm-bar.wide>span:first-child{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.adm-h2{margin:0;font-size:15px;color:#eef2f6;font-weight:600}
.adm-window{display:inline-flex;gap:2px;margin-left:auto;border:1px solid #1c2530;border-radius:7px;padding:2px;background:#0d1217}
.adm-window-btn{background:none;border:0;color:#7d8da0;cursor:pointer;font:inherit;font-size:12px;padding:4px 10px;border-radius:5px}
.adm-window-btn:hover{color:#cdd6e0}
.adm-window-btn.on{background:#1d3a2a;color:#3ddc84}
.adm-toolbar{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.adm-input{background:#0d1217;border:1px solid #1c2530;border-radius:6px;padding:8px 11px;color:#eef2f6;font:inherit;font-size:13px;outline:none;min-width:220px}
.adm-input:focus{border-color:#3ddc84}
.adm-btn{background:#3ddc84;color:#06140c;border:0;border-radius:6px;padding:8px 14px;font:inherit;font-weight:600;font-size:13px;cursor:pointer}
.adm-check{display:flex;align-items:center;gap:6px;font-size:12px;color:#9fb0c3}
.adm-count{font-size:12px;color:#566476;margin-left:auto}
.adm-tablewrap{padding:0;overflow-x:auto}
.adm-table{width:100%;border-collapse:collapse;font-size:13px}
.adm-table th{text-align:left;padding:11px 14px;color:#566476;font-weight:500;font-size:11px;text-transform:uppercase;letter-spacing:.06em;border-bottom:1px solid #1c2530}
.adm-table td{padding:11px 14px;border-bottom:1px solid #141b22;vertical-align:middle}
.adm-table tr:last-child td{border-bottom:0}
.adm-table tr.suspended{background:rgba(239,68,68,.05)}
.adm-u-name{color:#eef2f6;display:flex;align-items:center;gap:7px}
.adm-u-email{color:#6b7c90;font-size:12px;margin-top:2px}
.adm-muted{color:#7d8da0}
.adm-pill{font-size:10px;padding:2px 7px;border-radius:5px;border:1px solid #2b3744;color:#9fb0c3;text-transform:uppercase;letter-spacing:.05em}
.adm-pill.ok{color:#3ddc84;border-color:#1d3a2a;background:rgba(61,220,132,.07)}
.adm-pill.danger{color:#fca5a5;border-color:#4a2424;background:rgba(239,68,68,.1)}
.adm-pill.admin{color:#ffbd2e;border-color:#3a3320;background:rgba(255,189,46,.08)}
.adm-actions-cell{white-space:nowrap;text-align:right}
.adm-mini{background:transparent;border:1px solid #2b3744;color:#cdd6e0;border-radius:5px;padding:5px 10px;font:inherit;font-size:12px;cursor:pointer;margin-left:6px}
.adm-mini:hover{border-color:#3ddc84;color:#3ddc84}
.adm-mini.danger:hover{border-color:#ef4444;color:#fca5a5}
.adm-mini:disabled{opacity:.5;cursor:default}
.adm-empty{padding:40px;text-align:center;color:#566476}
.adm-empty-sm{padding:18px;text-align:center;color:#566476;font-size:13px}
.adm-error{background:rgba(239,68,68,.12);border:1px solid rgba(239,68,68,.4);color:#fca5a5;padding:10px 13px;border-radius:6px;font-size:13px}
.adm-note{color:#7d8da0;font-size:13px;margin:0}
.adm-plan{background:#0d1217;border:1px solid #2b3744;border-radius:5px;color:#cdd6e0;font:inherit;font-size:12px;padding:4px 6px;cursor:pointer}
.adm-select{width:100%;background:#0a0e12;border:1px solid #2b3744;border-radius:6px;color:#eef2f6;font:inherit;font-size:13px;padding:9px 11px;cursor:pointer}
.adm-select:focus{outline:none;border-color:#3ddc84}
.adm-radios{display:flex;flex-direction:column;gap:8px}
.adm-radio{display:flex;gap:10px;align-items:flex-start;border:1px solid #1c2530;border-radius:7px;padding:10px 12px;cursor:pointer;font-size:13px;color:#cdd6e0;line-height:1.45}
.adm-radio.on{border-color:#3ddc84;background:rgba(61,220,132,.06)}
.adm-radio input{margin-top:3px;accent-color:#3ddc84}
.adm-ok{color:#3ddc84;font-size:13px}
a.adm-mini{text-decoration:none;display:inline-block;margin-left:0}
.adm-plan:disabled{opacity:.5}
.adm-overlay{position:fixed;inset:0;background:rgba(4,8,12,.7);display:flex;align-items:flex-start;justify-content:center;padding:48px 16px;z-index:50;overflow-y:auto}
.adm-modal{background:#0d1217;border:1px solid #1c2530;border-radius:11px;width:100%;max-width:640px}
.adm-modal-head{display:flex;align-items:center;justify-content:space-between;padding:16px 20px;border-bottom:1px solid #1c2530}
.adm-modal-head h2{margin:0;font-size:16px;color:#eef2f6;display:flex;align-items:center}
.adm-modal-body{padding:16px 20px}
.adm-modal-body h3{margin:18px 0 8px;font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:#566476}
.adm-detail-meta{font-size:12px;color:#7d8da0}
.adm-detail-row{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:7px 0;border-bottom:1px solid #141b22;font-size:13px;color:#cdd6e0}
.adm-detail-row code{color:#9fb0c3;background:#121922;padding:1px 5px;border-radius:4px;font-size:12px}
.adm-storage-head{display:flex;align-items:baseline;justify-content:space-between;gap:12px;margin-bottom:10px;font-size:13px;flex-wrap:wrap}
.adm-storage-free{color:#9fb0c3}
.adm-storage-free strong{color:#3ddc84;font-size:18px;font-weight:600}
.adm-storage-free strong.warn{color:#ffbd2e}
.adm-storage-track{height:10px;background:#121922;border-radius:5px;overflow:hidden}
.adm-storage-track .fill{display:block;height:100%;background:#3ddc84;border-radius:5px;transition:width .3s}
.adm-storage-track .fill.warn{background:#ffbd2e}
.adm-storage-legend{display:flex;gap:16px;flex-wrap:wrap;margin-top:12px;font-size:12px;color:#7d8da0}
.adm-storage-legend .dot{display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:6px;vertical-align:middle}
.adm-storage-legend .dot.data{background:#3ddc84}
.adm-storage-legend .dot.index{background:#4a90d9}
.adm-storage-legend .dot.reuse{background:#566476}
`;
