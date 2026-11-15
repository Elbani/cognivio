import { useEffect, useState } from "react";
import { apiRequest, Memory } from "../lib/api";
import { timeAgo } from "./shared";

type VersionItem = {
  id: string;
  title: string;
  type: string;
  chars: number;
  updatedAt: string | null;
  supersededAt: string | null;
  source: string;
  keyName: string | null;
};
type VersionFull = VersionItem & { content: string };

// Minimal LCS line diff: rows are unchanged / removed-from-old / added-in-new.
function lineDiff(oldText: string, newText: string): { t: "same" | "del" | "add"; text: string }[] {
  const A = oldText.split("\n"), B = newText.split("\n");
  const n = A.length, m = B.length;
  const dp: number[][] = Array.from({ length: n + 1 }, () => new Array(m + 1).fill(0));
  for (let i = n - 1; i >= 0; i--)
    for (let j = m - 1; j >= 0; j--)
      dp[i][j] = A[i] === B[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  const rows: { t: "same" | "del" | "add"; text: string }[] = [];
  let i = 0, j = 0;
  while (i < n && j < m) {
    if (A[i] === B[j]) { rows.push({ t: "same", text: A[i] }); i++; j++; }
    else if (dp[i + 1][j] >= dp[i][j + 1]) { rows.push({ t: "del", text: A[i] }); i++; }
    else { rows.push({ t: "add", text: B[j] }); j++; }
  }
  while (i < n) rows.push({ t: "del", text: A[i++] });
  while (j < m) rows.push({ t: "add", text: B[j++] });
  return rows;
}

function who(v: VersionItem): string {
  if (v.source === "agent") return `agent${v.keyName ? ` · ${v.keyName}` : ""}`;
  return "manual edit";
}

export function VersionHistory({ token, memoryId, currentContent, canEdit, onRestored, onClose }: {
  token: string;
  memoryId: string;
  currentContent: string;
  canEdit: boolean;
  onRestored: (m: Memory) => void;
  onClose: () => void;
}) {
  const [versions, setVersions] = useState<VersionItem[] | null>(null);
  const [selected, setSelected] = useState<VersionFull | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    apiRequest<{ versions: VersionItem[] }>(`/api/memories/${memoryId}/versions`, { token })
      .then((r) => setVersions(r.versions))
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load history"));
  }, [memoryId, token]);

  async function pick(v: VersionItem) {
    setError("");
    try {
      const full = await apiRequest<VersionFull>(`/api/memories/${memoryId}/versions/${v.id}`, { token });
      setSelected(full);
    } catch (e) { setError(e instanceof Error ? e.message : "Could not load version"); }
  }

  async function restore() {
    if (!selected) return;
    setBusy(true); setError("");
    try {
      const m = await apiRequest<Memory>(`/api/memories/${memoryId}/versions/${selected.id}/restore`, { method: "POST", token });
      onRestored(m);
      onClose();
    } catch (e) { setError(e instanceof Error ? e.message : "Restore failed"); setBusy(false); }
  }

  const diff = selected ? lineDiff(selected.content, currentContent) : [];

  return (
    <div className="ac-overlay" onClick={onClose}>
      <div className="ac-modal vh-modal" onClick={(e) => e.stopPropagation()}>
        <div className="ac-modal-head">
          <h2>Version history</h2>
          <p>Every edit, yours or an agent's, is snapshotted here. Pick a revision to see what changed, then restore it.</p>
        </div>
        <div className="ac-modal-body vh-body">
          {error && <div className="ws-empty-sm" style={{ color: "#b91c1c" }}>{error}</div>}
          {versions === null ? (
            <div className="ws-empty-sm">Loading…</div>
          ) : versions.length === 0 ? (
            <div className="ws-empty-sm">No prior revisions yet, history starts at the next edit.</div>
          ) : (
            <div className="vh-cols">
              <div className="vh-list">
                {versions.map((v) => (
                  <button key={v.id} className={`vh-item${selected?.id === v.id ? " active" : ""}`} onClick={() => pick(v)}>
                    <span className="vh-when">{v.supersededAt ? timeAgo(v.supersededAt) : "-"}</span>
                    <span className="vh-who">{who(v)}{v.source === "agent" ? " ✦" : ""}</span>
                    <span className="vh-chars">{v.chars} chars</span>
                  </button>
                ))}
              </div>
              <div className="vh-diff">
                {!selected ? (
                  <div className="ws-empty-sm">Select a revision to compare it with the current doc.</div>
                ) : (
                  <>
                    <div className="vh-diff-head">
                      <span><span className="vh-leg del">−</span> this revision &nbsp; <span className="vh-leg add">+</span> current</span>
                      {canEdit && <button className="ws-btn sm primary" disabled={busy} onClick={restore}>{busy ? "Restoring…" : "Restore this revision"}</button>}
                    </div>
                    <pre className="vh-diff-body">
                      {diff.map((r, k) => (
                        <div key={k} className={`vh-line ${r.t}`}>
                          <span className="vh-sign">{r.t === "del" ? "−" : r.t === "add" ? "+" : " "}</span>{r.text || " "}
                        </div>
                      ))}
                    </pre>
                  </>
                )}
              </div>
            </div>
          )}
        </div>
        <div className="ac-modal-foot"><span className="spacer" /><button className="ws-btn" onClick={onClose}>Close</button></div>
      </div>
    </div>
  );
}
