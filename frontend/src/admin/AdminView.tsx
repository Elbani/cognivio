import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  apiRequest,
  type Appearance,
  type AdminAction,
  type AdminOrg,
  type AdminOrgDetail,
  type AdminOrgSso,
  type Role,
  type AdminOverview,
  type AdminUsage,
  type AdminUser,
  type AdminUserUsage,
  type SecurityEvent,
  type UsageTrendPoint,
  type User
} from "../lib/api";
import { ACTION_LABEL, timeAgo } from "../workspace/shared";
import "../styles/workspace.css";

type Tab = "overview" | "usage" | "users" | "orgs" | "appearance" | "security" | "actions";

const TABS: { id: Tab; label: string; icon: string }[] = [
  { id: "overview", label: "Overview", icon: "▦" },
  { id: "usage", label: "Usage", icon: "◫" },
  { id: "users", label: "Users", icon: "◉" },
  { id: "orgs", label: "Organizations", icon: "▤" },
  { id: "appearance", label: "Appearance", icon: "◐" },
  { id: "security", label: "Security", icon: "⛨" },
  { id: "actions", label: "Admin log", icon: "≡" }
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
  // Same look as the workspace: the platform's theme, and this device's light or dark choice.
  const ui = appearance.userTheme;
  const [theme, setTheme] = useState<"dark" | "light">(() => {
    const stored = localStorage.getItem("kb-theme");
    if (stored === "light" || stored === "dark") return stored;
    return ui === "editorial" ? "light" : "dark";
  });
  useEffect(() => { localStorage.setItem("kb-theme", theme); }, [theme]);
  // On a phone the rail is a drawer behind the menu button, as in the workspace.
  const [navOpen, setNavOpen] = useState(false);

  return (
    <div className={navOpen ? "ws adm nav-open" : "ws adm"} data-theme={theme} data-ui={ui}>
      <style>{adminCss}</style>
      <aside className="ws-rail">
        <div className="ws-rail-brand">
          <span className="mk">◆</span>Cognivio
          <button className="ws-iconbtn ws-rail-close" aria-label="Close menu" onClick={() => setNavOpen(false)}>✕</button>
        </div>
        <div className="ws-navlabel">Admin console</div>
        {TABS.map((t) => (
          <button
            key={t.id}
            className={`ws-navitem${tab === t.id ? " active" : ""}`}
            onClick={() => { setTab(t.id); setNavOpen(false); }}
          >
            <span className="ico">{t.icon}</span>{t.label}
          </button>
        ))}

        <div className="ws-rail-spacer" />
        <div className="ws-rail-foot">
          <Link className="ws-navitem" to="/app"><span className="ico">←</span>Back to workspace</Link>
          <button className="ws-navitem" onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}>
            <span className="ico">{theme === "dark" ? "☀︎" : "☾"}</span>{theme === "dark" ? "Light theme" : "Dark theme"}
          </button>
          <button className="ws-navitem" onClick={onLogout}><span className="ico">⏻</span>Sign out</button>
        </div>
      </aside>
      <div className="ws-scrim" onClick={() => setNavOpen(false)} />

      <main className="ws-main">
        <header className="ws-topbar">
          <button className="ws-iconbtn ws-menu-btn" aria-label="Open menu" aria-expanded={navOpen} onClick={() => setNavOpen(true)}>☰</button>
          <div className="ws-topbar-title">
            <h1>{TABS.find((t) => t.id === tab)?.label}</h1>
            <span className="sub">Admin console{user?.email ? ` · ${user.email}` : ""}</span>
          </div>
        </header>
        <div className="ws-content">
          <div className="adm-main">
        {tab === "overview" && <OverviewTab token={token} showPlans={!appearance.selfHosted} />}
        {tab === "usage" && <UsageTab token={token} />}
        {tab === "users" && <UsersTab token={token} />}
        {tab === "orgs" && <OrgsTab token={token} showPlans={!appearance.selfHosted} />}
        {tab === "appearance" && <AppearanceTab token={token} appearance={appearance} onChanged={onAppearanceChanged} />}
        {tab === "security" && <SecurityTab token={token} />}
        {tab === "actions" && <ActionsTab token={token} />}
          </div>
        </div>
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

            <h3>Single sign-on</h3>
            <OrgSsoSection token={token} orgId={orgId} />
          </div>
        )}
      </div>
    </div>
  );
}

function OrgSsoSection({ token, orgId }: { token: string; orgId: string }) {
  const path = `/api/admin/orgs/${orgId}/sso`;
  const { data, error, loading, reload } = useAdmin<AdminOrgSso>(path, token);
  const [form, setForm] = useState<AdminOrgSso | null>(null);
  const [secret, setSecret] = useState("");
  const [domains, setDomains] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  useEffect(() => {
    if (data) { setForm(data); setDomains(data.domains.join(", ")); setSecret(""); }
  }, [data]);

  if (error) return <div className="adm-error">{error}</div>;
  if (loading || !form) return <div className="adm-empty-sm">Loading…</div>;

  async function save() {
    if (!form) return;
    setBusy(true); setMsg(null);
    try {
      await apiRequest<AdminOrgSso>(path, {
        method: "PUT", token,
        body: {
          issuer: form.issuer.trim(),
          clientId: form.clientId.trim(),
          ...(secret ? { clientSecret: secret } : {}),
          domains: domains.split(/[\s,]+/).filter(Boolean),
          enabled: form.enabled,
          required: form.required,
          defaultRole: form.defaultRole
        }
      });
      setMsg({ ok: true, text: "Saved." });
      reload();
    } catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "Could not save." }); }
    finally { setBusy(false); }
  }

  async function remove() {
    if (!window.confirm("Remove single sign-on for this organization? Members who only signed in through it will need a password reset.")) return;
    setBusy(true); setMsg(null);
    try { await apiRequest(path, { method: "DELETE", token }); reload(); }
    catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "Could not remove." }); }
    finally { setBusy(false); }
  }

  const set = (patch: Partial<AdminOrgSso>) => setForm({ ...form, ...patch });

  return (
    <div className="adm-sso">
      <p className="adm-muted">
        OpenID Connect. Register this redirect URL with the identity provider: <code>{form.redirectUri}</code>.
        Only claim email domains this organization owns: its identity provider can sign in as any address in them.
      </p>
      <label>Issuer URL
        <input className="adm-input" value={form.issuer} placeholder="https://accounts.google.com" onChange={(e) => set({ issuer: e.target.value })} />
      </label>
      <label>Client ID
        <input className="adm-input" value={form.clientId} onChange={(e) => set({ clientId: e.target.value })} />
      </label>
      <label>Client secret
        <input className="adm-input" type="password" value={secret} autoComplete="off"
          placeholder={form.hasSecret ? "Stored. Leave empty to keep it." : ""} onChange={(e) => setSecret(e.target.value)} />
      </label>
      <label>Email domains
        <input className="adm-input" value={domains} placeholder="example.com, example.org" onChange={(e) => setDomains(e.target.value)} />
      </label>
      <label>Role for new members
        <select className="adm-plan" value={form.defaultRole} onChange={(e) => set({ defaultRole: e.target.value as Role })}>
          <option value="viewer">viewer</option>
          <option value="editor">editor</option>
          <option value="admin">admin</option>
        </select>
      </label>
      <label className="adm-check">
        <input type="checkbox" checked={form.enabled} onChange={(e) => set({ enabled: e.target.checked })} />
        Turn on single sign-on for these domains
      </label>
      <label className="adm-check">
        <input type="checkbox" checked={form.required} onChange={(e) => set({ required: e.target.checked })} />
        Require it: turn off password login for these domains (platform admins keep theirs)
      </label>
      <div className="adm-sso-actions">
        {msg && <span className={msg.ok ? "adm-muted" : "adm-sso-err"}>{msg.text}</span>}
        {form.configured && <button className="adm-mini danger" disabled={busy} onClick={remove}>Remove</button>}
        <button className="adm-btn" disabled={busy} onClick={save}>{busy ? "Checking the provider…" : "Save"}</button>
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
  { id: "editorial", label: "Editorial", blurb: "White page, Helvetica, black buttons." },
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
.adm{--ok:#15803d;--ok-soft:rgba(21,128,61,.09);--warn:#b45309;--warn-soft:rgba(180,83,9,.1);--danger:#b91c1c;--danger-soft:rgba(185,28,28,.07);--info:#2563eb}
.adm[data-theme="dark"]{--ok:#3ddc84;--ok-soft:rgba(61,220,132,.1);--warn:#ffbd2e;--warn-soft:rgba(255,189,46,.1);--danger:#fca5a5;--danger-soft:rgba(239,68,68,.12);--info:#6ea8fe}
.adm{--r-card:14px;--r-ctl:9px;--r-pill:999px}
.adm[data-ui="editorial"]{--r-card:var(--radius);--r-ctl:var(--radius);--r-pill:3px}
.adm a.ws-navitem{text-decoration:none}
.adm-main{max-width:1100px;margin:0 auto}
.adm-grid{display:flex;flex-direction:column;gap:18px}
.adm-stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:14px}
.adm-stat,.adm-card{background:var(--bg);border:1px solid var(--border);border-radius:var(--r-card);padding:18px}
.adm-stat .n{font-size:30px;font-weight:700;letter-spacing:-.02em;color:var(--text)}
.adm-stat .n.warn{color:var(--warn)}
.adm-stat .l{font-size:13px;color:var(--text-muted);margin-top:2px}
.adm-stat .sub{font-size:12px;color:var(--text-secondary);margin-top:8px}
.adm-cols2{display:grid;grid-template-columns:1fr 1fr;gap:18px}
@media(max-width:760px){.adm-cols2{grid-template-columns:1fr}}
.adm-card h3{margin:0 0 14px;font-size:15px;font-weight:650;color:var(--text)}
.adm-spark{display:flex;align-items:flex-end;gap:3px;height:80px}
.adm-spark .bar{flex:1;background:var(--border-strong);border-radius:2px 2px 0 0;min-height:2px}
.adm-spark .bar:hover{background:var(--accent)}
.adm-bars{display:flex;flex-direction:column;gap:9px}
.adm-bar{display:grid;grid-template-columns:160px 1fr 40px;align-items:center;gap:10px;font-size:13px;color:var(--text-secondary)}
.adm-bar .track{height:7px;background:var(--bg-subtle);border-radius:4px;overflow:hidden}
.adm-bar .fill{display:block;height:100%;background:var(--accent);border-radius:4px}
.adm-bar .fill.warn{background:var(--warn)}
.adm-bar .v{text-align:right;color:var(--text)}
.adm-bar.wide{grid-template-columns:1fr 90px 44px}
.adm-bar.wide>span:first-child{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.adm-h2{margin:0;font-size:16px;color:var(--text);font-weight:650}
.adm-window{display:inline-flex;gap:2px;margin-left:auto;border:1px solid var(--border);border-radius:var(--r-ctl);padding:2px;background:var(--bg)}
.adm .adm-window-btn{background:none;border:0;color:var(--text-secondary);cursor:pointer;font:inherit;font-size:13px;padding:4px 11px;border-radius:var(--r-ctl)}
.adm .adm-window-btn:hover{color:var(--text)}
.adm .adm-window-btn.on{background:var(--accent-soft);color:var(--accent);font-weight:600}
.adm-toolbar{display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.adm-input{background:var(--bg);border:1px solid var(--border);border-radius:var(--r-ctl);padding:9px 12px;color:var(--text);font:inherit;font-size:14px;outline:none;min-width:220px}
.adm-input:focus{border-color:var(--accent)}
.adm-input::placeholder{color:var(--text-muted)}
.adm .adm-btn{background:var(--accent);color:#fff;border:1px solid var(--accent);border-radius:var(--r-ctl);padding:8px 14px;font:inherit;font-weight:600;font-size:14px;cursor:pointer}
.adm .adm-btn:hover{background:var(--accent-hover);border-color:var(--accent-hover)}
.adm[data-ui="editorial"] .adm-btn{color:var(--bg)}
.adm .adm-btn:disabled{opacity:.55;cursor:default}
.adm-check{display:flex;align-items:center;gap:6px;font-size:13px;font-weight:400;color:var(--text-secondary)}
.adm-check input,.adm-radio input{accent-color:var(--accent)}
.adm-count{font-size:13px;color:var(--text-muted);margin-left:auto}
.adm-card.adm-tablewrap{padding:0;overflow-x:auto}
.adm-table{width:100%;border-collapse:collapse;font-size:14px}
.adm-table th{text-align:left;padding:12px 16px;color:var(--text-muted);font-weight:600;font-size:12px;text-transform:uppercase;letter-spacing:.05em;border-bottom:1px solid var(--border)}
.adm-table td{padding:11px 16px;border-bottom:1px solid var(--border);vertical-align:middle;color:var(--text)}
.adm-table tr:last-child td{border-bottom:0}
.adm-table tr.suspended{background:var(--danger-soft)}
.adm-u-name{color:var(--text);font-weight:600;display:flex;align-items:center;gap:7px}
.adm-u-email{color:var(--text-muted);font-size:12px;margin-top:2px}
.adm-muted{color:var(--text-muted)}
.adm-pill{font-size:10px;font-weight:600;padding:2px 8px;border-radius:var(--r-pill);border:1px solid var(--border);color:var(--text-secondary);text-transform:uppercase;letter-spacing:.05em;white-space:nowrap}
.adm-pill.ok{color:var(--ok);border-color:transparent;background:var(--ok-soft)}
.adm-pill.danger{color:var(--danger);border-color:transparent;background:var(--danger-soft)}
.adm-pill.admin{color:var(--warn);border-color:transparent;background:var(--warn-soft)}
.adm-actions-cell{white-space:nowrap;text-align:right}
.adm .adm-mini{background:var(--bg);border:1px solid var(--border);color:var(--text);border-radius:var(--r-ctl);padding:5px 11px;font:inherit;font-size:13px;font-weight:500;cursor:pointer;margin-left:6px}
.adm .adm-mini:hover{border-color:var(--border-strong)}
.adm .adm-mini.danger{color:var(--danger)}
.adm .adm-mini.danger:hover{border-color:var(--danger)}
.adm .adm-mini:disabled{opacity:.5;cursor:default}
.adm a.adm-mini{text-decoration:none;display:inline-block;margin-left:0}
.adm .adm-link{background:none;border:0;color:var(--text-secondary);cursor:pointer;font:inherit;font-size:13px;text-decoration:none;padding:0}
.adm .adm-link:hover{color:var(--text)}
.adm-empty{padding:40px;text-align:center;color:var(--text-muted)}
.adm-empty-sm{padding:18px;text-align:center;color:var(--text-muted);font-size:13px}
.adm-error{background:var(--danger-soft);border:1px solid var(--danger);color:var(--danger);padding:10px 14px;border-radius:var(--r-ctl);font-size:13px}
.adm-note{color:var(--text-secondary);font-size:13px;margin:0;line-height:1.55}
.adm-plan{background:var(--bg);border:1px solid var(--border);border-radius:var(--r-ctl);color:var(--text);font:inherit;font-size:13px;padding:4px 8px;cursor:pointer}
.adm-plan:disabled{opacity:.5}
.adm-select{width:100%;background:var(--bg);border:1px solid var(--border);border-radius:var(--r-ctl);color:var(--text);font:inherit;font-size:14px;padding:9px 12px;cursor:pointer}
.adm-select:focus{outline:none;border-color:var(--accent)}
.adm-radios{display:flex;flex-direction:column;gap:8px}
.adm-radio{display:flex;gap:10px;align-items:flex-start;border:1px solid var(--border);border-radius:var(--r-ctl);padding:11px 13px;cursor:pointer;font-size:14px;font-weight:400;color:var(--text);line-height:1.45}
.adm-radio.on{border-color:var(--accent);background:var(--accent-soft)}
.adm-radio input{margin-top:3px}
.adm-ok{color:var(--ok);font-size:13px}
.adm-overlay{position:fixed;inset:0;background:rgba(0,0,0,.45);display:flex;align-items:flex-start;justify-content:center;padding:48px 16px;z-index:50;overflow-y:auto}
.adm-modal{background:var(--bg);border:1px solid var(--border);border-radius:var(--r-card);width:100%;max-width:640px;box-shadow:var(--shadow-lg);color:var(--text)}
.adm-modal-head{display:flex;align-items:center;justify-content:space-between;padding:16px 22px;border-bottom:1px solid var(--border)}
.adm-modal-head h2{margin:0;font-size:17px;font-weight:650;color:var(--text);display:flex;align-items:center}
.adm-modal-body{padding:16px 22px 22px}
.adm-modal-body h3{margin:20px 0 8px;font-size:11px;text-transform:uppercase;letter-spacing:.08em;color:var(--text-muted);font-weight:600}
.adm-detail-meta{font-size:13px;color:var(--text-muted)}
.adm-detail-row{display:flex;align-items:center;justify-content:space-between;gap:10px;padding:8px 0;border-bottom:1px solid var(--border);font-size:14px;color:var(--text)}
.adm-detail-row code,.adm-sso code{color:var(--text-secondary);background:var(--bg-subtle);padding:1px 6px;border-radius:5px;font-size:12px}
.adm-sso{display:flex;flex-direction:column;gap:12px;font-size:14px;color:var(--text)}
.adm-sso p{margin:0;line-height:1.55;font-size:13px}
.adm-sso code{word-break:break-all}
.adm-sso label{display:flex;flex-direction:column;gap:5px;font-size:12px;font-weight:600;color:var(--text-secondary)}
.adm-sso label.adm-check{flex-direction:row;align-items:center;gap:8px;color:var(--text);font-size:14px;font-weight:400}
.adm-sso .adm-input{min-width:0;width:100%}
.adm-sso-actions{display:flex;align-items:center;justify-content:flex-end;gap:6px}
.adm-sso-err{color:var(--danger);margin-right:auto;font-size:13px}
.adm-storage-head{display:flex;align-items:baseline;justify-content:space-between;gap:12px;margin-bottom:10px;font-size:13px;flex-wrap:wrap;color:var(--text-secondary)}
.adm-storage-free{color:var(--text-secondary)}
.adm-storage-free strong{color:var(--ok);font-size:18px;font-weight:700}
.adm-storage-free strong.warn{color:var(--warn)}
.adm-storage-track{height:10px;background:var(--bg-subtle);border-radius:5px;overflow:hidden}
.adm-storage-track .fill{display:block;height:100%;background:var(--ok);border-radius:5px;transition:width .3s}
.adm-storage-track .fill.warn{background:var(--warn)}
.adm-storage-legend{display:flex;gap:16px;flex-wrap:wrap;margin-top:12px;font-size:12px;color:var(--text-muted)}
.adm-storage-legend .dot{display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:6px;vertical-align:middle}
.adm-storage-legend .dot.data{background:var(--ok)}
.adm-storage-legend .dot.index{background:var(--info)}
.adm-storage-legend .dot.reuse{background:var(--text-muted)}
@media(max-width:860px){
.adm-stats{grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
.adm-cols2{grid-template-columns:minmax(0,1fr)}
.adm-bar{grid-template-columns:minmax(0,110px) 1fr 36px}
.adm-table{min-width:560px}
.ws.adm input:not([type=checkbox]):not([type=radio]),.ws.adm select,.ws.adm textarea{font-size:16px}
.adm .adm-mini{padding:8px 12px}
.adm .adm-link{padding:10px 6px;margin:-10px -6px}
.adm-table th,.adm-table td{padding:10px 12px}
.adm-overlay{padding:12px}
.adm-modal-head{padding:14px 16px}
.adm-modal-body{padding:14px 16px 18px}
}
`;
