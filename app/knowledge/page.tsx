"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import * as api from "@/lib/api";
import type { KbEntry, LiveAgent } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

export default function KnowledgePage() {
  const { user } = useAuth();
  const [entries, setEntries] = useState<KbEntry[]>([]);
  const [agents, setAgents] = useState<LiveAgent[]>([]);
  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [scope, setScope] = useState("global");
  const [agentId, setAgentId] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement | null>(null);

  const load = useCallback(async () => {
    try { setEntries(await api.getKb()); setAgents(await api.getAgents()); setErr(null); }
    catch (e) { setErr((e as Error).message); }
  }, []);
  useEffect(() => { if (user?.role === "admin") load(); }, [load, user]);

  if (user?.role !== "admin") return <div className="page-body"><div className="backend-warn">Admins only.</div></div>;

  const addText = async () => {
    if (!text.trim()) return;
    setBusy(true);
    try { await api.addKbText(title.trim() || "Untitled", text.trim(), scope, scope === "agent_specific" ? agentId : null); setTitle(""); setText(""); load(); }
    catch (e) { alert((e as Error).message); } finally { setBusy(false); }
  };
  const upload = async (f: File) => {
    setBusy(true);
    try { await api.uploadKb(f, scope, scope === "agent_specific" ? agentId : "", title.trim()); setTitle(""); load(); }
    catch (e) { alert((e as Error).message); } finally { setBusy(false); if (fileRef.current) fileRef.current.value = ""; }
  };

  return (
    <div className="page-body">
      <div className="page-head"><div><h1>Knowledge Base</h1><p className="page-sub">Grounding docs agents use when reasoning. Scope globally or to one agent.</p></div></div>
      {err && <div className="backend-warn">⚠ {err}</div>}

      <div className="panel">
        <div className="panel-head"><h2>Add knowledge</h2></div>
        <div className="grow-form">
          <input className="af-input" placeholder="Title" value={title} onChange={(e) => setTitle(e.target.value)} />
          <div className="key-row">
            <select className="af-input" value={scope} onChange={(e) => setScope(e.target.value)} style={{ flex: "0 0 220px" }}>
              <option value="global">Available to all agents</option>
              <option value="agent_specific">Specific to an agent</option>
            </select>
            {scope === "agent_specific" && (
              <select className="af-input" value={agentId} onChange={(e) => setAgentId(e.target.value)}>
                <option value="">Select agent…</option>
                {agents.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
              </select>
            )}
          </div>
          <textarea className="af-input" rows={3} placeholder="Paste text knowledge here…" value={text} onChange={(e) => setText(e.target.value)} />
          <div className="key-row">
            <button className="btn-mini primary" disabled={busy || !text.trim()} onClick={addText}>Add text</button>
            <span className="muted small">or upload a file (PDF / DOCX / TXT):</span>
            <input ref={fileRef} type="file" accept=".pdf,.docx,.txt" onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
          </div>
        </div>
      </div>

      <div className="panel">
        <div className="panel-head"><h2>Entries</h2><span className="muted">{entries.length}</span></div>
        <div className="table-wrap">
          <table className="leads-table">
            <thead><tr><th>Title</th><th>Type</th><th>Scope</th><th>Size</th><th></th></tr></thead>
            <tbody>
              {entries.map((e) => (
                <tr key={e.id}>
                  <td className="lead-name">{e.title}{e.original_filename ? <span className="lead-id">{e.original_filename}</span> : null}</td>
                  <td>{e.content_type}</td>
                  <td>{e.scope === "global" ? "All agents" : `→ ${agents.find((a) => a.id === e.agent_id)?.name || e.agent_id}`}</td>
                  <td className="muted">{e.chars} chars</td>
                  <td className="row-actions"><button className="btn-mini danger" onClick={async () => { await api.deleteKb(e.id); load(); }}>Delete</button></td>
                </tr>
              ))}
              {entries.length === 0 && <tr><td colSpan={5} className="muted" style={{ padding: 14 }}>No knowledge added yet.</td></tr>}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
