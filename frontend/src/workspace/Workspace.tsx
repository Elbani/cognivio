import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import "../styles/workspace.css";
import {
  apiRequest, AuditEntry, Folder, MapResponse, Member, Memory, MemoryListItem,
  MemoryType, Org, Team, User, MEMORY_TYPES, MEMORY_TYPE_LABELS, UserTheme } from "../lib/api";
import { freshness, TYPE_COLOR } from "./shared";
import { Overview } from "./Overview";
import { MemoriesBrowser } from "./MemoriesBrowser";
import { MemoryDetail } from "./MemoryDetail";
import { MapView } from "./MapView";
import { GraphView } from "./GraphView";
import { AgentsView } from "./AgentsView";
import { InsightsView } from "./InsightsView";
import { RepoView } from "./RepoView";
import { ProjectDocsView } from "./ProjectDocsView";
import { MembersView } from "./MembersView";
import { HelpView } from "./HelpView";
import { SettingsView } from "./SettingsView";
import { ConnectDialog } from "./ConnectDialog";
import { Tour, TourStep } from "./Tour";
import { ScopeMenu } from "./ScopeMenu";

type View = "overview" | "map" | "memories" | "graph" | "agents" | "insights" | "repo" | "projectdocs" | "members" | "trash" | "help" | "settings" | "review";

type DialogKind = "new-org" | "rename-org" | "new-team" | "rename-team" | "new-project";

const DIALOG_META: Record<DialogKind, { title: string; label: string; submit: string }> = {
  "new-org": { title: "New organization", label: "Organization name", submit: "Create" },
  "rename-org": { title: "Rename organization", label: "Organization name", submit: "Save" },
  "new-team": { title: "New team", label: "Team name", submit: "Create" },
  "rename-team": { title: "Rename team", label: "Team name", submit: "Save" },
  "new-project": { title: "New project", label: "Project name", submit: "Create" }
};

// All glyphs are monochrome text-style; symbols that default to emoji presentation
// on macOS (☀ ⚙ etc.) carry U+FE0E to force the text glyph and stay visually consistent.
const NAV: { id: View; label: string; glyph: string }[] = [
  { id: "overview", label: "Overview", glyph: "▦" },
  { id: "map", label: "Project Map", glyph: "◇" },
  { id: "memories", label: "Docs", glyph: "▤" },
  { id: "graph", label: "Graph", glyph: "⬡" },
  { id: "agents", label: "Agents", glyph: "⚿" },
  { id: "insights", label: "Insights", glyph: "◫" },
  { id: "repo", label: "Repo", glyph: "⎇" },
  { id: "projectdocs", label: "Project Docs", glyph: "❏" },
  { id: "trash", label: "Trash", glyph: "⌫" }
];

// Sections that can be restored from ?view= on refresh / deep-link.
const VIEWS: View[] = ["overview", "map", "memories", "graph", "agents", "insights", "repo", "projectdocs", "members", "trash", "help", "settings", "review"];

export function Workspace({ token, user, ui = "terminal", onLogout, onUserUpdated }: { token: string; user: User | null; ui?: UserTheme; onLogout: () => void; onUserUpdated: (user: User) => void }) {
  const [searchParams, setSearchParams] = useSearchParams();
  const [orgs, setOrgs] = useState<Org[]>([]);
  const [orgId, setOrgId] = useState<string | null>(() => localStorage.getItem("kb-org"));
  const [teams, setTeams] = useState<Team[]>([]);
  const [teamId, setTeamId] = useState<string | null>(() => localStorage.getItem("kb-team"));
  const [view, setView] = useState<View>(() => {
    const v = searchParams.get("view");
    return v && (VIEWS as string[]).includes(v) ? (v as View) : "overview";
  });
  const [memories, setMemories] = useState<MemoryListItem[]>([]);
  const [trashed, setTrashed] = useState<MemoryListItem[]>([]);
  const [pending, setPending] = useState<MemoryListItem[]>([]);
  const [folders, setFolders] = useState<Folder[]>([]);
  const [map, setMap] = useState<MapResponse | null>(null);
  const [members, setMembers] = useState<Member[]>([]);
  const [activity, setActivity] = useState<AuditEntry[]>([]);
  // True while a team's initial data is still in flight, so the Overview shows a
  // skeleton instead of flashing the empty "Getting started" state before data lands.
  const [loading, setLoading] = useState(true);
  const [templates, setTemplates] = useState<Record<string, string>>({});
  const [selectedId, setSelectedId] = useState<string | null>(() => searchParams.get("memory"));
  const [newOpen, setNewOpen] = useState(false);
  const [error, setError] = useState("");
  // Dark/light is a per-device choice. With no stored choice, the terminal theme starts
  // dark (it is a console) and the editorial theme starts light (it is a page).
  const [theme, setTheme] = useState<"dark" | "light">(() => {
    const stored = localStorage.getItem("kb-theme");
    if (stored === "light" || stored === "dark") return stored;
    return ui === "editorial" ? "light" : "dark";
  });
  const [tourOpen, setTourOpen] = useState(() => !localStorage.getItem("ac-welcomed"));
  const [editId, setEditId] = useState<string | null>(null);
  const [dialog, setDialog] = useState<{ kind: DialogKind; value: string } | null>(null);
  const [connectOpen, setConnectOpen] = useState(false);
  const newRef = useRef<HTMLDivElement>(null);

  useEffect(() => { localStorage.setItem("kb-theme", theme); }, [theme]);

  function finishTour() { localStorage.setItem("ac-welcomed", "1"); setTourOpen(false); }

  async function loadExamples() {
    if (!teamId) return;
    const make = (title: string, type: MemoryType, content: string) =>
      apiRequest<Memory>(`/api/teams/${teamId}/memories`, { method: "POST", token, body: { title, type, content, tags: [] } });
    try {
      await make("How the app works", "architecture",
        "# How the app works\n\nA short description of your system: the main pieces and how they fit together.\n\n## Components\n- \n");
      await make("Deploy guide", "playbook",
        "# Deploy guide\n\n## Steps\n1. \n2. \n3. \n\n## Rollback\n- \n");
      await make("Why we chose this stack", "decision",
        "# Decision: our stack\n\n- **Status:** accepted\n\n## Context\n\n## Decision\n\n## Consequences\n");
      await make("Project Map", "map",
        "# Project Map\n\n> Start here. This is the first thing your agents read.\n\n## Key docs\n" +
        "- [[How the app works]]\n- [[Deploy guide]]\n- [[Why we chose this stack]]\n");
      refreshTeam(teamId);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load examples");
    }
  }

  const currentOrg = orgs.find((o) => o.id === orgId) ?? null;
  const currentTeam = teams.find((t) => t.id === teamId) ?? null;
  const canEdit = currentOrg ? currentOrg.role !== "viewer" : false;
  const canManage = currentOrg ? currentOrg.role === "owner" || currentOrg.role === "admin" : false;

  // bootstrap
  useEffect(() => {
    apiRequest<Org[]>("/api/orgs", { token })
      .then((o) => { setOrgs(o); setOrgId((c) => (c && o.some((x) => x.id === c) ? c : o[0]?.id ?? null)); })
      .catch((e) => setError(e.message));
    apiRequest<Record<string, string>>("/api/memory-templates", { token }).then(setTemplates).catch(() => undefined);
  }, [token]);

  // org -> teams (only for an org the current user actually belongs to)
  useEffect(() => {
    if (!orgId || !orgs.some((o) => o.id === orgId)) return;
    localStorage.setItem("kb-org", orgId);
    setError("");
    apiRequest<Team[]>(`/api/orgs/${orgId}/teams`, { token })
      .then((t) => { setTeams(t); setTeamId((c) => (c && t.some((x) => x.id === c) ? c : t[0]?.id ?? null)); })
      .catch((e) => setError(e.message));
    apiRequest<Member[]>(`/api/orgs/${orgId}/members`, { token }).then(setMembers).catch(() => undefined);
  }, [orgId, orgs, token]);

  function refreshTeam(tid: string, opts: { quiet?: boolean } = {}) {
    if (!opts.quiet) setLoading(true);
    const memP = apiRequest<{ memories: MemoryListItem[] }>(`/api/teams/${tid}/memories`, { token }).then((p) => setMemories(p.memories)).catch((e) => setError(e.message));
    apiRequest<Folder[]>(`/api/teams/${tid}/folders`, { token }).then(setFolders).catch(() => undefined);
    const mapP = apiRequest<MapResponse>(`/api/teams/${tid}/map`, { token }).then(setMap).catch(() => undefined);
    const actP = apiRequest<{ entries: AuditEntry[] }>(`/api/teams/${tid}/activity`, { token }).then((p) => setActivity(p.entries)).catch(() => undefined);
    loadPending(tid);
    // Clear the gate only once the three feeds the Overview reads (docs, map, activity) settle.
    if (!opts.quiet) Promise.allSettled([memP, mapP, actP]).then(() => setLoading(false));
  }

  // team -> data (only once the team belongs to the loaded org's team list)
  useEffect(() => {
    if (!teamId || !teams.some((t) => t.id === teamId)) return;
    localStorage.setItem("kb-team", teamId);
    setError("");
    refreshTeam(teamId);
  }, [teamId, teams, token]);

  // close "new" menu on outside click
  useEffect(() => {
    function h(e: globalThis.MouseEvent) { if (newRef.current && !newRef.current.contains(e.target as Node)) setNewOpen(false); }
    document.addEventListener("mousedown", h);
    return () => document.removeEventListener("mousedown", h);
  }, []);

  // Persist the active section (and open doc) in the URL so a refresh / deep-link restores
  // exactly where you were, instead of resetting to Overview. "overview" is the clean default
  // (omitted from the URL).
  function viewParams(v: View, memory?: string): Record<string, string> {
    const p: Record<string, string> = {};
    if (v !== "overview") p.view = v;
    if (memory) p.memory = memory;
    return p;
  }
  function openMemory(id: string) { setSelectedId(id); setSearchParams(viewParams(view, id)); }
  function closeMemory() { setSelectedId(null); setSearchParams(viewParams(view)); }
  function goView(v: string) {
    setSelectedId(null);
    setView(v as View);
    setSearchParams(viewParams(v as View));
    if (v === "trash") loadTrash();
    if (v === "review" && teamId) loadPending(teamId);
    // Refresh team-level feeds (docs, map, activity, folders) so navigating between
    // sections picks up writes an agent or another tab may have made since mount.
    // Quiet so the Overview doesn't re-flash its skeleton on every menu click.
    if (teamId) refreshTeam(teamId, { quiet: true });
  }

  function loadTrash() {
    if (!teamId) return;
    apiRequest<{ memories: MemoryListItem[] }>(`/api/teams/${teamId}/memories/trash`, { token }).then((p) => setTrashed(p.memories)).catch(() => undefined);
  }

  // Agent-authored drafts awaiting approval (the write-back review queue).
  function loadPending(tid: string) {
    apiRequest<{ memories: MemoryListItem[] }>(`/api/teams/${tid}/memories?status=draft&source=agent`, { token })
      .then((p) => setPending(p.memories)).catch(() => undefined);
  }

  // Refresh landing directly on ?view=trash never goes through goView, so load it here.
  useEffect(() => { if (view === "trash" && teamId) loadTrash(); }, [view, teamId]);
  useEffect(() => { if (view === "review" && teamId) loadPending(teamId); }, [view, teamId]);

  function onSaved(up: Memory) {
    setMemories((cur) => {
      const item = up as unknown as MemoryListItem;
      return cur.some((m) => m.id === up.id) ? cur.map((m) => (m.id === up.id ? item : m)) : [item, ...cur];
    });
    if (teamId) apiRequest<MapResponse>(`/api/teams/${teamId}/map`, { token }).then(setMap).catch(() => undefined);
  }

  async function createMemory(type: MemoryType) {
    if (!teamId) return;
    setNewOpen(false);
    const label = MEMORY_TYPE_LABELS[type].toLowerCase();
    const m = await apiRequest<Memory>(`/api/teams/${teamId}/memories`, {
      method: "POST", token,
      body: { title: `Untitled ${label}`, content: templates[type] ?? "", type, tags: [] }
    });
    setMemories((cur) => [m as unknown as MemoryListItem, ...cur]);
    setEditId(m.id);
    openMemory(m.id);
  }

  async function createFromTitle(title: string) {
    if (!teamId) return;
    const m = await apiRequest<Memory>(`/api/teams/${teamId}/memories`, {
      method: "POST", token, body: { title, content: "", type: "note", tags: [] }
    });
    setMemories((cur) => [m as unknown as MemoryListItem, ...cur]);
    setEditId(m.id);
    openMemory(m.id);
  }

  const byName = (a: { name: string }, b: { name: string }) => a.name.localeCompare(b.name);

  async function submitDialog(name: string) {
    const d = dialog;
    if (!d) return;
    try {
      if (d.kind === "new-org") {
        const o = await apiRequest<Org>("/api/orgs", { method: "POST", token, body: { name } });
        setOrgs((c) => [...c, o].sort(byName)); setOrgId(o.id);
      } else if (d.kind === "rename-org" && orgId) {
        const o = await apiRequest<Org>(`/api/orgs/${orgId}`, { method: "PATCH", token, body: { name } });
        setOrgs((c) => c.map((x) => (x.id === o.id ? o : x)).sort(byName));
      } else if (d.kind === "new-team" && orgId) {
        const t = await apiRequest<Team>(`/api/orgs/${orgId}/teams`, { method: "POST", token, body: { name } });
        setTeams((c) => [...c, t].sort(byName)); setSelectedId(null); setTeamId(t.id);
      } else if (d.kind === "rename-team" && teamId) {
        const t = await apiRequest<Team>(`/api/teams/${teamId}`, { method: "PATCH", token, body: { name } });
        setTeams((c) => c.map((x) => (x.id === t.id ? t : x)).sort(byName));
      } else if (d.kind === "new-project" && teamId) {
        const f = await apiRequest<Folder>(`/api/teams/${teamId}/folders`, { method: "POST", token, body: { name } });
        setFolders((c) => [...c, f].sort(byName));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Action failed");
    }
    setDialog(null);
  }

  // Platform admins (ADMIN_EMAILS) are never paywalled; the backend applies the same rule.
  const isPlatformAdmin = Boolean(user?.isAdmin);
  const isEnterprise = isPlatformAdmin || currentOrg?.plan === "enterprise";
  const canAddOrg = isPlatformAdmin || orgs.length === 0 || orgs.some((o) => o.plan === "enterprise");
  const upsell = (what: string) =>
    setError(`${what} are an Enterprise feature. The Free plan is a single developer (1 org, 1 team, 1 project). Ask your administrator to enable them.`);
  const createProject = () => (isEnterprise || folders.length === 0 ? setDialog({ kind: "new-project", value: "" }) : upsell("Multiple projects"));
  const createOrg = () => (canAddOrg ? setDialog({ kind: "new-org", value: "" }) : upsell("Multiple organizations"));
  const createTeam = () => (isEnterprise || teams.length === 0 ? setDialog({ kind: "new-team", value: "" }) : upsell("Multiple teams"));
  const renameOrg = () => setDialog({ kind: "rename-org", value: currentOrg?.name ?? "" });
  const renameTeam = () => setDialog({ kind: "rename-team", value: currentTeam?.name ?? "" });

  async function trashMemory(id: string) {
    await apiRequest(`/api/memories/${id}`, { method: "DELETE", token });
    setMemories((cur) => cur.filter((m) => m.id !== id));
    closeMemory();
  }
  async function restoreMemory(id: string) {
    const m = await apiRequest<Memory>(`/api/memories/${id}/restore`, { method: "POST", token });
    setTrashed((cur) => cur.filter((x) => x.id !== id));
    setMemories((cur) => [m as unknown as MemoryListItem, ...cur]);
  }
  async function deleteForever(id: string) {
    if (!window.confirm("Permanently delete this doc? This cannot be undone.")) return;
    await apiRequest(`/api/memories/${id}/permanent`, { method: "DELETE", token });
    setTrashed((cur) => cur.filter((x) => x.id !== id));
  }

  async function approvePending(id: string) {
    const m = await apiRequest<Memory>(`/api/memories/${id}/approve`, { method: "POST", token });
    setPending((cur) => cur.filter((x) => x.id !== id));
    onSaved(m);
  }
  async function dismissPending(id: string) {
    if (!window.confirm("Dismiss this agent draft? It moves to Trash.")) return;
    await apiRequest(`/api/memories/${id}`, { method: "DELETE", token });
    setPending((cur) => cur.filter((x) => x.id !== id));
    setMemories((cur) => cur.filter((x) => x.id !== id));
  }

  const attentionCount = useMemo(() => {
    const linkedTo = new Set<string>();
    memories.forEach((m) => m.linkedMemoryIds.forEach((id) => linkedTo.add(id)));
    const stale = memories.filter((m) => freshness(m.lastVerifiedAt).stale).length;
    const issues = memories.filter((m) => m.unresolvedLinks.length > 0 || (m.linkedMemoryIds.length === 0 && !linkedTo.has(m.id))).length;
    return stale + issues;
  }, [memories]);

  const fullBleed = Boolean(selectedId) || view === "graph" || view === "map";
  const titleByView: Record<View, string> = {
    overview: "Overview", map: "Project Map", memories: "Docs", graph: "Graph", agents: "Agents", insights: "Insights", repo: "Repo", projectdocs: "Project Docs", members: "Members", trash: "Trash", help: "Help & API", settings: "Settings", review: "Review"
  };

  const tourSteps: TourStep[] = [
    { place: "center", title: "Welcome to Cognivio", body: "A quick tour of your team's knowledge base, the place your AI agents read before they act. Takes about a minute." },
    { sel: '[data-tour="switcher"]', place: "right", title: "Org & team", body: "This is where you are. Open it to switch organization or team, or to create a new one. Each team has its own docs, map, and agents." },
    { sel: '[data-tour="nav-overview"]', place: "right", title: "Overview", body: "The health of your knowledge base at a glance, plus a getting-started checklist." },
    { sel: '[data-tour="nav-map"]', place: "right", title: "Project Map", body: "The entry point your agents read first. It points them to everything else." },
    { sel: '[data-tour="nav-memories"]', place: "right", title: "Docs", body: "Write and browse all your docs, grouped by type: How It Works, Guide, Decision, and more." },
    { sel: '[data-tour="nav-graph"]', place: "right", title: "Graph", body: "See how your docs connect through [[links]], and spot orphans." },
    { sel: '[data-tour="nav-agents"]', place: "right", title: "Agents", body: "Create API keys and watch what your agents are reading and writing." },
    ...(canEdit ? [{ sel: '[data-tour="new-doc"]', place: "bottom" as const, title: "Create a doc", body: "Add a doc anytime: pick its type, then type [[ to link it to others." }] : []),
    { sel: '[data-tour="theme"]', place: "right", title: "Theme", body: "Prefer light mode? Switch the theme here, your choice is remembered." },
    { place: "center", title: "You're all set 🎉", body: canEdit ? "Start by creating your Project Map, or load example docs from the Overview to see how it fits together." : "Browse the Project Map and Docs to explore your team's knowledge." }
  ];

  return (
    <div className="ws" data-theme={theme} data-ui={ui}>
      {tourOpen && teamId && <Tour steps={tourSteps} onFinish={finishTour} />}
      {connectOpen && orgId && (
        <ConnectDialog token={token} orgId={orgId} teamId={teamId} canManage={canManage} onClose={() => setConnectOpen(false)} />
      )}
      {dialog && (
        <ScopeDialog
          title={DIALOG_META[dialog.kind].title}
          label={DIALOG_META[dialog.kind].label}
          submitLabel={DIALOG_META[dialog.kind].submit}
          initial={dialog.value}
          onSubmit={submitDialog}
          onClose={() => setDialog(null)}
        />
      )}
      <aside className="ws-rail">
        <div className="ws-rail-brand"><span className="mk">◆</span>Cognivio</div>
        <ScopeMenu
          token={token} orgs={orgs} teams={teams} orgId={orgId} teamId={teamId}
          canManage={canManage} canAddOrg={canAddOrg} canAddTeam={canManage && (isEnterprise || teams.length === 0)}
          onSelectOrg={(id) => { setOrgId(id); setSelectedId(null); }}
          onSelectTeam={(oid, tid) => { setOrgId(oid); setTeamId(tid); setSelectedId(null); }}
          onNewOrg={createOrg} onNewTeam={createTeam} onRenameOrg={renameOrg} onRenameTeam={renameTeam}
        />

        <div className="ws-navlabel">Knowledge</div>
        {NAV.map((n) => (
          <button key={n.id} data-tour={`nav-${n.id}`} className={`ws-navitem${view === n.id && !selectedId ? " active" : ""}`} onClick={() => goView(n.id)}>
            <span className="ico">{n.glyph}</span>{n.label}
            {n.id === "overview" && attentionCount > 0 && <span className="badge">{attentionCount}</span>}
          </button>
        ))}
        {(currentTeam?.agentWriteReview || pending.length > 0) && (
          <button className={`ws-navitem${view === "review" && !selectedId ? " active" : ""}`} onClick={() => goView("review")}>
            <span className="ico">◔</span>Review
            {pending.length > 0 && <span className="badge">{pending.length}</span>}
          </button>
        )}

        <div className="ws-navlabel">Settings</div>
        <button className={`ws-navitem${view === "members" && !selectedId ? " active" : ""}`} onClick={() => goView("members")}>
          <span className="ico">◉</span>Members
        </button>
        <button className={`ws-navitem${view === "help" && !selectedId ? " active" : ""}`} onClick={() => goView("help")}>
          <span className="ico">⊙</span>Help &amp; API
        </button>
        <button className={`ws-navitem${view === "settings" && !selectedId ? " active" : ""}`} onClick={() => goView("settings")}>
          <span className="ico">⚙︎</span>Settings
        </button>

        <div className="ws-rail-spacer" />
        <div className="ws-rail-foot">
          <button className="ws-navitem" onClick={() => { goView("overview"); setTourOpen(true); }}>
            <span className="ico">✦</span>Take the tour
          </button>
          <button className="ws-navitem" data-tour="theme" onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}>
            <span className="ico">{theme === "dark" ? "☀︎" : "☾"}</span>{theme === "dark" ? "Light theme" : "Dark theme"}
          </button>
          {user?.isAdmin && (
            <a className="ws-navitem" href="/admin"><span className="ico">⛨</span>Admin console</a>
          )}
          <button className="ws-navitem" onClick={onLogout}><span className="ico">⏻</span>Sign out</button>
        </div>
      </aside>

      <main className="ws-main">
        <header className="ws-topbar">
          {selectedId ? (
            <button className="ws-btn sm" onClick={closeMemory}>← Back</button>
          ) : (
            <div>
              <h1>{titleByView[view]}</h1>
              <span className="sub">{currentTeam ? currentTeam.name : ""}{currentOrg ? ` · ${currentOrg.name}` : ""}</span>
            </div>
          )}
          <div className="right">
            {view === "memories" && canEdit && !selectedId && <button className="ws-btn sm" onClick={createProject}>+ Project</button>}
            {canEdit && (
              <div className="ws-newmenu" ref={newRef}>
                <button className="ws-btn primary" data-tour="new-doc" onClick={() => setNewOpen((v) => !v)}>+ New doc</button>
                {newOpen && (
                  <div className="ws-newmenu-pop">
                    {MEMORY_TYPES.map((t) => (
                      <button key={t} onClick={() => createMemory(t as MemoryType)}>
                        <span className="ty-dot" style={{ background: TYPE_COLOR[t as MemoryType] }} />{MEMORY_TYPE_LABELS[t]}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </header>

        {error && <div className="error-banner" style={{ margin: 16 }}>{error}</div>}

        <div className={fullBleed ? "ws-content flush" : "ws-content"} style={fullBleed ? { overflow: "hidden" } : undefined}>
          {!teamId ? (
            <div className="ws-empty"><h2>No team</h2><p>Create or pick a team to begin.</p></div>
          ) : selectedId ? (
            <MemoryDetail
              token={token} memoryId={selectedId} memories={memories} folders={folders}
              canEdit={canEdit} trashMode={false} startInEdit={selectedId === editId}
              onSaved={onSaved} onOpen={openMemory} onTrash={trashMemory} onRestore={restoreMemory}
              onDelete={deleteForever} onCreateFromTitle={createFromTitle}
            />
          ) : view === "overview" ? (
            <Overview loading={loading} memories={memories} activity={activity} hasMap={Boolean(map?.mapMemory)} canEdit={canEdit} onOpen={openMemory} onView={goView} onCreate={createMemory} onLoadExamples={loadExamples} onConnect={() => setConnectOpen(true)} />
          ) : view === "map" ? (
            <MapView map={map} memories={memories} canEdit={canEdit} onOpen={openMemory} onCreateMap={() => createMemory("map")} />
          ) : view === "memories" ? (
            <MemoriesBrowser memories={memories} folders={folders} onOpen={openMemory} />
          ) : view === "graph" ? (
            <GraphView memories={memories} selectedId={selectedId} onSelect={openMemory} />
          ) : view === "agents" ? (
            <AgentsView token={token} orgId={orgId!} teams={teams} canManage={canManage} activity={activity} memories={memories} onOpen={openMemory} onConnect={() => setConnectOpen(true)} />
          ) : view === "insights" ? (
            <InsightsView token={token} orgId={orgId!} onView={goView} onOpen={openMemory} />
          ) : view === "repo" ? (
            <RepoView token={token} teamId={teamId!} canManage={canManage} onOpen={openMemory} />
          ) : view === "projectdocs" ? (
            <ProjectDocsView token={token} teamId={teamId!} />
          ) : view === "members" ? (
            <MembersView token={token} orgId={orgId!} unlocked={isEnterprise} members={members} canManage={canManage} currentUserId={user?.id ?? null} onChanged={() => apiRequest<Member[]>(`/api/orgs/${orgId}/members`, { token }).then(setMembers).catch(() => undefined)} />
          ) : view === "help" ? (
            <HelpView />
          ) : view === "settings" ? (
            <SettingsView
              token={token} user={user} org={currentOrg} team={currentTeam} canManage={canManage}
              theme={theme} onTheme={setTheme} onUserUpdated={onUserUpdated}
              onOrgUpdated={(o) => setOrgs((c) => c.map((x) => (x.id === o.id ? o : x)).sort(byName))}
              onTeamUpdated={(t) => setTeams((c) => c.map((x) => (x.id === t.id ? t : x)).sort(byName))}
              onOpenHelp={() => goView("help")} onSignOut={onLogout}
              docCount={memories.length} onWiped={() => { if (teamId) { refreshTeam(teamId); loadTrash(); } }}
            />
          ) : view === "review" ? (
            <ReviewView pending={pending} onOpen={openMemory} onApprove={approvePending} onDismiss={dismissPending} canEdit={canEdit} reviewOn={Boolean(currentTeam?.agentWriteReview)} />
          ) : view === "trash" ? (
            <TrashView trashed={trashed} onRestore={restoreMemory} onDelete={deleteForever} canEdit={canEdit} />
          ) : null}
        </div>
      </main>
    </div>
  );
}

function ScopeDialog({ title, label, submitLabel, initial, onSubmit, onClose }: {
  title: string; label: string; submitLabel: string; initial: string;
  onSubmit: (name: string) => Promise<void>; onClose: () => void;
}) {
  const [value, setValue] = useState(initial);
  const [busy, setBusy] = useState(false);
  async function go() {
    if (!value.trim() || busy) return;
    setBusy(true);
    await onSubmit(value.trim());
  }
  return (
    <div className="ac-overlay" onClick={onClose}>
      <div className="ac-modal" style={{ maxWidth: 420 }} onClick={(e) => e.stopPropagation()}>
        <div className="ac-modal-head"><h2>{title}</h2></div>
        <div className="ac-modal-body">
          <label className="scope-label">{label}
            <input className="scope-input" autoFocus value={value} onChange={(e) => setValue(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter") go(); if (e.key === "Escape") onClose(); }} />
          </label>
        </div>
        <div className="ac-modal-foot">
          <span className="spacer" />
          <button className="ws-btn" onClick={onClose}>Cancel</button>
          <button className="ws-btn primary" disabled={busy || !value.trim()} onClick={go}>{submitLabel}</button>
        </div>
      </div>
    </div>
  );
}

function ReviewView({ pending, onOpen, onApprove, onDismiss, canEdit, reviewOn }: {
  pending: MemoryListItem[];
  onOpen: (id: string) => void;
  onApprove: (id: string) => void;
  onDismiss: (id: string) => void;
  canEdit: boolean;
  reviewOn: boolean;
}) {
  if (pending.length === 0) {
    return (
      <div className="ws-empty">
        <h2>Nothing to review</h2>
        <p>
          {reviewOn
            ? "Agent write-back is held for approval. Docs an agent creates or updates will appear here as drafts."
            : "Turn on “Hold for review” in Settings → Knowledge base to have agent write-back wait for your approval."}
        </p>
      </div>
    );
  }
  return (
    <div className="ws-grid" style={{ gap: 14 }}>
      <p style={{ color: "var(--text-secondary)", fontSize: 14, margin: 0 }}>
        Drafts written by agents, awaiting approval. They're hidden from agent retrieval until you approve them.
      </p>
      <table className="ws-table">
        <thead><tr><th>Title</th><th>Type</th><th>Written by</th>{canEdit && <th></th>}</tr></thead>
        <tbody>
          {pending.map((m) => (
            <tr key={m.id}>
              <td><button className="ws-linklike" onClick={() => onOpen(m.id)} style={{ textAlign: "left" }}><b>{m.title}</b></button></td>
              <td><span className="ty-pill"><span className="ty-dot" style={{ background: TYPE_COLOR[m.type] }} />{m.type}</span></td>
              <td style={{ color: "var(--text-muted)" }}>{(m.sourceRef as { keyName?: string } | null)?.keyName ?? "agent"}</td>
              {canEdit && (
                <td style={{ textAlign: "right" }}>
                  <button className="ws-btn sm primary" onClick={() => onApprove(m.id)}>Approve</button>{" "}
                  <button className="ws-btn sm danger" onClick={() => onDismiss(m.id)}>Dismiss</button>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TrashView({ trashed, onRestore, onDelete, canEdit }: { trashed: MemoryListItem[]; onRestore: (id: string) => void; onDelete: (id: string) => void; canEdit: boolean }) {
  if (trashed.length === 0) return <div className="ws-empty"><h2>Trash is empty</h2><p>Deleted docs appear here and can be restored.</p></div>;
  return (
    <table className="ws-table">
      <thead><tr><th>Title</th><th>Type</th>{canEdit && <th></th>}</tr></thead>
      <tbody>
        {trashed.map((m) => (
          <tr key={m.id}>
            <td><b>{m.title}</b></td>
            <td><span className="ty-pill"><span className="ty-dot" style={{ background: TYPE_COLOR[m.type] }} />{m.type}</span></td>
            {canEdit && (
              <td style={{ textAlign: "right" }}>
                <button className="ws-btn sm" onClick={() => onRestore(m.id)}>Restore</button>{" "}
                <button className="ws-btn sm danger" onClick={() => onDelete(m.id)}>Delete forever</button>
              </td>
            )}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
