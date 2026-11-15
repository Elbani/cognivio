import { useMemo, useState } from "react";
import type { Folder, MemoryListItem, MemoryStatus, MemoryType } from "../lib/api";
import { MEMORY_TYPES, MEMORY_TYPE_LABELS } from "../lib/api";
import { freshness, TYPE_COLOR, TYPE_GLYPH } from "./shared";

type Props = {
  memories: MemoryListItem[];
  folders: Folder[];
  onOpen: (id: string) => void;
};

export function MemoriesBrowser({ memories, folders, onOpen }: Props) {
  const [q, setQ] = useState("");
  const [type, setType] = useState<MemoryType | "all">("all");
  const [status, setStatus] = useState<MemoryStatus | "all">("all");
  const [project, setProject] = useState<string>("all");
  const [staleOnly, setStaleOnly] = useState(false);
  const [group, setGroup] = useState(true);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  const staleCount = useMemo(() => memories.filter((m) => freshness(m.lastVerifiedAt).stale).length, [memories]);

  const toggleGroup = (t: string) =>
    setCollapsed((prev) => {
      const next = new Set(prev);
      next.has(t) ? next.delete(t) : next.add(t);
      return next;
    });

  const filtered = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return memories.filter((m) => {
      if (type !== "all" && m.type !== type) return false;
      if (status !== "all" && m.status !== status) return false;
      if (project !== "all" && (m.folderId ?? "none") !== project) return false;
      if (staleOnly && !freshness(m.lastVerifiedAt).stale) return false;
      if (needle && !(m.title.toLowerCase().includes(needle) || m.tags.some((t) => t.includes(needle)))) return false;
      return true;
    });
  }, [memories, q, type, status, project, staleOnly]);

  const grouped = useMemo(() => {
    if (!group) return null;
    const map = new Map<MemoryType, MemoryListItem[]>();
    for (const m of filtered) {
      if (!map.has(m.type)) map.set(m.type, []);
      map.get(m.type)!.push(m);
    }
    return MEMORY_TYPES.map((t) => [t, map.get(t as MemoryType) ?? []] as const).filter(([, arr]) => arr.length);
  }, [filtered, group]);

  const row = (m: MemoryListItem) => {
    const f = freshness(m.lastVerifiedAt);
    return (
      <button className="ws-mrow" key={m.id} onClick={() => onOpen(m.id)}>
        <span className="ty-dot" style={{ background: TYPE_COLOR[m.type], width: 11, height: 11 }} title={m.type} />
        <span>
          <div className="ti">{m.title}</div>
          {m.tags.length > 0 && <div className="tags">{m.tags.map((t) => `#${t}`).join("  ")}</div>}
        </span>
        <span className="meta">
          {m.status !== "active" && <span className={`st-badge st-${m.status}`}>{m.status}</span>}
          {m.source === "agent" && <span className="src-badge">agent</span>}
          {f.stale
            ? <span className="stale-pill" title={`Last verified ${f.label}`}>⚠ stale</span>
            : <span className="fresh-ok">{f.label}</span>}
        </span>
      </button>
    );
  };

  return (
    <div>
      <div className="ws-filters">
        <span className="ws-search"><input placeholder="Search docs…" value={q} onChange={(e) => setQ(e.target.value)} /></span>
        <select className="ws-select" value={status} onChange={(e) => setStatus(e.target.value as MemoryStatus | "all")}>
          <option value="all">Any status</option>
          <option value="active">Active</option>
          <option value="draft">Draft</option>
          <option value="deprecated">Deprecated</option>
        </select>
        <select className="ws-select" value={project} onChange={(e) => setProject(e.target.value)}>
          <option value="all">Any project</option>
          <option value="none">No project</option>
          {folders.map((f) => <option key={f.id} value={f.id}>{f.name}</option>)}
        </select>
        <button
          className={`ws-btn sm${staleOnly ? " primary" : ""}`}
          onClick={() => setStaleOnly((s) => !s)}
          disabled={staleCount === 0 && !staleOnly}
          title="Show only docs that need re-verifying"
        >
          ⚠ Stale{staleCount > 0 ? ` · ${staleCount}` : ""}
        </button>
        <button className={`ws-btn sm${group ? " primary" : ""}`} onClick={() => setGroup((g) => !g)}>Group by type</button>
      </div>

      <div className="ws-typechips">
        <button className={`ws-typechip${type === "all" ? " active" : ""}`} onClick={() => setType("all")}>All</button>
        {MEMORY_TYPES.map((t) => (
          <button key={t} className={`ws-typechip${type === t ? " active" : ""}`} onClick={() => setType(t as MemoryType)}>
            <span className="ty-dot" style={{ background: TYPE_COLOR[t as MemoryType] }} />{MEMORY_TYPE_LABELS[t]}
          </button>
        ))}
      </div>

      {filtered.length === 0 ? (
        <div className="ws-empty-sm">No docs match these filters.</div>
      ) : grouped ? (
        grouped.map(([t, arr]) => {
          const isCollapsed = collapsed.has(t);
          return (
            <div key={t} style={{ marginBottom: 18 }}>
              <button className="ws-grouphdr" aria-expanded={!isCollapsed} onClick={() => toggleGroup(t)}>
                <span className={`ws-grouphdr-chev${isCollapsed ? " collapsed" : ""}`}>▾</span>
                <span style={{ color: TYPE_COLOR[t as MemoryType] }}>{TYPE_GLYPH[t as MemoryType]}</span>
                {MEMORY_TYPE_LABELS[t]} · {arr.length}
              </button>
              {!isCollapsed && <div className="ws-mlist">{arr.map(row)}</div>}
            </div>
          );
        })
      ) : (
        <div className="ws-mlist">{filtered.map(row)}</div>
      )}
    </div>
  );
}
