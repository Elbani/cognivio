import { useState } from "react";
import { apiRequest, Org, Team, User } from "../lib/api";

type Props = {
  token: string;
  user: User | null;
  org: Org | null;
  team: Team | null;
  canManage: boolean;
  theme: "dark" | "light";
  onTheme: (theme: "dark" | "light") => void;
  onUserUpdated: (user: User) => void;
  onOrgUpdated: (org: Org) => void;
  onTeamUpdated: (team: Team) => void;
  onOpenHelp: () => void;
  onSignOut: () => void;
  docCount: number;
  onWiped: () => void;
};

export function SettingsView({
  token, user, org, team, canManage, theme, onTheme, onUserUpdated, onOrgUpdated, onTeamUpdated, onOpenHelp, onSignOut, docCount, onWiped
}: Props) {
  return (
    <div className="settings">
      <ProfileSection token={token} user={user} onUserUpdated={onUserUpdated} />
      <PasswordSection token={token} />
      <AppearanceSection theme={theme} onTheme={onTheme} />
      {team && <TeamKbSection token={token} team={team} canManage={canManage} onTeamUpdated={onTeamUpdated} />}
      {org && <OrganizationSection token={token} org={org} canManage={canManage} onOrgUpdated={onOrgUpdated} />}
      {team && canManage && <DangerZoneSection token={token} team={team} docCount={docCount} onWiped={onWiped} />}
      <AboutSection onOpenHelp={onOpenHelp} onSignOut={onSignOut} />
    </div>
  );
}

function DangerZoneSection({ token, team, docCount, onWiped }: {
  token: string; team: Team; docCount: number; onWiped: () => void;
}) {
  const [confirming, setConfirming] = useState(false);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const ready = text.trim() === team.name;

  function reset() {
    setConfirming(false); setText("");
  }

  async function wipe() {
    if (!ready || busy) return;
    setBusy(true); setMsg(null);
    try {
      const { deleted } = await apiRequest<{ deleted: number }>(
        `/api/teams/${team.id}/memories/all`, { method: "DELETE", token }
      );
      reset();
      setMsg({ kind: "ok", text: `Deleted ${deleted} document${deleted === 1 ? "" : "s"}.` });
      onWiped();
    } catch (e) {
      setMsg({ kind: "err", text: e instanceof Error ? e.message : "Could not delete documents." });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="settings-card danger-zone">
      <header>
        <h2>Danger zone</h2>
        <p>Irreversible actions for the <b>{team.name}</b> team.</p>
      </header>
      <div className="settings-field">
        <label>Delete all documents</label>
        <span className="settings-hint">
          Permanently removes every document in this team, including drafts, the project map,
          and anything in Trash, along with their version history. <b>This cannot be undone.</b>
          {" "}Folders are kept. {docCount > 0 && <>This team currently has <b>{docCount}</b> active document{docCount === 1 ? "" : "s"}.</>}
        </span>
        {!confirming ? (
          <div className="settings-actions left">
            <button className="ws-btn danger" onClick={() => { setMsg(null); setConfirming(true); }}>
              Delete all documents…
            </button>
            {msg && <span className={`settings-msg ${msg.kind}`}>{msg.text}</span>}
          </div>
        ) : (
          <>
            <input
              className="ws-input" value={text} autoFocus disabled={busy}
              onChange={(e) => setText(e.target.value)}
              placeholder={`Type "${team.name}" to confirm`}
            />
            <div className="settings-actions left">
              <button className="ws-btn danger" disabled={!ready || busy} onClick={wipe}>
                {busy ? "Deleting…" : "Permanently delete everything"}
              </button>
              <button className="ws-btn" disabled={busy} onClick={reset}>Cancel</button>
              {msg && <span className={`settings-msg ${msg.kind}`}>{msg.text}</span>}
            </div>
          </>
        )}
      </div>
    </section>
  );
}

function TeamKbSection({ token, team, canManage, onTeamUpdated }: {
  token: string; team: Team; canManage: boolean; onTeamUpdated: (t: Team) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const review = Boolean(team.agentWriteReview);

  async function toggle(next: boolean) {
    if (busy || !canManage) return;
    setBusy(true); setMsg(null);
    try {
      const updated = await apiRequest<Team>(`/api/teams/${team.id}`, {
        method: "PATCH", token, body: { agentWriteReview: next }
      });
      onTeamUpdated(updated);
      setMsg({ kind: "ok", text: next ? "Agent writes now need approval." : "Agent writes now go live." });
    } catch (e) {
      setMsg({ kind: "err", text: e instanceof Error ? e.message : "Could not save." });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="settings-card">
      <header>
        <h2>Knowledge base</h2>
        <p>{canManage ? "Control how agents write to this team's memory." : "You need an admin role to change these settings."}</p>
      </header>
      <div className="settings-field">
        <label>Review agent write-back</label>
        <div className="settings-segment">
          <button className={!review ? "active" : ""} disabled={busy || !canManage} onClick={() => toggle(false)}>Write live</button>
          <button className={review ? "active" : ""} disabled={busy || !canManage} onClick={() => toggle(true)}>Hold for review</button>
        </div>
        <span className="settings-hint">
          When on, docs an agent creates or updates land as <b>drafts</b>, hidden from agent retrieval until
          you approve them in the <b>Review</b> tab. Protects the KB from a confidently-wrong write.
        </span>
        {msg && <span className={`settings-msg ${msg.kind}`} style={{ marginTop: 8 }}>{msg.text}</span>}
      </div>
    </section>
  );
}

function ProfileSection({ token, user, onUserUpdated }: {
  token: string; user: User | null; onUserUpdated: (u: User) => void;
}) {
  const [name, setName] = useState(user?.name ?? "");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const dirty = name.trim() !== (user?.name ?? "") && name.trim().length > 0;

  async function save() {
    if (!dirty || busy) return;
    setBusy(true); setMsg(null);
    try {
      const updated = await apiRequest<User>("/api/auth/me", { method: "PATCH", token, body: { name: name.trim() } });
      onUserUpdated(updated);
      setMsg({ kind: "ok", text: "Profile updated." });
    } catch (e) {
      setMsg({ kind: "err", text: e instanceof Error ? e.message : "Could not save profile." });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="settings-card">
      <header><h2>Profile</h2><p>Your name and account email.</p></header>
      <div className="settings-field">
        <label>Name</label>
        <input className="ws-input" value={name} maxLength={80}
          onChange={(e) => setName(e.target.value)} placeholder="Your name" />
      </div>
      <div className="settings-field">
        <label>Email</label>
        <input className="ws-input" value={user?.email ?? ""} disabled readOnly />
        <span className="settings-hint">Your email can't be changed.</span>
      </div>
      <div className="settings-actions">
        {msg && <span className={`settings-msg ${msg.kind}`}>{msg.text}</span>}
        <span className="spacer" />
        <button className="ws-btn primary" disabled={!dirty || busy} onClick={save}>
          {busy ? "Saving…" : "Save changes"}
        </button>
      </div>
    </section>
  );
}

function PasswordSection({ token }: { token: string }) {
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  const tooShort = next.length > 0 && next.length < 8;
  const mismatch = confirm.length > 0 && next !== confirm;
  const ready = current.length > 0 && next.length >= 8 && next === confirm;

  async function save() {
    if (!ready || busy) return;
    setBusy(true); setMsg(null);
    try {
      await apiRequest("/api/auth/password", {
        method: "POST", token, body: { currentPassword: current, newPassword: next }
      });
      setCurrent(""); setNext(""); setConfirm("");
      setMsg({ kind: "ok", text: "Password changed." });
    } catch (e) {
      setMsg({ kind: "err", text: e instanceof Error ? e.message : "Could not change password." });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="settings-card">
      <header><h2>Password</h2><p>Use a strong password you don't reuse elsewhere.</p></header>
      <div className="settings-field">
        <label>Current password</label>
        <input className="ws-input" type="password" autoComplete="current-password"
          value={current} onChange={(e) => setCurrent(e.target.value)} />
      </div>
      <div className="settings-field">
        <label>New password</label>
        <input className="ws-input" type="password" autoComplete="new-password"
          value={next} onChange={(e) => setNext(e.target.value)} />
        {tooShort && <span className="settings-hint err">At least 8 characters.</span>}
      </div>
      <div className="settings-field">
        <label>Confirm new password</label>
        <input className="ws-input" type="password" autoComplete="new-password"
          value={confirm} onChange={(e) => setConfirm(e.target.value)} />
        {mismatch && <span className="settings-hint err">Passwords don't match.</span>}
      </div>
      <div className="settings-actions">
        {msg && <span className={`settings-msg ${msg.kind}`}>{msg.text}</span>}
        <span className="spacer" />
        <button className="ws-btn primary" disabled={!ready || busy} onClick={save}>
          {busy ? "Saving…" : "Change password"}
        </button>
      </div>
    </section>
  );
}

function AppearanceSection({ theme, onTheme }: { theme: "dark" | "light"; onTheme: (t: "dark" | "light") => void }) {
  return (
    <section className="settings-card">
      <header><h2>Appearance</h2><p>Choose how the workspace looks. Saved on this device.</p></header>
      <div className="settings-field">
        <label>Theme</label>
        <div className="settings-segment">
          <button className={theme === "dark" ? "active" : ""} onClick={() => onTheme("dark")}>☾ Dark</button>
          <button className={theme === "light" ? "active" : ""} onClick={() => onTheme("light")}>☀ Light</button>
        </div>
      </div>
    </section>
  );
}

function OrganizationSection({ token, org, canManage, onOrgUpdated }: {
  token: string; org: Org; canManage: boolean; onOrgUpdated: (o: Org) => void;
}) {
  const [name, setName] = useState(org.name);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const dirty = name.trim() !== org.name && name.trim().length > 0;

  async function save() {
    if (!dirty || busy) return;
    setBusy(true); setMsg(null);
    try {
      const body: Record<string, unknown> = { name: name.trim() };
      const updated = await apiRequest<Org>(`/api/orgs/${org.id}`, { method: "PATCH", token, body });
      onOrgUpdated(updated);
      setMsg({ kind: "ok", text: "Organization updated." });
    } catch (e) {
      setMsg({ kind: "err", text: e instanceof Error ? e.message : "Could not update organization." });
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="settings-card">
      <header><h2>Organization</h2><p>{canManage ? "Rename your organization." : "You need an admin role to change these settings."}</p></header>
      <div className="settings-field">
        <label>Name</label>
        <input className="ws-input" value={name} maxLength={120} disabled={!canManage}
          onChange={(e) => setName(e.target.value)} />
      </div>
      <div className="settings-field">
        <label>Your role</label>
        <input className="ws-input" value={org.role} disabled readOnly />
      </div>
      {canManage && (
        <div className="settings-actions">
          {msg && <span className={`settings-msg ${msg.kind}`}>{msg.text}</span>}
          <span className="spacer" />
          <button className="ws-btn primary" disabled={!dirty || busy} onClick={save}>
            {busy ? "Saving…" : "Save changes"}
          </button>
        </div>
      )}
    </section>
  );
}

function AboutSection({ onOpenHelp, onSignOut }: { onOpenHelp: () => void; onSignOut: () => void }) {
  return (
    <section className="settings-card">
      <header><h2>About</h2><p>Cognivio, the memory layer your AI agents read before they act.</p></header>
      <div className="settings-actions left">
        <button className="ws-btn" onClick={onOpenHelp}>Help &amp; API docs</button>
        <button className="ws-btn danger" onClick={onSignOut}>Sign out</button>
      </div>
    </section>
  );
}
