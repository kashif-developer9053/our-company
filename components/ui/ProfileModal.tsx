"use client";

import { useState } from "react";
import * as api from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

// "My Profile" — available to everyone (admin included). Update your own name,
// and change your own password (current password required as a safety check).
export default function ProfileModal({ onClose }: { onClose: () => void }) {
  const { user, refreshMe } = useAuth();
  const [name, setName] = useState(user?.name ?? "");
  const [cur, setCur] = useState("");
  const [next, setNext] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  const saveName = async () => {
    setBusy(true); setMsg(null);
    try { await api.updateMyProfile({ name: name.trim() }); await refreshMe(); setMsg({ ok: true, text: "Profile updated." }); }
    catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
    finally { setBusy(false); }
  };
  const savePw = async () => {
    setBusy(true); setMsg(null);
    try { await api.changeMyPassword(cur, next); setCur(""); setNext(""); setMsg({ ok: true, text: "Password changed." }); }
    catch (e) { setMsg({ ok: false, text: (e as Error).message }); }
    finally { setBusy(false); }
  };

  return (
    <div className="chat-overlay" onClick={onClose}>
      <div className="chat-window" onClick={(e) => e.stopPropagation()} style={{ width: 400 }}>
        <div className="chat-head">
          <div>
            <div className="name">My Profile</div>
            <div className="role">{user?.email} · {user?.role}</div>
          </div>
          <button className="x" onClick={onClose}>×</button>
        </div>

        <div className="profile-section">
          <label>Name</label>
          <div className="key-row">
            <input className="af-input" value={name} onChange={(e) => setName(e.target.value)} />
            <button className="btn-mini primary" disabled={busy} onClick={saveName}>Save</button>
          </div>
        </div>

        <div className="profile-section">
          <label>Change password</label>
          <input className="af-input" type="password" placeholder="Current password" value={cur} onChange={(e) => setCur(e.target.value)} />
          <input className="af-input" type="password" placeholder="New password (min 6)" value={next} onChange={(e) => setNext(e.target.value)} style={{ marginTop: 6 }} />
          <button className="btn-mini primary" disabled={busy || !cur || next.length < 6} onClick={savePw} style={{ marginTop: 8 }}>Update password</button>
        </div>

        {msg && <div className={`test-result ${msg.ok ? "ok" : "bad"}`} style={{ marginTop: 4 }}>{msg.text}</div>}
      </div>
    </div>
  );
}
