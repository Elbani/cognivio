import { MouseEvent, useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import remarkGfm from "remark-gfm";
import { apiRequest, Folder, Memory, MemoryListItem, MemoryStatus, MemoryType } from "../lib/api";
import { MEMORY_TYPES, MEMORY_TYPE_LABELS } from "../lib/api";
import { replaceWikiLinks } from "../lib/wikiLinks";
import {
  getCharCount, getWordCount, handleEditorKeyDown, insertCodeBlock, insertHr, insertLink,
  toggleBlockquote, toggleBold, toggleBulletList, toggleHeading, toggleInlineCode, toggleItalic,
  toggleOrderedList, toggleStrikethrough
} from "../editorActions";
import { useWikiLinkSuggest, WikiLinkDropdown } from "../WikiLinkSuggest";
import { VersionHistory } from "./VersionHistory";
import { freshness, TYPE_COLOR } from "./shared";

type Tab = "edit" | "preview";
type Save = "idle" | "saving" | "saved" | "error";

type Props = {
  token: string;
  memoryId: string;
  memories: MemoryListItem[];
  folders: Folder[];
  canEdit: boolean;
  trashMode: boolean;
  onSaved: (m: Memory) => void;
  onOpen: (id: string) => void;
  onTrash: (id: string) => void;
  onRestore: (id: string) => void;
  onDelete: (id: string) => void;
  onCreateFromTitle: (title: string) => void;
  startInEdit: boolean;
};

function splitTags(v: string) {
  return v.split(",").map((t) => t.trim().toLowerCase()).filter(Boolean);
}

export function MemoryDetail(props: Props) {
  const { token, memoryId, memories, folders, canEdit, trashMode, startInEdit } = props;
  const [memory, setMemory] = useState<Memory | null>(null);
  const [title, setTitle] = useState("");
  const [content, setContent] = useState("");
  const [tagsInput, setTagsInput] = useState("");
  const [tab, setTab] = useState<Tab>("preview");
  const [save, setSave] = useState<Save>("idle");
  const [historyOpen, setHistoryOpen] = useState(false);
  const editorRef = useRef<HTMLTextAreaElement>(null);
  const readOnly = trashMode || !canEdit;

  const byId = useMemo(() => new Map(memories.map((m) => [m.id, m])), [memories]);

  useEffect(() => {
    let cancelled = false;
    apiRequest<Memory>(`/api/memories/${memoryId}`, { token })
      .then((m) => {
        if (cancelled) return;
        setMemory(m);
        setTitle(m.title);
        setContent(m.content);
        setTagsInput(m.tags.join(", "));
        setSave("idle");
        setTab(startInEdit && canEdit ? "edit" : "preview");
      })
      .catch(() => undefined);
    return () => { cancelled = true; };
  }, [memoryId, token]);

  // autosave title/content/tags
  useEffect(() => {
    if (!memory || readOnly) return;
    const tags = splitTags(tagsInput);
    const changed = title !== memory.title || content !== memory.content || tags.join(",") !== memory.tags.join(",");
    if (!changed || !title.trim()) return;
    setSave("saving");
    const t = window.setTimeout(async () => {
      try {
        const up = await apiRequest<Memory>(`/api/memories/${memory.id}`, { method: "PATCH", token, body: { title, content, tags } });
        setMemory(up); setSave("saved"); props.onSaved(up);
      } catch { setSave("error"); }
    }, 850);
    return () => window.clearTimeout(t);
  }, [title, content, tagsInput, memory?.id, readOnly]);

  const wiki = useWikiLinkSuggest(memories as unknown as Memory[], content, setContent, editorRef, readOnly);
  const previewMd = useMemo(() => replaceWikiLinks(content, memories as unknown as Memory[]), [content, memories]);

  async function patch(body: Record<string, unknown>) {
    if (!memory) return;
    const up = await apiRequest<Memory>(`/api/memories/${memory.id}`, { method: "PATCH", token, body });
    setMemory(up); props.onSaved(up);
  }
  async function verify() {
    if (!memory) return;
    const up = await apiRequest<Memory>(`/api/memories/${memory.id}/verify`, { method: "POST", token });
    setMemory(up); props.onSaved(up);
  }
  async function approve() {
    if (!memory) return;
    const up = await apiRequest<Memory>(`/api/memories/${memory.id}/approve`, { method: "POST", token });
    setMemory(up); props.onSaved(up);
  }

  function previewLink(e: MouseEvent<HTMLAnchorElement>, href?: string) {
    if (!href?.startsWith("/app")) return;
    const id = new URL(href, window.location.origin).searchParams.get("memory");
    if (!id) return;
    e.preventDefault();
    props.onOpen(id);
  }

  if (!memory) return <div className="ws-empty">Loading…</div>;

  const backlinks = memories.filter((m) => m.linkedMemoryIds.includes(memory.id) && m.id !== memory.id);
  const outbound = memory.linkedMemoryIds.map((id) => byId.get(id)).filter(Boolean) as MemoryListItem[];
  const f = freshness(memory.lastVerifiedAt);
  const tags = splitTags(tagsInput);

  return (
    <div className="ws-detail">
      <div className="ws-editor-pane">
        <div className="ws-ehead">
          <div className="ws-ehead-top">
            <span className="ty-dot" style={{ background: TYPE_COLOR[memory.type], width: 12, height: 12 }} />
            <input className="ws-title-input" value={title} onChange={(e) => setTitle(e.target.value)} disabled={readOnly}
              onFocus={(e) => { if (title.startsWith("Untitled ")) e.target.select(); }} />
            {f.stale && (readOnly
              ? <span className="stale-pill" title={`Last verified ${f.label}`}>⚠ Stale</span>
              : <button className="stale-pill stale-btn" title={`Last verified ${f.label}, click to mark verified`} onClick={verify}>⚠ Stale · Verify</button>)}
            {memory.status === "draft" && memory.source === "agent" && (
              <span className="stale-pill" title="Written by an agent, awaiting approval">⏳ Pending review</span>
            )}
          </div>
          <div className="ws-ehead-meta">
            {!readOnly && (
              <div className="ws-tabs">
                <button className={`ws-tab${tab === "preview" ? " active" : ""}`} onClick={() => setTab("preview")}>Preview</button>
                <button className={`ws-tab${tab === "edit" ? " active" : ""}`} onClick={() => setTab("edit")}>Edit</button>
              </div>
            )}
            <span style={{ flex: 1 }} />
            {trashMode ? (
              <>
                <button className="ws-btn sm" onClick={() => props.onRestore(memory.id)}>Restore</button>
                <button className="ws-btn sm danger" onClick={() => props.onDelete(memory.id)}>Delete forever</button>
              </>
            ) : (
              <>
                {canEdit && memory.status === "draft" && memory.source === "agent" && (
                  <button className="ws-btn sm primary" onClick={approve}>Approve</button>
                )}
                <button className="ws-btn sm" onClick={() => setHistoryOpen(true)}>History</button>
                {canEdit && <button className="ws-btn sm danger" onClick={() => props.onTrash(memory.id)}>Trash</button>}
              </>
            )}
          </div>
        </div>

        {tab === "edit" && !readOnly && (
          <div className="md-toolbar" role="toolbar" style={{ padding: "8px 18px", borderBottom: "1px solid var(--border)" }}>
            <button title="Bold" onClick={() => toggleBold(editorRef, content, setContent)}><b>B</b></button>
            <button title="Italic" onClick={() => toggleItalic(editorRef, content, setContent)}><i>I</i></button>
            <button title="Strikethrough" onClick={() => toggleStrikethrough(editorRef, content, setContent)}><s>S</s></button>
            <span className="md-toolbar-sep" />
            <button title="Heading" onClick={() => toggleHeading(editorRef, content, setContent)}>H</button>
            <button title="Inline code" onClick={() => toggleInlineCode(editorRef, content, setContent)}>{"</>"}</button>
            <button title="Code block" onClick={() => insertCodeBlock(editorRef, content, setContent)}>{"{ }"}</button>
            <span className="md-toolbar-sep" />
            <button title="Bullet list" onClick={() => toggleBulletList(editorRef, content, setContent)}>•</button>
            <button title="Numbered list" onClick={() => toggleOrderedList(editorRef, content, setContent)}>1.</button>
            <button title="Quote" onClick={() => toggleBlockquote(editorRef, content, setContent)}>❝</button>
            <span className="md-toolbar-sep" />
            <button title="Link" onClick={() => insertLink(editorRef, content, setContent)}>🔗</button>
            <button title="Divider" onClick={() => insertHr(editorRef, content, setContent)}>―</button>
          </div>
        )}

        <div className="ws-editor-body">
          {tab === "edit" ? (
            <div style={{ position: "relative", flex: 1, display: "flex" }}>
              <textarea
                ref={editorRef} value={content} disabled={readOnly} spellCheck={false}
                onChange={(e) => { setContent(e.target.value); wiki.detect(e); }}
                onKeyDown={(e) => { if (wiki.suggest.open) { wiki.handleKeyDown(e); return; } handleEditorKeyDown(e, content, setContent, editorRef); }}
              />
              {wiki.suggest.open && (
                <WikiLinkDropdown filtered={wiki.filtered} activeIndex={wiki.activeIndex} position={wiki.position} onPick={wiki.pick} onClose={wiki.close} />
              )}
            </div>
          ) : (
            <article className="ws-preview preview">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}
                urlTransform={(u) => (/^(https?:|mailto:|\/)/i.test(u) ? u : "")}
                components={{ a: ({ href, children, ...p }) => <a {...p} href={href} rel="noopener noreferrer" onClick={(e) => previewLink(e, href)}>{children}</a> }}
              >{previewMd}</ReactMarkdown>
            </article>
          )}
        </div>

        <div className="ws-statusbar">
          <span>{getWordCount(content)} words</span>
          <span>{getCharCount(content)} chars</span>
          {!readOnly && save !== "idle" && (
            <span className={`save ws-save-${save}`}>{save === "saving" ? "Saving…" : save === "saved" ? "Saved" : "Save failed"}</span>
          )}
        </div>
      </div>

      <aside className="ws-side">
        <h4>Type</h4>
        <select className="ws-select" value={memory.type} disabled={readOnly} onChange={(e) => patch({ type: e.target.value as MemoryType })}>
          {MEMORY_TYPES.map((t) => <option key={t} value={t}>{MEMORY_TYPE_LABELS[t]}</option>)}
        </select>

        <h4>Status</h4>
        <select className="ws-select" value={memory.status} disabled={readOnly} onChange={(e) => patch({ status: e.target.value as MemoryStatus })}>
          <option value="active">Active</option>
          <option value="draft">Draft</option>
          <option value="deprecated">Deprecated</option>
        </select>

        <h4>Project</h4>
        <select className="ws-select" value={memory.folderId ?? ""} disabled={readOnly} onChange={(e) => patch({ folderId: e.target.value || null })}>
          <option value="">No project</option>
          {folders.map((fl) => <option key={fl.id} value={fl.id}>{fl.name}</option>)}
        </select>

        <h4>Freshness</h4>
        <div className="ws-meta-row">
          <span className={f.stale ? "fresh-stale" : "fresh-ok"}>{f.label}</span>
          {!readOnly && <button className="ws-btn sm" onClick={verify}>Verify now</button>}
        </div>

        <h4>Tags</h4>
        <div className="ws-tagchips">
          {tags.map((t) => (
            <span className="ws-tagchip" key={t}>#{t}{!readOnly && <button onClick={() => setTagsInput(tags.filter((x) => x !== t).join(", "))}>×</button>}</span>
          ))}
          {!readOnly && (
            <input className="ws-tag-input" placeholder="+ tag" onKeyDown={(e) => {
              const v = e.currentTarget.value.trim().toLowerCase();
              if ((e.key === "Enter" || e.key === ",") && v) { e.preventDefault(); if (!tags.includes(v)) setTagsInput([...tags, v].join(", ")); e.currentTarget.value = ""; }
            }} />
          )}
        </div>

        <h4>Links out ({outbound.length})</h4>
        {outbound.length === 0 && <div className="ws-empty-sm">No links yet.</div>}
        {outbound.map((m) => (
          <div className="ws-link-row" key={m.id} onClick={() => props.onOpen(m.id)}>
            <span className="ty-dot" style={{ background: TYPE_COLOR[m.type] }} />{m.title}
          </div>
        ))}

        {memory.unresolvedLinks.length > 0 && (
          <>
            <h4>Unresolved ({memory.unresolvedLinks.length})</h4>
            {memory.unresolvedLinks.map((t) => (
              <div className="ws-unresolved" key={t}>
                <span style={{ color: "var(--text-muted)" }}>⚠</span>{t}
                {!readOnly && <button className="mk" onClick={() => props.onCreateFromTitle(t)}>create</button>}
              </div>
            ))}
          </>
        )}

        <h4>Backlinks ({backlinks.length})</h4>
        {backlinks.length === 0 && <div className="ws-empty-sm">Nothing links here yet.</div>}
        {backlinks.map((m) => (
          <div className="ws-link-row" key={m.id} onClick={() => props.onOpen(m.id)}>
            <span className="ty-dot" style={{ background: TYPE_COLOR[m.type] }} />{m.title}
          </div>
        ))}

        <h4>Provenance</h4>
        <div className="ws-meta-row"><span>Source</span><b>{memory.source}{memory.source === "agent" ? " ✦" : ""}</b></div>
        {(memory.helpfulCount > 0 || memory.notHelpfulCount > 0) && (
          <div className="ws-meta-row" title="How agents rated this doc via mark_helpful">
            <span>Agent feedback</span><b>👍 {memory.helpfulCount} · 👎 {memory.notHelpfulCount}</b>
          </div>
        )}
        <div className="ws-meta-row"><span>Created</span><b>{new Date(memory.createdAt).toLocaleDateString()}</b></div>
        <div className="ws-meta-row"><span>Updated</span><b>{new Date(memory.updatedAt).toLocaleDateString()}</b></div>
      </aside>

      {historyOpen && (
        <VersionHistory
          token={token}
          memoryId={memory.id}
          currentContent={memory.content}
          canEdit={canEdit && !trashMode}
          onRestored={(m) => { setMemory(m); setTitle(m.title); setContent(m.content); setTagsInput(m.tags.join(", ")); props.onSaved(m); }}
          onClose={() => setHistoryOpen(false)}
        />
      )}
    </div>
  );
}
