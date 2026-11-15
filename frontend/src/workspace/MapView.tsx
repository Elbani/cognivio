import { MouseEvent, useMemo } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { MapResponse, Memory, MemoryListItem } from "../lib/api";
import { replaceWikiLinks } from "../lib/wikiLinks";

export function MapView({
  map,
  memories,
  canEdit,
  onOpen,
  onCreateMap
}: {
  map: MapResponse | null;
  memories: MemoryListItem[];
  canEdit: boolean;
  onOpen: (id: string) => void;
  onCreateMap: () => void;
}) {
  const mapMemory = map?.mapMemory ?? null;
  const md = useMemo(
    () => (mapMemory ? replaceWikiLinks(mapMemory.content, memories as unknown as Memory[]) : ""),
    [mapMemory, memories]
  );

  function previewLink(e: MouseEvent<HTMLAnchorElement>, href?: string) {
    if (!href?.startsWith("/app")) return;
    const id = new URL(href, window.location.origin).searchParams.get("memory");
    if (!id) return;
    e.preventDefault();
    onOpen(id);
  }

  return (
    <div style={{ height: "100%", overflowY: "auto" }}>
      <div style={{ maxWidth: 760, margin: "0 auto", padding: "26px 28px 72px" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 16 }}>
          <p style={{ color: "var(--text-muted)", fontSize: 13, margin: 0 }}>
            This is the first thing your agents read to orient themselves.
          </p>
          {mapMemory && canEdit && (
            <button className="ws-btn sm" style={{ marginLeft: "auto" }} onClick={() => onOpen(mapMemory.id)}>Edit</button>
          )}
        </div>

        {mapMemory ? (
          <article className="preview">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              urlTransform={(u) => (/^(https?:|mailto:|\/)/i.test(u) ? u : "")}
              components={{ a: ({ href, children, ...p }) => <a {...p} href={href} onClick={(e) => previewLink(e, href)}>{children}</a> }}
            >{md}</ReactMarkdown>
          </article>
        ) : (
          <div className="ws-empty" style={{ height: "auto", marginTop: 40 }}>
            <h2>No project map yet</h2>
            <p>Create a project map to give agents a single entry point into this team's knowledge.</p>
            {canEdit && <button className="ws-btn primary" onClick={onCreateMap}>Create the project map</button>}
          </div>
        )}
      </div>
    </div>
  );
}
