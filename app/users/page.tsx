"use client";

import { useCallback, useEffect, useState } from "react";
import * as api from "@/lib/api";
import type { User } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

const blank = { name: "", email: "", role: "user", password: "" };

export default function UsersPage() {
  const { user: me } = useAuth();
  const [users, setUsers] = useState<User[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ ...blank });
  const [editing, setEditing] = useState<User | null>(null);
  const [tempPw, setTempPw] = useState<string | null>(null);
  const [resetFor, setResetFor] = useState<User | null>(null);
  const [resetPw, setResetPw] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try { setUsers(await api.getUsers()); setErr(null); }
    catch (e) { setErr((e as Error).message); }
  }, []);
  useEffect(() => { load(); }, [load]);

  if (me?.role !== "admin") {
    return <div className="page-body"><div className="backend-warn">Admins only.</div></div>;
  }

  const addUser = async () => {
    setBusy(true); setTempPw(null);
    try {
      const r = await api.createUser({ name: form.name.trim(), email: form.email.trim(), role: form.role, password: form.password || undefined });
      if (r.temporary_password) setTempPw(r.temporary_password);
      setForm({ ...blank }); setAdding(false); load();
    } catch (e) { alert((e as Error).message); }
    finally { setBusy(false); }
  };
  const saveEdit = async () => {
    if (!editing) return;
    setBusy(true);
    try { await api.updateUser(editing.id, { name: editing.name, email: editing.email, role: editing.role, is_active: editing.is_active }); setEditing(null); load(); }
    catch (e) { alert((e as Error).message); }
    finally { setBusy(false); }
  };
  const toggleActive = async (u: User) => {
    try { await api.updateUser(u.id, { is_active: !u.is_active }); load(); }
    catch (e) { alert((e as Error).message); }
  };
  const del = async (u: User) => {
    if (!confirm(`Delete ${u.name} (${u.email})? This cannot be undone.`)) return;
    try { await api.deleteUser(u.id); load(); }
    catch (e) { alert((e as Error).message); }
  };
  const doReset = async () => {
    if (!resetFor) return;
    setBusy(true);
    try { await api.resetUserPassword(resetFor.id, resetPw); setResetFor(null); setResetPw(""); alert("Password reset."); }
    catch (e) { alert((e as Error).message); }
    finally { setBusy(false); }
  };

  return (
    <div className="page-body">
      <div className="page-head">
        <div><h1>User Management</h1><p className="page-sub">Admin only · create, edit, deactivate, delete, reset passwords</p></div>
        <button className="btn open" onClick={() => { setAdding(true); setTempPw(null); }}>+ Add User</button>
      </div>

      {err && <div className="backend-warn">⚠ {err}</div>}
      {tempPw && <div className="team-error" style={{ maxWidth: 640 }}>Temporary password (share once, won’t be shown again): <strong>{tempPw}</strong></div>}

      {adding && (
        <div className="panel edit-panel">
          <div className="panel-head"><h2>New user</h2></div>
          <div className="form-grid">
            <input className="af-input" placeholder="Name *" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
            <input className="af-input" placeholder="Email *" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
            <select className="af-input" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
              <option value="user">User</option><option value="admin">Admin</option>
            </select>
            <input className="af-input" type="password" placeholder="Password (blank = auto-generate)" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
          </div>
          <div className="af-actions">
            <button className="btn-mini primary" disabled={busy} onClick={addUser}>Create user</button>
            <button className="btn-mini" onClick={() => setAdding(false)}>Cancel</button>
          </div>
        </div>
      )}

      {resetFor && (
        <div className="panel edit-panel">
          <div className="panel-head"><h2>Reset password · {resetFor.name}</h2></div>
          <div className="key-row">
            <input className="af-input" type="password" placeholder="New password (min 6)" value={resetPw} onChange={(e) => setResetPw(e.target.value)} />
            <button className="btn-mini primary" disabled={busy || resetPw.length < 6} onClick={doReset}>Set password</button>
            <button className="btn-mini" onClick={() => setResetFor(null)}>Cancel</button>
          </div>
        </div>
      )}

      <div className="panel">
        <div className="table-wrap">
          <table className="leads-table">
            <thead><tr><th>Name</th><th>Email</th><th>Role</th><th>Status</th><th>Last login</th><th></th></tr></thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id}>
                  <td>{editing?.id === u.id ? <input className="af-input" value={editing.name} onChange={(e) => setEditing({ ...editing, name: e.target.value })} /> : <span className="lead-name">{u.name}{u.id === me?.id ? " (you)" : ""}</span>}</td>
                  <td>{editing?.id === u.id ? <input className="af-input" value={editing.email} onChange={(e) => setEditing({ ...editing, email: e.target.value })} /> : u.email}</td>
                  <td>{editing?.id === u.id ? (
                    <select className="af-input" value={editing.role} onChange={(e) => setEditing({ ...editing, role: e.target.value })}><option value="user">user</option><option value="admin">admin</option></select>
                  ) : <span className="lead-badge" style={{ color: u.role === "admin" ? "#f2c14e" : "#8a93a6", borderColor: u.role === "admin" ? "#f2c14e" : "#8a93a6" }}>{u.role}</span>}</td>
                  <td>{u.is_active ? <span style={{ color: "#7ee0a2" }}>Active</span> : <span style={{ color: "#ef8f8f" }}>Disabled</span>}</td>
                  <td className="muted">{u.last_login || "—"}</td>
                  <td className="row-actions">
                    {editing?.id === u.id ? (
                      <>
                        <button className="btn-mini primary" disabled={busy} onClick={saveEdit}>Save</button>
                        <button className="btn-mini" onClick={() => setEditing(null)}>Cancel</button>
                      </>
                    ) : (
                      <>
                        <button className="btn-mini" onClick={() => setEditing(u)}>Edit</button>
                        <button className="btn-mini" onClick={() => toggleActive(u)}>{u.is_active ? "Disable" : "Enable"}</button>
                        <button className="btn-mini" onClick={() => { setResetFor(u); setResetPw(""); }}>Reset PW</button>
                        <button className="btn-mini danger" onClick={() => del(u)}>Delete</button>
                      </>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
