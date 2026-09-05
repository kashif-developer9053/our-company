"use client";

import { useCallback, useEffect, useState } from "react";
import * as api from "@/lib/api";
import type { AiProvider, CompanyProfile } from "@/lib/api";

// ---- AI Providers ----------------------------------------------------------
export function ProvidersSection() {
  const [providers, setProviders] = useState<AiProvider[]>([]);
  const [keys, setKeys] = useState<Record<string, string>>({});
  const [urls, setUrls] = useState<Record<string, string>>({});
  const [results, setResults] = useState<Record<string, { ok: boolean; message: string }>>({});
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => { try { setProviders(await api.getProviders()); } catch { /* */ } }, []);
  useEffect(() => { load(); }, [load]);

  const save = async (p: AiProvider) => {
    setBusy(p.provider_id);
    try { await api.saveProvider(p.provider_id, keys[p.provider_id]?.trim() || undefined, urls[p.provider_id] ?? (p.needs_base_url ? p.base_url : undefined)); setKeys({ ...keys, [p.provider_id]: "" }); await load(); }
    finally { setBusy(null); }
  };
  const test = async (id: string) => {
    setBusy(id + "t");
    try { setResults({ ...results, [id]: await api.testProvider(id) }); } finally { setBusy(null); }
  };
  const remove = async (id: string) => { if (!confirm(`Remove ${id} key?`)) return; await api.deleteProvider(id); load(); };

  return (
    <div className="settings-card">
      <div className="settings-card-head"><h2>AI Providers</h2></div>
      <p style={{ fontSize: 12.5, color: "#8a93a6", marginBottom: 10 }}>Connect any provider; assign per-agent in each agent’s AI Configuration. Keys are encrypted, never shown in full.</p>
      {providers.map((p) => (
        <div key={p.provider_id} className="provider-row">
          <div className="provider-head">
            <span className="lead-name">{p.display_name}</span>
            <span className={`soon-tag ${p.is_set ? "set" : ""}`}>{p.status}</span>
          </div>
          {p.needs_base_url && (
            <input className="af-input" placeholder="Base URL (e.g. https://your-router/v1)" value={urls[p.provider_id] ?? p.base_url} onChange={(e) => setUrls({ ...urls, [p.provider_id]: e.target.value })} style={{ marginBottom: 6 }} />
          )}
          <div className="key-row">
            <input className="af-input" type="password" placeholder={p.is_set ? "Replace key…" : `${p.display_name} API key…`} value={keys[p.provider_id] || ""} onChange={(e) => setKeys({ ...keys, [p.provider_id]: e.target.value })} />
            <button className="btn-mini primary" disabled={busy === p.provider_id} onClick={() => save(p)}>Save</button>
            <button className="btn-mini" disabled={busy === p.provider_id + "t"} onClick={() => test(p.provider_id)}>Test</button>
            {p.is_set && <button className="btn-mini danger" onClick={() => remove(p.provider_id)}>Remove</button>}
          </div>
          {results[p.provider_id] && <div className={`test-result ${results[p.provider_id].ok ? "ok" : "bad"}`} style={{ marginTop: 6 }}>{results[p.provider_id].ok ? "✓ " : "✕ "}{results[p.provider_id].message}</div>}
          <div className="muted small" style={{ marginTop: 4 }}>Models: {p.available_models.join(", ") || "(set base URL / add manually)"}</div>
        </div>
      ))}
    </div>
  );
}

// ---- Company Profile -------------------------------------------------------
export function CompanySection() {
  const [p, setP] = useState<CompanyProfile | null>(null);
  const [linksText, setLinksText] = useState("");
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    api.getCompany().then((cp) => { setP(cp); setLinksText(cp.contact_links.map((l) => `${l.label} | ${l.url}`).join("\n")); }).catch(() => {});
  }, []);
  if (!p) return null;

  const save = async () => {
    setBusy(true);
    const contact_links = linksText.split("\n").map((l) => l.split("|")).filter((a) => a[1]).map((a) => ({ label: a[0].trim(), url: a[1].trim() }));
    try { await api.saveCompany({ ...p, contact_links }); setSaved(true); setTimeout(() => setSaved(false), 2000); } finally { setBusy(false); }
  };

  return (
    <div className="settings-card">
      <div className="settings-card-head"><h2>Company Profile</h2>{saved && <span className="soon-tag set">Saved</span>}</div>
      <p style={{ fontSize: 12.5, color: "#8a93a6", marginBottom: 10 }}>Used by Agent 3 (outreach voice/links) and Agent 1 (which niches fit your services).</p>
      <div className="form-grid">
        <input className="af-input" placeholder="Company name" value={p.company_name} onChange={(e) => setP({ ...p, company_name: e.target.value })} />
        <input className="af-input" placeholder="Website" value={p.website} onChange={(e) => setP({ ...p, website: e.target.value })} />
        <input className="af-input" placeholder="Tagline" value={p.tagline} onChange={(e) => setP({ ...p, tagline: e.target.value })} />
        <input className="af-input" placeholder="Services (comma-separated)" value={p.services_offered.join(", ")} onChange={(e) => setP({ ...p, services_offered: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })} />
        <input className="af-input" placeholder="Tone (e.g. friendly and professional)" value={p.tone_preference} onChange={(e) => setP({ ...p, tone_preference: e.target.value })} />
      </div>
      <label className="build-label" style={{ marginTop: 12 }}>Contact details Agent 3 signs every cold email with</label>
      <div className="form-grid">
        <input className="af-input" placeholder="Contact email" value={p.contact_email || ""} onChange={(e) => setP({ ...p, contact_email: e.target.value })} />
        <input className="af-input" placeholder="WhatsApp number" value={p.whatsapp || ""} onChange={(e) => setP({ ...p, whatsapp: e.target.value })} />
        <input className="af-input" placeholder="Phone" value={p.phone || ""} onChange={(e) => setP({ ...p, phone: e.target.value })} />
        <input className="af-input" placeholder="Your name (sign-off)" value={p.sender_name || ""} onChange={(e) => setP({ ...p, sender_name: e.target.value })} />
        <input className="af-input" placeholder="Your title (e.g. Director)" value={p.sender_title || ""} onChange={(e) => setP({ ...p, sender_title: e.target.value })} />
        <input className="af-input" placeholder="Logo image URL (shown in emails)" value={p.logo_url || ""} onChange={(e) => setP({ ...p, logo_url: e.target.value })} />
      </div>
      <label className="build-label" style={{ marginTop: 10 }}>Contact links (one per line: Label | URL)</label>
      <textarea className="af-input" rows={2} value={linksText} onChange={(e) => setLinksText(e.target.value)} placeholder="Book a call | https://cal.com/you" />
      <label className="build-label" style={{ marginTop: 10 }}>Outreach template / structure (style guide for Agent 3)</label>
      <textarea className="af-input" rows={3} value={p.outreach_template} onChange={(e) => setP({ ...p, outreach_template: e.target.value })} />
      <div style={{ marginTop: 10 }}><button className="btn-mini primary" disabled={busy} onClick={save}>Save profile</button></div>
    </div>
  );
}

// ---- Usage & Cost ----------------------------------------------------------
export function UsageSection() {
  const [range, setRange] = useState("week");
  const [data, setData] = useState<Awaited<ReturnType<typeof api.getUsage>> | null>(null);
  useEffect(() => { api.getUsage(range).then(setData).catch(() => {}); }, [range]);

  return (
    <div className="settings-card">
      <div className="settings-card-head">
        <h2>Usage &amp; Cost</h2>
        <div className="range-toggle">
          {["day", "week", "month"].map((r) => <button key={r} className={`range-btn ${range === r ? "active" : ""}`} onClick={() => setRange(r)}>{r}</button>)}
        </div>
      </div>
      {!data ? <div className="muted small">Loading…</div> : (
        <>
          <div className="usage-totals">{data.total_calls} calls · est. ${data.total_cost} this {range}</div>
          <div className="table-wrap">
            <table className="leads-table">
              <thead><tr><th>Agent</th><th>Calls</th><th>In tokens</th><th>Out tokens</th><th>Providers</th><th>Est. cost</th></tr></thead>
              <tbody>
                {Object.entries(data.by_agent).map(([aid, a]) => (
                  <tr key={aid}><td>{aid}</td><td>{a.calls}</td><td>{a.input_tokens}</td><td>{a.output_tokens}</td><td className="muted">{Object.keys(a.providers).join(", ")}</td><td>${a.est_cost}</td></tr>
                ))}
                {Object.keys(data.by_agent).length === 0 && <tr><td colSpan={6} className="muted" style={{ padding: 14 }}>No AI calls logged in this range yet.</td></tr>}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
