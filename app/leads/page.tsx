"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import * as api from "@/lib/api";
import type { ApiLead } from "@/lib/api";
import { LEAD_STATUS_META, LEAD_STATUS_OPTIONS, leadStatusMeta } from "@/lib/api";
import LeadsTable from "@/components/dashboard/LeadsTable";
import PendingLeadsPanel from "@/components/ui/PendingLeadsPanel";
import LeadHunter from "@/components/ui/LeadHunter";
import WhatsAppPanel from "@/components/ui/WhatsAppPanel";

const FILTERS = [
  { key: "all", label: "All (active)" },
  { key: "verified", label: "Verified" },
  { key: "interested_awaiting_review", label: "Needs Review" },
  { key: "replied", label: "Replied" },
  { key: "mailed", label: "Mailed" },
  { key: "new", label: "New" },
  { key: "not_interested", label: "Not Interested" },
  { key: "rejected", label: "Rejected (hidden)" },
  // Contact-route filters. Most leads are phone-only, so being able to see
  // which can actually be emailed decides what outreach is even possible.
  { key: "has_email", label: "Has email" },
  { key: "no_email", label: "Phone only" },
];

// Filters applied in the browser rather than sent to the API as a status.
const CONTACT_FILTERS = new Set(["has_email", "no_email"]);

const blankLead = { business_name: "", niche: "", city: "", email: "", phone: "", status: "new" as string };

export default function LeadsPage() {
  const [leads, setLeads] = useState<ApiLead[]>([]);
  const [channel, setChannel] = useState<"leads" | "whatsapp">("leads");
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ ...blankLead });
  const [editing, setEditing] = useState<ApiLead | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const l = await api.getLeads(
        filter === "all" || CONTACT_FILTERS.has(filter) ? {} : { status: filter });
      setLeads(l); setErr(null);
    } catch (e) { setErr((e as Error).message); }
  }, [filter]);

  useEffect(() => { load(); }, [load]);

  const visible = useMemo(() => {
    let rows = leads;
    if (filter === "has_email") rows = rows.filter((l) => (l.email || "").trim());
    if (filter === "no_email") rows = rows.filter((l) => !(l.email || "").trim());
    if (!query.trim()) return rows;
    const q = query.toLowerCase();
    return rows.filter((l) => l.business_name.toLowerCase().includes(q) || l.niche.toLowerCase().includes(q));
  }, [leads, query, filter]);

  const addLead = async () => {
    if (!form.business_name.trim()) return;
    setBusy(true);
    try { await api.createLead(form); setAdding(false); setForm({ ...blankLead }); load(); }
    finally { setBusy(false); }
  };
  const saveEdit = async () => {
    if (!editing) return;
    setBusy(true);
    try {
      await api.updateLead(editing.id, { status: editing.status, notes: editing.notes, business_name: editing.business_name, niche: editing.niche, city: editing.city, email: editing.email, phone: editing.phone, call_scheduled: editing.call_scheduled });
      setEditing(null); load();
    } finally { setBusy(false); }
  };
  const del = async (l: ApiLead) => {
    if (!confirm(`Permanently delete "${l.business_name}"?`)) return;
    await api.deleteLead(l.id); load();
  };

  return (
    <div className="page-body">
      <div className="page-head">
        <div>
          <h1>CRM · Leads</h1>
          <p className="page-sub">Your prospect database — why each was collected and its remarks. Email lives in <a href="/outreach">Outreach</a>.</p>
        </div>
        <div className="controls">
          <button className="btn open" onClick={() => { setAdding(true); setEditing(null); }}>+ Add Lead</button>
        </div>
      </div>

      {err && <div className="backend-warn">⚠ Can’t reach backend ({err}).</div>}

      {/* Channel tabs: the email CRM, or the WhatsApp-reachable subset. */}
      <div className="filter-chips" style={{ marginBottom: 14 }}>
        <button className={`chip ${channel === "leads" ? "active" : ""}`} onClick={() => setChannel("leads")}>
          All leads
        </button>
        <button className={`chip ${channel === "whatsapp" ? "active" : ""}`} onClick={() => setChannel("whatsapp")}>
          WhatsApp leads
        </button>
      </div>

      {channel === "whatsapp" ? <WhatsAppPanel /> : (
      <>
      <LeadHunter onDone={load} />
      <PendingLeadsPanel onChanged={load} />

      <div className="toolbar">
        <div className="filter-chips">
          {FILTERS.map((f) => (
            <button key={f.key} className={`chip ${filter === f.key ? "active" : ""}`} onClick={() => setFilter(f.key)}
              style={f.key !== "all" && !CONTACT_FILTERS.has(f.key) && filter === f.key ? { borderColor: leadStatusMeta(f.key).color, color: leadStatusMeta(f.key).color } : undefined}>
              {f.label}
            </button>
          ))}
        </div>
        <input className="search" placeholder="Search business or niche…" value={query} onChange={(e) => setQuery(e.target.value)} />
      </div>

      {adding && (
        <div className="panel edit-panel">
          <div className="panel-head"><h2>New lead</h2></div>
          <div className="form-grid">
            <input className="af-input" placeholder="Business name *" value={form.business_name} onChange={(e) => setForm({ ...form, business_name: e.target.value })} />
            <input className="af-input" placeholder="Niche" value={form.niche} onChange={(e) => setForm({ ...form, niche: e.target.value })} />
            <input className="af-input" placeholder="City" value={form.city} onChange={(e) => setForm({ ...form, city: e.target.value })} />
            <input className="af-input" placeholder="Email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
            <select className="af-input" value={form.status} onChange={(e) => setForm({ ...form, status: e.target.value })}>
              {LEAD_STATUS_OPTIONS.map((s) => <option key={s} value={s}>{LEAD_STATUS_META[s].label}</option>)}
            </select>
          </div>
          <div className="af-actions">
            <button className="btn-mini primary" disabled={busy} onClick={addLead}>Create lead</button>
            <button className="btn-mini" onClick={() => setAdding(false)}>Cancel</button>
          </div>
        </div>
      )}

      {editing && (
        <div className="panel edit-panel">
          <div className="panel-head"><h2>Edit {editing.business_name} <span className="lead-id">{editing.id}</span></h2></div>
          <div className="form-grid">
            <input className="af-input" value={editing.business_name} onChange={(e) => setEditing({ ...editing, business_name: e.target.value })} />
            <input className="af-input" value={editing.niche} onChange={(e) => setEditing({ ...editing, niche: e.target.value })} />
            <input className="af-input" value={editing.city} onChange={(e) => setEditing({ ...editing, city: e.target.value })} />
            <input className="af-input" value={editing.email} onChange={(e) => setEditing({ ...editing, email: e.target.value })} />
            <select className="af-input" value={editing.status} onChange={(e) => setEditing({ ...editing, status: e.target.value })}>
              {LEAD_STATUS_OPTIONS.map((s) => <option key={s} value={s}>{LEAD_STATUS_META[s].label}</option>)}
            </select>
            <input className="af-input" placeholder="Notes" value={editing.notes} onChange={(e) => setEditing({ ...editing, notes: e.target.value })} />
            <input className="af-input" placeholder="Schedule call (e.g. 2026-08-01 15:00) — stub" value={editing.call_scheduled || ""} onChange={(e) => setEditing({ ...editing, call_scheduled: e.target.value })} />
          </div>
          <div className="af-actions">
            <button className="btn-mini primary" disabled={busy} onClick={saveEdit}>Save changes</button>
            <button className="btn-mini" onClick={() => setEditing(null)}>Cancel</button>
          </div>
        </div>
      )}

      <div className="panel">
        <div className="panel-head">
          <h2>Leads</h2>
          <span className="muted">{visible.length} shown</span>
        </div>
        <LeadsTable leads={visible} onEdit={(l) => { setEditing(l); setAdding(false); }} onDelete={del} />
      </div>
      </>
      )}
    </div>
  );
}
