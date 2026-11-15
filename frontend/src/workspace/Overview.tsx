import { useMemo, useState } from "react";
import type { AuditEntry, MemoryListItem, MemoryType } from "../lib/api";
import { MEMORY_TYPES, MEMORY_TYPE_LABELS } from "../lib/api";
import { ACTION_LABEL, freshness, timeAgo, TYPE_COLOR } from "./shared";

type Props = {
  loading: boolean;
  memories: MemoryListItem[];
  activity: AuditEntry[];
  hasMap: boolean;
  canEdit: boolean;
  onOpen: (id: string) => void;
  onView: (v: string) => void;
  onCreate: (type: MemoryType) => void;
  onLoadExamples: () => void;
  onConnect: () => void;
};

export function Overview({ loading, memories, activity, hasMap, canEdit, onOpen, onView, onCreate, onLoadExamples, onConnect }: Props) {
  const [checklistDismissed, setChecklistDismissed] = useState(
    () => Boolean(localStorage.getItem("ac-checklist-done"))
  );

  const checklist = useMemo(() => {
    const items = [
      { key: "map", label: "Create your Project Map", done: hasMap, cta: "Create", act: () => onCreate("map") },
      { key: "doc", label: "Write your first doc", done: memories.some((m) => m.type !== "map"), cta: "New doc", act: () => onCreate("note") },
      { key: "agent", label: "Connect an agent", done: activity.length > 0, cta: "Connect", act: onConnect }
    ];
    return { items, doneCount: items.filter((i) => i.done).length };
  }, [memories, activity, hasMap, onCreate, onView]);

  const showChecklist = canEdit && !checklistDismissed && checklist.doneCount < checklist.items.length;
  function dismissChecklist() { localStorage.setItem("ac-checklist-done", "1"); setChecklistDismissed(true); }

  const stats = useMemo(() => {
    const byType: Record<string, number> = {};
    let active = 0, draft = 0, deprecated = 0, stale = 0, agentAuthored = 0;
    const linkedTo = new Set<string>();
    for (const m of memories) {
      byType[m.type] = (byType[m.type] ?? 0) + 1;
      if (m.status === "active") active++;
      else if (m.status === "draft") draft++;
      else deprecated++;
      if (freshness(m.lastVerifiedAt).stale) stale++;
      if (m.source === "agent") agentAuthored++;
      for (const id of m.linkedMemoryIds) linkedTo.add(id);
    }
    const orphans = memories.filter((m) => m.linkedMemoryIds.length === 0 && !linkedTo.has(m.id));
    const unresolved = memories.filter((m) => m.unresolvedLinks.length > 0);
    const staleList = memories
      .filter((m) => freshness(m.lastVerifiedAt).stale)
      .sort((a, b) => (freshness(b.lastVerifiedAt).days ?? 1e9) - (freshness(a.lastVerifiedAt).days ?? 1e9));
    return { byType, active, draft, deprecated, stale, agentAuthored, orphans, unresolved, staleList };
  }, [memories]);

  const maxType = Math.max(1, ...MEMORY_TYPES.map((t) => stats.byType[t] ?? 0));
  const reads7d = activity.filter((a) => a.action !== "memory.create").length;
  const writes = activity.filter((a) => a.action === "memory.create").length;

  // While the team's data is loading, render a skeleton that mirrors the dashboard
  // layout, never the empty "Getting started" / "No project map" states, which would
  // flash for unconfigured-looking workspaces that are actually just mid-fetch.
  if (loading) {
    return (
      <div className="ws-grid" style={{ gap: 22 }} aria-busy="true">
        <div className="ws-grid ws-stats">
          {[0, 1, 2, 3].map((i) => (
            <div className="ws-card ws-stat" key={i}>
              <div className="sk sk-n" />
              <div className="sk sk-l" />
              <div className="sk sk-sub" />
            </div>
          ))}
        </div>
        <div className="ws-grid ws-cols2">
          {[0, 1].map((col) => (
            <div className="ws-card" key={col}>
              <div className="sk sk-title" />
              {[0, 1, 2, 3].map((i) => <div className="sk sk-row" key={i} />)}
            </div>
          ))}
        </div>
        <div className="ws-card">
          <div className="sk sk-title" />
          {[0, 1, 2].map((i) => <div className="sk sk-row" key={i} />)}
        </div>
      </div>
    );
  }

  return (
    <div className="ws-grid" style={{ gap: 22 }}>
      {showChecklist && (
        <div className="ws-card ac-checklist">
          <div className="hd">
            <h3>Getting started</h3>
            <span className="prog">{checklist.doneCount} / {checklist.items.length}</span>
            <button className="x" title="Dismiss" onClick={dismissChecklist}>×</button>
          </div>
          {checklist.items.map((i) => (
            <div className={`ac-citem${i.done ? " done" : ""}`} key={i.key}>
              <span className={`ac-check${i.done ? " done" : ""}`}>{i.done ? "✓" : ""}</span>
              <span className="lbl">{i.label}</span>
              {!i.done && <button className="ws-btn sm act" onClick={i.act}>{i.cta}</button>}
            </div>
          ))}
        </div>
      )}

      {!hasMap && (
        <div className="ws-card" style={{ borderColor: "var(--accent)", background: "var(--accent-soft)" }}>
          <strong>No project map yet.</strong>{" "}
          <span style={{ color: "var(--text-secondary)" }}>
            The project map is the first thing your agents read. Create one to orient them.
          </span>
          {canEdit && (
            <span style={{ display: "inline-flex", gap: 8, marginLeft: 8 }}>
              <button className="ws-btn sm primary" onClick={() => onView("map")}>Create the project map</button>
              {memories.length === 0 && <button className="ws-btn sm" onClick={onLoadExamples}>Load example docs</button>}
            </span>
          )}
        </div>
      )}

      <div className="ws-grid ws-stats">
        <div className="ws-card ws-stat">
          <div className="n">{memories.length}</div>
          <div className="l">docs</div>
          <div className="sub">{stats.active} active · {stats.draft} draft · {stats.deprecated} deprecated</div>
        </div>
        <div className="ws-card ws-stat" style={{ cursor: "pointer" }} onClick={() => onView("memories")}>
          <div className="n" style={{ color: stats.stale ? "#b45309" : undefined }}>{stats.stale}</div>
          <div className="l">need re-verifying</div>
          <div className="sub">not verified in 90+ days</div>
        </div>
        <div className="ws-card ws-stat">
          <div className="n" style={{ color: (stats.unresolved.length || stats.orphans.length) ? "#b45309" : undefined }}>
            {stats.unresolved.length + stats.orphans.length}
          </div>
          <div className="l">graph issues</div>
          <div className="sub">{stats.unresolved.length} unresolved links · {stats.orphans.length} orphaned</div>
        </div>
        <div className="ws-card ws-stat" style={{ cursor: "pointer" }} onClick={() => onView("agents")}>
          <div className="n">{reads7d}</div>
          <div className="l">agent reads (recent)</div>
          <div className="sub">{writes} agent writes · {stats.agentAuthored} agent-authored</div>
        </div>
      </div>

      <div className="ws-grid ws-cols2">
        <div className="ws-card">
          <h3 className="ws-sec-title">Docs by type</h3>
          <div className="ws-typebars">
            {MEMORY_TYPES.map((t) => (
              <div className="ws-typebar" key={t}>
                <span style={{ display: "flex", alignItems: "center", gap: 7 }}>
                  <span className="ty-dot" style={{ background: TYPE_COLOR[t as MemoryType] }} />
                  {MEMORY_TYPE_LABELS[t]}
                </span>
                <span className="track"><span className="fill" style={{ width: `${((stats.byType[t] ?? 0) / maxType) * 100}%`, background: TYPE_COLOR[t as MemoryType] }} /></span>
                <span style={{ textAlign: "right", color: "var(--text-secondary)" }}>{stats.byType[t] ?? 0}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="ws-card">
          <h3 className="ws-sec-title">Needs attention</h3>
          {stats.staleList.length === 0 && stats.unresolved.length === 0 && (
            <div className="ws-empty-sm">Everything looks fresh and well-linked. ✓</div>
          )}
          {stats.staleList.slice(0, 4).map((m) => (
            <div className="ws-attn-row" key={m.id} onClick={() => onOpen(m.id)}>
              <span className="ty-dot" style={{ background: TYPE_COLOR[m.type] }} />
              <span className="t">{m.title}</span>
              <span className="meta fresh-stale">{freshness(m.lastVerifiedAt).label}</span>
            </div>
          ))}
          {stats.unresolved.slice(0, 3).map((m) => (
            <div className="ws-attn-row" key={"u" + m.id} onClick={() => onOpen(m.id)}>
              <span className="ty-dot" style={{ background: TYPE_COLOR[m.type] }} />
              <span className="t">{m.title}</span>
              <span className="meta" style={{ color: "var(--text-muted)" }}>{m.unresolvedLinks.length} broken link{m.unresolvedLinks.length > 1 ? "s" : ""}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="ws-card">
        <h3 className="ws-sec-title">Recent agent activity</h3>
        {activity.length === 0 && <div className="ws-empty-sm">No agent activity yet. Connect an agent from the Agents tab.</div>}
        {activity.slice(0, 8).map((a) => (
          <div className="ws-feed-item" key={a.id}>
            <span className="dot" />
            <span className="who">{a.keyName ?? "agent"}</span>
            <span className="act">
              {ACTION_LABEL[a.action] ?? a.action}
              {a.query ? `, “${a.query}”` : ""}
            </span>
            <span className="when">{timeAgo(a.at)}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
