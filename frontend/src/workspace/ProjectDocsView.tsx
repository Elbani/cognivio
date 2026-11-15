import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  apiRequest,
  type ProjectDocsCurrent,
  type ProjectDocsVersion,
  type ProjectDocsVersionList,
  type ProjectDocsDiff
} from "../lib/api";
import { timeAgo } from "./shared";

// Human-facing developer documentation: a versioned handbook the connected coding agent
// generates (the platform never calls an LLM). Separate from the agent KB and never used in
// retrieval, this view just renders the current snapshot, lets you browse past versions, and
// diff how the docs evolved.
export function ProjectDocsView({ token, teamId }: { token: string; teamId: string }) {
  const [data, setData] = useState<ProjectDocsCurrent | null>(null);
  const [versions, setVersions] = useState<ProjectDocsVersion[]>([]);
  const [shown, setShown] = useState<ProjectDocsVersion | null>(null);
  const [activeSlug, setActiveSlug] = useState<string | null>(null);
  const [diff, setDiff] = useState<ProjectDocsDiff | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    setLoading(true);
    setError("");
    setData(null); setShown(null); setVersions([]); setDiff(null); setActiveSlug(null);
    apiRequest<ProjectDocsCurrent>(`/api/teams/${teamId}/project-docs`, { token })
      .then((d) => {
        setData(d);
        setShown(d.current);
        setActiveSlug(d.current?.sections[0]?.slug ?? null);
        if (d.hasDocs) {
          apiRequest<ProjectDocsVersionList>(`/api/teams/${teamId}/project-docs/versions`, { token })
            .then((v) => setVersions(v.versions))
            .catch(() => undefined);
        }
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load documentation"))
      .finally(() => setLoading(false));
  }, [teamId, token]);

  async function showVersion(n: number) {
    setDiff(null);
    if (data?.current && n === data.current.version) {
      setShown(data.current);
      setActiveSlug(data.current.sections[0]?.slug ?? null);
      return;
    }
    try {
      const full = await apiRequest<ProjectDocsVersion>(
        `/api/teams/${teamId}/project-docs/versions/${n}`, { token }
      );
      setShown(full);
      setActiveSlug(full.sections[0]?.slug ?? null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load version");
    }
  }

  async function runDiff(from: number, to: number) {
    if (from === to) { setDiff(null); return; }
    try {
      setDiff(await apiRequest<ProjectDocsDiff>(
        `/api/teams/${teamId}/project-docs/diff?from=${from}&to=${to}`, { token }
      ));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not compute diff");
    }
  }

  if (loading) return <div className="ws-empty"><p>Loading documentation…</p></div>;

  if (!data?.hasDocs) {
    return (
      <div style={{ padding: 16, maxWidth: 720 }}>
        {error && <div className="error-banner" style={{ marginBottom: 12 }}>{error}</div>}
        <div className="ws-card" style={{ padding: 24, borderRadius: 10 }}>
          <h2 style={{ marginTop: 0 }}>❏ Project documentation</h2>
          <p>
            A human-readable developer handbook for this project: Overview, Architecture, Local
            Setup, and more. It's <strong>separate from your agent knowledge base</strong> and is
            never used for agent retrieval; it's for people reading the codebase.
          </p>
          <p>
            Cognivio doesn't write it with its own model, your <strong>connected coding agent</strong>{" "}
            generates it. In Claude Code, Cursor, or Codex (connected to this team), just say:
          </p>
          <pre style={{ background: "var(--surface-2, #1113)", padding: "10px 12px", borderRadius: 8, whiteSpace: "pre-wrap" }}>
            Generate our project documentation in Cognivio.
          </pre>
          <p style={{ opacity: 0.8, fontSize: 13 }}>
            The agent calls <code>plan_project_docs</code>, scans the repo, then publishes with{" "}
            <code>write_project_docs</code> (needs a <code>memory:write</code> key). Each publish is
            saved as a new version, so you'll be able to browse and diff how the docs evolve here.
          </p>
        </div>
      </div>
    );
  }

  const current = data.current!;
  const viewing = shown ?? current;
  const activeSection = viewing.sections.find((s) => s.slug === activeSlug) ?? viewing.sections[0];

  return (
    <div style={{ display: "flex", height: "100%", minHeight: 0 }}>
      {/* Sidebar: version control + section TOC */}
      <aside style={{ width: 240, flex: "0 0 240px", borderRight: "1px solid var(--border, #8882)", padding: 12, overflowY: "auto" }}>
        <label style={{ fontSize: 12, opacity: 0.7 }}>Version</label>
        <select
          value={viewing.version}
          onChange={(e) => showVersion(Number(e.target.value))}
          style={{ width: "100%", margin: "4px 0 6px" }}
        >
          {versions.map((v) => (
            <option key={v.version} value={v.version}>
              v{v.version}{v.status === "current" ? " (current)" : ""} · {v.createdAt ? timeAgo(v.createdAt) : ""}
            </option>
          ))}
        </select>
        {viewing.summary && <p style={{ fontSize: 12, opacity: 0.75, margin: "0 0 6px" }}>{viewing.summary}</p>}
        {viewing.status !== "current" && (
          <p style={{ fontSize: 12, color: "var(--warn, #c90)", margin: "0 0 8px" }}>
            Viewing an archived version. v{current.version} is current.
          </p>
        )}

        {versions.length > 1 && (
          <details style={{ margin: "4px 0 10px" }}>
            <summary style={{ cursor: "pointer", fontSize: 13 }}>Compare versions</summary>
            <CompareControls versions={versions} current={viewing.version} onCompare={runDiff} />
          </details>
        )}

        <div style={{ fontSize: 12, opacity: 0.7, margin: "8px 0 4px" }}>Sections</div>
        {viewing.sections.map((s) => (
          <button
            key={s.slug}
            className={`ws-navitem${!diff && s.slug === activeSection?.slug ? " active" : ""}`}
            style={{ width: "100%", textAlign: "left" }}
            onClick={() => { setDiff(null); setActiveSlug(s.slug); }}
          >
            {s.title}
          </button>
        ))}
      </aside>

      {/* Main: either a section, or a diff */}
      <div style={{ flex: 1, minWidth: 0, overflowY: "auto", padding: "16px 24px" }}>
        {error && <div className="error-banner" style={{ marginBottom: 12 }}>{error}</div>}
        {diff ? (
          <DiffPanel diff={diff} onClose={() => setDiff(null)} />
        ) : activeSection ? (
          <article className="ws-preview preview">
            <ReactMarkdown remarkPlugins={[remarkGfm]} urlTransform={(u) => (/^(https?:|mailto:|\/)/i.test(u) ? u : "")}>
              {`# ${activeSection.title}\n\n${activeSection.content ?? ""}`}
            </ReactMarkdown>
          </article>
        ) : (
          <p style={{ opacity: 0.7 }}>This version has no sections.</p>
        )}
      </div>
    </div>
  );
}

function CompareControls({ versions, current, onCompare }: {
  versions: ProjectDocsVersion[];
  current: number;
  onCompare: (from: number, to: number) => void;
}) {
  const sorted = versions.map((v) => v.version);
  const [from, setFrom] = useState<number>(sorted[1] ?? sorted[0]);
  const [to, setTo] = useState<number>(current);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 6 }}>
      <label style={{ fontSize: 12 }}>From
        <select value={from} onChange={(e) => setFrom(Number(e.target.value))} style={{ width: "100%" }}>
          {sorted.map((v) => <option key={v} value={v}>v{v}</option>)}
        </select>
      </label>
      <label style={{ fontSize: 12 }}>To
        <select value={to} onChange={(e) => setTo(Number(e.target.value))} style={{ width: "100%" }}>
          {sorted.map((v) => <option key={v} value={v}>v{v}</option>)}
        </select>
      </label>
      <button className="ws-btn sm" onClick={() => onCompare(from, to)}>Compare</button>
    </div>
  );
}

const DIFF_BADGE: Record<string, { label: string; color: string }> = {
  added: { label: "added", color: "#3a7" },
  removed: { label: "removed", color: "#c55" },
  changed: { label: "changed", color: "#c90" },
  unchanged: { label: "unchanged", color: "#8888" }
};

function DiffPanel({ diff, onClose }: { diff: ProjectDocsDiff; onClose: () => void }) {
  const changed = diff.sections.filter((s) => s.status !== "unchanged");
  return (
    <div>
      <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 12 }}>
        <h2 style={{ margin: 0 }}>Changes: v{diff.from} → v{diff.to}</h2>
        <button className="ws-btn sm" onClick={onClose}>Close diff</button>
      </div>
      {changed.length === 0 && <p style={{ opacity: 0.7 }}>No section changed between these versions.</p>}
      {diff.sections.map((s) => {
        const badge = DIFF_BADGE[s.status];
        return (
          <div key={s.slug} style={{ marginBottom: 16 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <strong>{s.title ?? s.slug}</strong>
              <span style={{ fontSize: 11, color: badge.color, border: `1px solid ${badge.color}`, borderRadius: 4, padding: "0 5px" }}>
                {badge.label}
              </span>
            </div>
            {s.diff && (
              <pre style={{ fontSize: 12, lineHeight: 1.5, overflowX: "auto", background: "var(--surface-2, #1113)", padding: "8px 10px", borderRadius: 6, marginTop: 6 }}>
                {s.diff.split("\n").map((line, i) => {
                  const color = line.startsWith("+") && !line.startsWith("+++")
                    ? "#3a7"
                    : line.startsWith("-") && !line.startsWith("---")
                      ? "#c55"
                      : line.startsWith("@@")
                        ? "#69f"
                        : undefined;
                  return <div key={i} style={{ color }}>{line || " "}</div>;
                })}
              </pre>
            )}
          </div>
        );
      })}
    </div>
  );
}
