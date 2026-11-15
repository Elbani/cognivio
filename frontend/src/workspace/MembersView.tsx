import { useState } from "react";
import { apiRequest, Member, Role } from "../lib/api";

const ROLES: Role[] = ["owner", "admin", "editor", "viewer"];

export function MembersView({
  token,
  orgId,
  unlocked,
  members,
  canManage,
  currentUserId,
  contactEmail,
  onChanged
}: {
  token: string;
  orgId: string;
  /** Teams plan, or the viewer is a platform admin: team features are available. */
  unlocked: boolean;
  contactEmail: string | null;
  members: Member[];
  canManage: boolean;
  currentUserId: string | null;
  onChanged: () => void;
}) {
  const hasTeams = unlocked;
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<Role>("editor");
  const [error, setError] = useState("");

  async function invite() {
    setError("");
    if (!email.trim()) return;
    try {
      await apiRequest(`/api/orgs/${orgId}/members`, { method: "POST", token, body: { email: email.trim(), role } });
      setEmail("");
      onChanged();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to add member");
    }
  }
  async function changeRole(userId: string, r: Role) {
    await apiRequest(`/api/orgs/${orgId}/members/${userId}`, { method: "PATCH", token, body: { role: r } });
    onChanged();
  }
  async function remove(userId: string) {
    if (!window.confirm("Remove this member from the organization?")) return;
    await apiRequest(`/api/orgs/${orgId}/members/${userId}`, { method: "DELETE", token });
    onChanged();
  }

  return (
    <div>
      <p style={{ color: "var(--text-secondary)", fontSize: 14, marginTop: 0 }}>
        People in this organization and what they can do. Roles apply across all teams.
      </p>

      {canManage && hasTeams && (
        <div className="ws-filters" style={{ marginBottom: 18 }}>
          <span className="ws-search"><input placeholder="Add by email (existing account)…" value={email} onChange={(e) => setEmail(e.target.value)} /></span>
          <select className="ws-select" value={role} onChange={(e) => setRole(e.target.value as Role)}>
            {ROLES.filter((r) => r !== "owner").map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
          <button className="ws-btn primary" onClick={invite}>Add member</button>
        </div>
      )}
      {canManage && !hasTeams && (
        <div className="ws-card" style={{ marginBottom: 18, display: "flex", alignItems: "center", gap: 16, flexWrap: "wrap" }}>
          <div style={{ flex: 1, minWidth: 240 }}>
            <strong>Free plan: one person</strong>
            <div style={{ color: "var(--text-secondary)", fontSize: 13, marginTop: 4 }}>
              Inviting teammates and shared org knowledge are on the <b>Teams</b> plan. {contactEmail ? <>Write to <a href={`mailto:${contactEmail}?subject=Cognivio%20for%20teams`}>{contactEmail}</a> to turn it on for this organization.</> : "Ask your administrator to turn it on for this organization."}
            </div>
          </div>
        </div>
      )}
      {error && <div className="ws-empty-sm" style={{ color: "#b91c1c" }}>{error}</div>}

      <table className="ws-table">
        <thead><tr><th>Name</th><th>Email</th><th>Role</th>{canManage && <th></th>}</tr></thead>
        <tbody>
          {members.filter((m) => m.teamId == null).map((m) => (
            <tr key={m.userId}>
              <td><b>{m.name}</b>{m.userId === currentUserId ? " (you)" : ""}</td>
              <td style={{ color: "var(--text-secondary)" }}>{m.email}</td>
              <td>
                {canManage && m.userId !== currentUserId ? (
                  <select className="ws-role-select" value={m.role} onChange={(e) => changeRole(m.userId, e.target.value as Role)}>
                    {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                  </select>
                ) : <span className="ty-pill">{m.role}</span>}
              </td>
              {canManage && (
                <td style={{ textAlign: "right" }}>
                  {m.userId !== currentUserId && <button className="ws-btn sm danger" onClick={() => remove(m.userId)}>Remove</button>}
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
