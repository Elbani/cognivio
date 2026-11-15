import { useEffect, useState } from "react";
import { apiRequest, MEMORY_TYPES, MEMORY_TYPE_LABELS } from "../lib/api";
import type { Insights, MemoryType } from "../lib/api";
import { ACTION_LABEL, TYPE_COLOR } from "./shared";

export function InsightsView({ token, orgId, onView, onOpen }: {
  token: string;
  orgId: string;
  onView: (v: string) => void;
  onOpen: (id: string) => void;
}) {
  const [data, setData] = useState<Insights | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    apiRequest<Insights>(`/api/orgs/${orgId}/insights`, { token })
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load insights"));
  }, [orgId, token]);

  if (error) return <div className="ws-empty-sm" style={{ color: "#b91c1c" }}>{error}</div>;
  if (!data) return <div className="ws-empty-sm">Loading insights…</div>;

  const { coverage, gaps, activity, docs, retrieval, usefulness } = data;
  const hitPct = retrieval.hitRate === null ? null : Math.round(retrieval.hitRate * 100);
  const maxReads = Math.max(1, ...docs.topRead.map((d) => d.reads));
  const maxType = Math.max(1, ...MEMORY_TYPES.map((t) => coverage.byType[t] ?? 0));
  const mapGap = coverage.teams - coverage.teamsWithMap;
  // Order the action breakdown by volume, biggest first.
  const actions = Object.entries(activity.byAction).sort((a, b) => b[1] - a[1]);
  const maxAction = Math.max(1, ...actions.map(([, n]) => n));

  return (
    <div className="ws-grid" style={{ gap: 22 }}>
      <p style={{ color: "var(--text-secondary)", fontSize: 14, marginTop: 0 }}>
        How much your knowledge base covers, where agents came up empty, and what they've been doing
        across <b>all teams</b> in the last {activity.days} days.
      </p>

      {/* Coverage */}
      <div className="ws-grid ws-stats">
        <div className="ws-card ws-stat" style={{ cursor: "pointer" }} onClick={() => onView("memories")}>
          <div className="n">{coverage.docs}</div>
          <div className="l">docs</div>
          <div className="sub">across {coverage.teams} team{coverage.teams === 1 ? "" : "s"}</div>
        </div>
        <div className="ws-card ws-stat">
          <div className="n" style={{ color: mapGap ? "#b45309" : undefined }}>{coverage.teamsWithMap}/{coverage.teams}</div>
          <div className="l">teams with a map</div>
          <div className="sub">{mapGap ? `${mapGap} missing an entry point` : "every team is oriented"}</div>
        </div>
        <div className="ws-card ws-stat" style={{ cursor: "pointer" }} onClick={() => onView("memories")}>
          <div className="n" style={{ color: coverage.stale ? "#b45309" : undefined }}>{coverage.stale}</div>
          <div className="l">need re-verifying</div>
          <div className="sub">not verified in 90+ days</div>
        </div>
        <div className="ws-card ws-stat" style={{ cursor: "pointer" }} onClick={() => onView("agents")}>
          <div className="n">{activity.activeKeys}</div>
          <div className="l">active agents</div>
          <div className="sub">{activity.reads} reads · {activity.writes} writes</div>
        </div>
        <div className="ws-card ws-stat">
          <div className="n" style={{ color: hitPct !== null && hitPct < 50 ? "#b45309" : undefined }}>
            {hitPct === null ? "-" : `${hitPct}%`}
          </div>
          <div className="l">retrieval hit rate</div>
          <div className="sub">
            {retrieval.lookups === 0
              ? "no lookups yet"
              : `${retrieval.hits}/${retrieval.lookups} lookups found a doc`}
          </div>
        </div>
      </div>

      <div className="ws-grid ws-cols2">
        {/* Knowledge gaps */}
        <div className="ws-card">
          <h3 className="ws-sec-title">Knowledge gaps</h3>
          <p className="agents-note" style={{ marginTop: 0 }}>
            Agents searched for these and the KB had nothing. Near-duplicate queries are grouped. Each is a doc worth writing.
          </p>
          {gaps.length === 0 ? (
            <div className="ws-empty-sm">No empty-handed searches in this window. ✓</div>
          ) : (
            gaps.map((g, i) => (
              <div className="ws-attn-row" key={i} style={{ cursor: "default" }}>
                <span className="t" title={g.examples.join(" · ")}>{g.query}</span>
                <span className="meta" style={{ color: "var(--text-muted)" }}>
                  {g.missCount}× missed{g.examples.length > 1 ? ` · ${g.examples.length} variants` : ""}
                </span>
              </div>
            ))
          )}
        </div>

        {/* Docs by type */}
        <div className="ws-card">
          <h3 className="ws-sec-title">Docs by type</h3>
          <div className="ws-typebars">
            {MEMORY_TYPES.map((t) => (
              <div className="ws-typebar" key={t}>
                <span style={{ display: "flex", alignItems: "center", gap: 7 }}>
                  <span className="ty-dot" style={{ background: TYPE_COLOR[t as MemoryType] }} />
                  {MEMORY_TYPE_LABELS[t]}
                </span>
                <span className="track"><span className="fill" style={{ width: `${((coverage.byType[t] ?? 0) / maxType) * 100}%`, background: TYPE_COLOR[t as MemoryType] }} /></span>
                <span style={{ textAlign: "right", color: "var(--text-secondary)" }}>{coverage.byType[t] ?? 0}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Activity breakdown */}
      <div className="ws-card">
        <h3 className="ws-sec-title">What agents did ({activity.totalEvents} actions)</h3>
        {actions.length === 0 ? (
          <div className="ws-empty-sm">No agent activity in this window. Connect an agent from the Agents tab.</div>
        ) : (
          <div className="ws-typebars">
            {actions.map(([action, n]) => (
              <div className="ws-typebar" key={action}>
                <span>{ACTION_LABEL[action] ?? action}</span>
                <span className="track"><span className="fill" style={{ width: `${(n / maxAction) * 100}%`, background: "var(--accent)" }} /></span>
                <span style={{ textAlign: "right", color: "var(--text-secondary)" }}>{n}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Doc usage: what agents actually pull in full */}
      <div className="ws-grid ws-cols2">
        <div className="ws-card">
          <h3 className="ws-sec-title">Most-read docs</h3>
          <p className="agents-note" style={{ marginTop: 0 }}>
            Docs agents pulled in full (via get_memory) most often: your highest-value pages.
          </p>
          {docs.topRead.length === 0 ? (
            <div className="ws-empty-sm">No docs were read in this window yet.</div>
          ) : (
            <div className="ws-typebars">
              {docs.topRead.map((d) => (
                <div className="ws-typebar" key={d.id}>
                  <span style={{ display: "flex", alignItems: "center", gap: 7, overflow: "hidden" }}>
                    <span className="ty-dot" style={{ background: TYPE_COLOR[d.type] }} />
                    {d.deleted ? (
                      <span style={{ color: "var(--text-muted)" }}>{d.title} <em>(deleted)</em></span>
                    ) : (
                      <button className="ws-linklike" onClick={() => onOpen(d.id)} style={{ textAlign: "left" }}>{d.title}</button>
                    )}
                  </span>
                  <span className="track"><span className="fill" style={{ width: `${(d.reads / maxReads) * 100}%`, background: TYPE_COLOR[d.type] }} /></span>
                  <span style={{ textAlign: "right", color: "var(--text-secondary)" }}>{d.reads}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="ws-card">
          <h3 className="ws-sec-title">Never-read docs {docs.neverReadCount > 0 && <span style={{ color: "#b45309" }}>({docs.neverReadCount})</span>}</h3>
          <p className="agents-note" style={{ marginTop: 0 }}>
            Active docs no agent has ever pulled: dead weight, a wrong/unfindable title, or not surfacing in prime_context. Fix or prune.
          </p>
          {docs.neverRead.length === 0 ? (
            <div className="ws-empty-sm">Every doc has been read at least once. ✓</div>
          ) : (
            docs.neverRead.map((d) => (
              <div className="ws-attn-row" key={d.id} onClick={() => onOpen(d.id)}>
                <span className="ty-dot" style={{ background: TYPE_COLOR[d.type] }} />
                <span className="t">{d.title}</span>
                <span className="meta" style={{ color: "var(--text-muted)" }}>{MEMORY_TYPE_LABELS[d.type]}</span>
              </div>
            ))
          )}
        </div>
      </div>

      {/* Usefulness: what agents told us via mark_helpful */}
      <div className="ws-card">
        <h3 className="ws-sec-title">
          Usefulness
          <span style={{ color: "var(--text-secondary)", fontWeight: 400, fontSize: 13, marginLeft: 8 }}>
            👍 {usefulness.helpful} · 👎 {usefulness.notHelpful} across {usefulness.ratedDocs} rated doc{usefulness.ratedDocs === 1 ? "" : "s"}
          </span>
        </h3>
        <p className="agents-note" style={{ marginTop: 0 }}>
          Docs agents flagged as unhelpful via mark_helpful (more 👎 than 👍): wrong, stale, or noisy. Fix or prune; they're also demoted in prime_context.
        </p>
        {usefulness.lowSignal.length === 0 ? (
          <div className="ws-empty-sm">No docs have net-negative feedback. ✓</div>
        ) : (
          usefulness.lowSignal.map((d) => (
            <div className="ws-attn-row" key={d.id} onClick={() => onOpen(d.id)}>
              <span className="ty-dot" style={{ background: TYPE_COLOR[d.type] }} />
              <span className="t">{d.title}</span>
              <span className="meta" style={{ color: "var(--text-muted)" }}>👍 {d.helpful} · 👎 {d.notHelpful}</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
