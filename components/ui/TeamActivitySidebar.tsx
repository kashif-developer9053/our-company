"use client";

import { useState } from "react";
import type { LiveStatus, LiveAgent } from "@/lib/api";
import * as api from "@/lib/api";
import { roleLabel } from "@/lib/api";
import { STATUS_META, type AnyStatus } from "@/types/officeTypes";
import { useAuth } from "@/lib/auth-context";
import AgentConfigModal from "./AgentConfigModal";

interface Props {
  status: LiveStatus | null;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  onChanged: () => void; // refresh after add/edit/delete
}

const ROLE_OPTIONS = [
  { key: "researcher", label: "Researcher" },
  { key: "verifier", label: "Verifier" },
  { key: "outreach", label: "Outreach" },
  { key: "it_monitor", label: "IT Monitor" },
  { key: "supervisor", label: "Manager" },
  { key: "custom", label: "Custom" },
];

export default function TeamActivitySidebar({ status, selectedId, onSelect, onChanged }: Props) {
  const { user } = useAuth();
  const [collapsed, setCollapsed] = useState(false);
  const [configAgent, setConfigAgent] = useState<LiveAgent | null>(null);
  const [adding, setAdding] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // form fields
  const [fName, setFName] = useState("");
  const [fResp, setFResp] = useState("");
  const [fRole, setFRole] = useState("custom");

  const agents = status ? Object.values(status.agents) : [];

  const startAdd = () => {
    setAdding(true); setEditingId(null);
    setFName(""); setFResp(""); setFRole("custom");
  };
  const startEdit = (a: LiveAgent) => {
    setEditingId(a.id); setAdding(false);
    setFName(a.name); setFResp(a.responsibility); setFRole(a.role_key);
  };
  const cancel = () => { setAdding(false); setEditingId(null); };

  const submitAdd = async () => {
    if (!fName.trim()) return;
    setBusy(true);
    try {
      await api.createAgent({ name: fName.trim(), responsibility: fResp.trim(), role_key: fRole });
      cancel(); onChanged();
    } finally { setBusy(false); }
  };
  const submitEdit = async (id: string) => {
    setBusy(true);
    try {
      await api.updateAgent(id, { name: fName.trim(), responsibility: fResp.trim(), role_key: fRole });
      cancel(); onChanged();
    } finally { setBusy(false); }
  };
  const remove = async (a: LiveAgent) => {
    if (!confirm(`Delete custom agent "${a.name}"? This cannot be undone.`)) return;
    setBusy(true);
    try { await api.deleteAgent(a.id); cancel(); onChanged(); }
    catch (e) { alert((e as Error).message); }
    finally { setBusy(false); }
  };

  if (collapsed) {
    return (
      <aside className="team-sidebar collapsed">
        <button className="team-collapse" onClick={() => setCollapsed(false)} title="Expand">»</button>
      </aside>
    );
  }

  const renderForm = (mode: "add" | "edit", id?: string) => (
    <div className="agent-form">
      <input className="af-input" placeholder="Agent name" value={fName} onChange={(e) => setFName(e.target.value)} />
      <textarea className="af-input" placeholder="Responsibility" rows={2} value={fResp} onChange={(e) => setFResp(e.target.value)} />
      <select className="af-input" value={fRole} onChange={(e) => setFRole(e.target.value)}>
        {ROLE_OPTIONS.map((r) => <option key={r.key} value={r.key}>{r.label}</option>)}
      </select>
      <div className="af-actions">
        <button className="btn-mini primary" disabled={busy} onClick={() => (mode === "add" ? submitAdd() : submitEdit(id!))}>
          {mode === "add" ? "Add agent" : "Save"}
        </button>
        <button className="btn-mini" disabled={busy} onClick={cancel}>Cancel</button>
      </div>
    </div>
  );

  return (
    <aside className="team-sidebar">
      <div className="team-head">
        <span>Team Activity</span>
        <div className="team-head-actions">
          <button className="btn-mini" onClick={adding ? cancel : startAdd} title="Add agent">
            {adding ? "×" : "＋ Add"}
          </button>
          <button className="team-collapse" onClick={() => setCollapsed(true)} title="Collapse">«</button>
        </div>
      </div>

      <div className="team-cards">
        {adding && <div className="team-card expanded">{renderForm("add")}</div>}

        {!status && <div className="muted small" style={{ padding: 10 }}>Connecting to backend…</div>}

        {agents.map((a) => {
          const meta = STATUS_META[(a.status as AnyStatus)] || STATUS_META.offline;
          const expanded = selectedId === a.id;
          const editing = editingId === a.id;

          return (
            <div key={a.id} className={`team-card ${expanded ? "expanded" : ""}`}>
              <div className="team-card-head-row">
                <button className="team-card-head" onClick={() => onSelect(expanded ? null : a.id)}>
                  <div className="team-card-title">
                    <span className="team-name">{a.name}</span>
                    <span className="team-role">— {roleLabel(a.role_key)}</span>
                  </div>
                </button>
                <div className="team-card-right">
                  <span className="team-status" style={{ color: meta.color, borderColor: meta.color }}>
                    <span className="dot" style={{ background: meta.color }} />
                    {meta.label}
                  </span>
                  <button className="pencil" title="Edit agent" onClick={() => (editing ? cancel() : startEdit(a))}>✎</button>
                  {user?.role === "admin" && <button className="pencil" title="Configure AI + instructions" onClick={() => setConfigAgent(a)}>⚙</button>}
                </div>
              </div>

              <div className="team-task">
                {a.status === "working" && a.task ? <span className="task-live">▸ {a.task}</span> : (a.responsibility || "No description set.")}
              </div>

              {editing && (
                <div className="team-detail">
                  {renderForm("edit", a.id)}
                  {a.is_default ? (
                    <div className="muted small" style={{ marginTop: 6 }}>Default agent — editable but cannot be deleted.</div>
                  ) : (
                    <button className="btn-mini danger" disabled={busy} onClick={() => remove(a)}>Delete agent</button>
                  )}
                </div>
              )}

              {expanded && !editing && (
                <div className="team-detail">
                  <div className="team-log-title">Details</div>
                  <ul className="team-log">
                    <li><span className="log-time">role</span><span className="log-msg">{roleLabel(a.role_key)} ({a.role_key})</span></li>
                    <li><span className="log-time">type</span><span className="log-msg">{a.is_default ? "Default (core)" : "Custom (CEO-added)"}</span></li>
                    <li><span className="log-time">status</span><span className="log-msg">{meta.label}</span></li>
                  </ul>
                  <div className="muted small" style={{ marginTop: 8 }}>Live activity log arrives in Phase 3.</div>
                </div>
              )}
            </div>
          );
        })}
      </div>

      {configAgent && <AgentConfigModal agent={configAgent} onClose={() => setConfigAgent(null)} onChanged={onChanged} />}
    </aside>
  );
}
