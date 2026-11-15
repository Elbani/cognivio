import { useEffect, useRef, useState } from "react";
import { apiRequest, Org, Team } from "../lib/api";

// The org and team switcher at the top of the sidebar: one button that names where you
// are, and one menu that lists every organization with its teams, the current one ticked,
// and the create actions right where they apply. Enterprise-only actions show as locked
// instead of failing after the click.
export function ScopeMenu({
  token, orgs, teams, orgId, teamId, canManage, canAddOrg, canAddTeam,
  onSelectOrg, onSelectTeam, onNewOrg, onNewTeam, onRenameOrg, onRenameTeam
}: {
  token: string;
  orgs: Org[];
  teams: Team[];
  orgId: string | null;
  teamId: string | null;
  canManage: boolean;
  canAddOrg: boolean;
  canAddTeam: boolean;
  onSelectOrg: (id: string) => void;
  onSelectTeam: (orgId: string, teamId: string) => void;
  onNewOrg: () => void;
  onNewTeam: () => void;
  onRenameOrg: () => void;
  onRenameTeam: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [otherTeams, setOtherTeams] = useState<Record<string, Team[]>>({});
  const ref = useRef<HTMLDivElement>(null);
  const currentOrg = orgs.find((o) => o.id === orgId) ?? null;
  const currentTeam = teams.find((t) => t.id === teamId) ?? null;

  useEffect(() => {
    if (!open) return;
    function onDoc(e: globalThis.MouseEvent) { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); }
    function onKey(e: KeyboardEvent) { if (e.key === "Escape") setOpen(false); }
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDoc); document.removeEventListener("keydown", onKey); };
  }, [open]);

  // Teams of the other organizations load only when the menu opens; the current org's
  // teams are already in hand.
  useEffect(() => {
    if (!open) return;
    orgs.filter((o) => o.id !== orgId && !otherTeams[o.id]).forEach((o) => {
      apiRequest<Team[]>(`/api/orgs/${o.id}/teams`, { token })
        .then((t) => setOtherTeams((cur) => ({ ...cur, [o.id]: t })))
        .catch(() => setOtherTeams((cur) => ({ ...cur, [o.id]: [] })));
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, orgs, orgId]);

  const locked = !canAddOrg || !canAddTeam;

  return (
    <div className="ws-scope" ref={ref}>
      <button type="button" className={`ws-scope-btn${open ? " open" : ""}`} onClick={() => setOpen((v) => !v)} aria-haspopup="menu" aria-expanded={open} data-tour="switcher">
        <span className="ws-scope-names">
          <span className="ws-scope-org">{currentOrg?.name ?? "No organization"}</span>
          <span className="ws-scope-team">{currentTeam?.name ?? "No team"}</span>
        </span>
        <span className="ws-scope-chev" aria-hidden="true">⌄</span>
      </button>

      {open && (
        <div className="ws-scope-pop" role="menu">
          {orgs.map((o) => {
            const isCurrent = o.id === orgId;
            const list = isCurrent ? teams : otherTeams[o.id];
            return (
              <div key={o.id} className="ws-scope-group">
                <div className="ws-scope-head">
                  <span className="ws-scope-headname">{o.name}</span>
                  {o.plan === "enterprise" && <span className="ws-scope-tag">Enterprise</span>}
                  {isCurrent && canManage && (
                    <button type="button" className="ws-scope-act" onClick={() => { setOpen(false); onRenameOrg(); }}>Rename</button>
                  )}
                </div>
                {list === undefined && <div className="ws-scope-row muted">Loading teams…</div>}
                {list?.length === 0 && <div className="ws-scope-row muted">No teams yet</div>}
                {list?.map((t) => {
                  const on = isCurrent && t.id === teamId;
                  return (
                    <div key={t.id} className={`ws-scope-row${on ? " on" : ""}`}>
                      <button type="button" className="ws-scope-pick" role="menuitemradio" aria-checked={on} onClick={() => { setOpen(false); if (!on) onSelectTeam(o.id, t.id); }}>
                        <span className="ws-scope-tick" aria-hidden="true">{on ? "✓" : ""}</span>
                        <span className="ws-scope-teamname">{t.name}</span>
                      </button>
                      {on && canManage && (
                        <button type="button" className="ws-scope-act" onClick={() => { setOpen(false); onRenameTeam(); }}>Rename</button>
                      )}
                    </div>
                  );
                })}
                {isCurrent ? (
                  <button type="button" className="ws-scope-new" disabled={!canAddTeam} onClick={() => { setOpen(false); onNewTeam(); }}>
                    <span className="ws-scope-tick" aria-hidden="true">+</span>New team
                    {!canAddTeam && <span className="ws-scope-tag lock">Enterprise</span>}
                  </button>
                ) : (
                  <button type="button" className="ws-scope-new" onClick={() => { setOpen(false); onSelectOrg(o.id); }}>
                    <span className="ws-scope-tick" aria-hidden="true">→</span>Switch to {o.name}
                  </button>
                )}
              </div>
            );
          })}

          <div className="ws-scope-foot">
            <button type="button" className="ws-scope-new" disabled={!canAddOrg} onClick={() => { setOpen(false); onNewOrg(); }}>
              <span className="ws-scope-tick" aria-hidden="true">+</span>New organization
              {!canAddOrg && <span className="ws-scope-tag lock">Enterprise</span>}
            </button>
            {locked && (
              <p className="ws-scope-note">The Free plan is one organization with one team. For more, ask your administrator.</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
