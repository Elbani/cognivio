import { useEffect, useState } from "react";
import { apiRequest } from "../lib/api";
import { timeAgo } from "./shared";

type RepoStatus = {
  connected: boolean;
  provider?: "github" | "gitlab";
  projectPath?: string;
  baseUrl?: string | null;
  defaultBranch?: string | null;
  connectedAt?: string;
};
type Coverage = {
  fileCount: number;
  documentedCount: number;
  byDir: { dir: string; total: number; documented: number }[];
  undocumentedSample: string[];
  provider: string;
  projectPath: string;
  defaultBranch: string | null;
  drifted: { id: string; title: string; changedFiles: { file: string; url: string; changedAt: string }[] }[];
};

export function RepoView({ token, teamId, canManage, onOpen }: {
  token: string;
  teamId: string;
  canManage: boolean;
  onOpen: (id: string) => void;
}) {
  const [status, setStatus] = useState<RepoStatus | null>(null);
  const [cov, setCov] = useState<Coverage | null>(null);
  const [covLoading, setCovLoading] = useState(false);
  const [error, setError] = useState("");

  // connect form
  const [provider, setProvider] = useState<"github" | "gitlab">("gitlab");
  const [projectPath, setProjectPath] = useState("");
  const [tokenInput, setTokenInput] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setCov(null); setError("");
    apiRequest<RepoStatus>(`/api/teams/${teamId}/repo`, { token })
      .then(setStatus)
      .catch(() => setStatus({ connected: false }));
  }, [teamId, token]);

  async function loadCoverage() {
    setCovLoading(true); setError("");
    try {
      setCov(await apiRequest<Coverage>(`/api/teams/${teamId}/repo/coverage`, { token }));
    } catch (e) { setError(e instanceof Error ? e.message : "Could not load coverage"); }
    finally { setCovLoading(false); }
  }

  useEffect(() => { if (status?.connected) loadCoverage(); /* eslint-disable-next-line */ }, [status?.connected, teamId]);

  async function connect() {
    setBusy(true); setError("");
    try {
      const body: Record<string, unknown> = { provider, projectPath: projectPath.trim(), token: tokenInput.trim() };
      if (baseUrl.trim()) body.baseUrl = baseUrl.trim();
      const s = await apiRequest<RepoStatus>(`/api/teams/${teamId}/repo`, { method: "PUT", token, body });
      setTokenInput(""); setStatus(s);
    } catch (e) { setError(e instanceof Error ? e.message : "Could not connect"); }
    finally { setBusy(false); }
  }

  async function disconnect() {
    if (!confirm("Disconnect this repo? The stored token is deleted.")) return;
    await apiRequest(`/api/teams/${teamId}/repo`, { method: "DELETE", token }).catch(() => undefined);
    setStatus({ connected: false }); setCov(null);
  }

  if (status === null) return <div className="ws-empty-sm">Loading…</div>;

  if (!status.connected) {
    return (
      <div className="ws-grid" style={{ gap: 18, maxWidth: 560 }}>
        <p style={{ color: "var(--text-secondary)", fontSize: 14, marginTop: 0 }}>
          Connect this team's Git repo (read-only) to see <b>which parts of the codebase have no docs</b> and detect
          docs whose referenced code changed, server-side, so it works for Remote MCP too.
        </p>
        {!canManage ? (
          <div className="ws-empty-sm">Only org owners/admins can connect a repo.</div>
        ) : (
          <div className="ws-card" style={{ display: "grid", gap: 10 }}>
            <label className="repo-field"><span>Provider</span>
              <select className="ws-select" value={provider} onChange={(e) => setProvider(e.target.value as "github" | "gitlab")}>
                <option value="gitlab">GitLab</option>
                <option value="github">GitHub</option>
              </select>
            </label>
            <label className="repo-field"><span>Project path</span>
              <input className="ws-input" placeholder={provider === "github" ? "owner/repo" : "group/project"} value={projectPath} onChange={(e) => setProjectPath(e.target.value)} />
            </label>
            <label className="repo-field"><span>Access token</span>
              <input className="ws-input" type="password" placeholder="read-only PAT" value={tokenInput} onChange={(e) => setTokenInput(e.target.value)} />
            </label>
            <label className="repo-field"><span>Base URL <em>(self-hosted only)</em></span>
              <input className="ws-input" placeholder={provider === "github" ? "https://api.github.com" : "https://gitlab.com"} value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
            </label>
            {error && <div className="ws-empty-sm" style={{ color: "#b91c1c" }}>{error}</div>}
            <div><button className="ws-btn primary" disabled={busy || !projectPath.trim() || !tokenInput.trim()} onClick={connect}>{busy ? "Connecting…" : "Connect repo"}</button></div>
            <p className="connect-note">A <b>read-only</b> token is enough, but it must allow the REST API: <b>GitLab</b> needs <code>read_api</code> (not <code>read_repository</code>, which is Git-clone only); <b>GitHub</b> needs <code>repo</code> (classic) or <code>Contents: read</code> + <code>Metadata: read</code> (fine-grained). It's stored to call the API and never shown again.</p>
          </div>
        )}
      </div>
    );
  }

  const pct = cov && cov.fileCount ? Math.round((cov.documentedCount / cov.fileCount) * 100) : 0;

  return (
    <div className="ws-grid" style={{ gap: 22 }}>
      <div className="ws-card agents-connect">
        <div className="ac-left">
          <strong>{status.provider} · {status.projectPath}</strong>
          <span>branch <code>{status.defaultBranch}</code>{status.connectedAt ? ` · connected ${timeAgo(status.connectedAt)}` : ""}</span>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button className="ws-btn sm" disabled={covLoading} onClick={loadCoverage}>{covLoading ? "Scanning…" : "Refresh"}</button>
          {canManage && <button className="ws-btn sm danger" onClick={disconnect}>Disconnect</button>}
        </div>
      </div>

      <p style={{ color: "var(--text-secondary)", fontSize: 14, margin: 0 }}>
        This compares your repo against your docs. A file counts as <b>covered</b> when a doc cites its exact path
        (e.g. <code>backend/app/main.py</code>), so this surfaces code agents work in that nobody has written up.
        <b> Drifted docs</b> reference a file whose latest commit is newer than the doc's last <b>Verify</b>, a sign the
        doc may be out of date. Low coverage is normal: treat the per-directory breakdown as a map of where a doc would
        help most, not a score to max out.
      </p>

      {error && <div className="ws-empty-sm" style={{ color: "#b91c1c" }}>{error}</div>}
      {covLoading && !cov && <div className="ws-empty-sm">Scanning the repo…</div>}

      {cov && (
        <>
          <div className="ws-grid ws-stats">
            <div className="ws-card ws-stat" title="Total files on the default branch of the connected repo.">
              <div className="n">{cov.fileCount}</div><div className="l">files in repo</div>
            </div>
            <div className="ws-card ws-stat" title="Files mentioned by their exact path in at least one doc. This is the coverage signal.">
              <div className="n">{cov.documentedCount}</div><div className="l">files cited by a doc</div><div className="sub">{pct}% of files covered</div>
            </div>
            <div className="ws-card ws-stat" title="Docs that cite a file whose latest commit is newer than the doc's last Verify, likely out of date.">
              <div className="n" style={{ color: cov.drifted.length ? "#b45309" : undefined }}>{cov.drifted.length}</div><div className="l">drifted docs</div><div className="sub">cited code changed after verify</div>
            </div>
          </div>

          <div className="ws-grid ws-cols2">
            <div className="ws-card">
              <h3 className="ws-sec-title">Coverage by directory</h3>
              <p className="agents-note" style={{ marginTop: 0 }}>Least-documented first: areas agents work in but nobody has written up.</p>
              <div className="ws-typebars">
                {cov.byDir.slice(0, 12).map((d) => (
                  <div className="ws-typebar" key={d.dir}>
                    <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{d.dir}</span>
                    <span className="track"><span className="fill" style={{ width: `${(d.documented / d.total) * 100}%`, background: d.documented === 0 ? "#b45309" : "var(--accent)" }} /></span>
                    <span style={{ textAlign: "right", color: "var(--text-secondary)" }}>{d.documented}/{d.total}</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="ws-card">
              <h3 className="ws-sec-title">Drifted docs</h3>
              {cov.drifted.length === 0 ? (
                <div className="ws-empty-sm">No drift: every cited file is older than its doc's last verify. ✓</div>
              ) : (
                cov.drifted.map((d) => (
                  <div className="ws-attn-row" key={d.id} onClick={() => onOpen(d.id)}>
                    <span className="t">{d.title}</span>
                    <span className="meta" style={{ color: "var(--text-muted)" }}>{d.changedFiles.length} file{d.changedFiles.length > 1 ? "s" : ""} changed</span>
                  </div>
                ))
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
