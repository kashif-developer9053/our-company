"use client";

import { useCallback, useEffect, useState } from "react";
import * as api from "@/lib/api";
import type { WhatsAppLead } from "@/lib/api";

// WhatsApp outreach desk. The app WRITES the message and opens WhatsApp with it
// pre-typed — the CEO presses send themselves. Nothing is automated, because
// automated sending is what gets numbers permanently banned.
const STATUSES = [
  { key: "all", label: "All" },
  { key: "not_contacted", label: "Not contacted" },
  { key: "message_sent", label: "Message sent" },
  { key: "replied", label: "Replied" },
  { key: "interested", label: "Interested" },
  { key: "not_interested", label: "Not interested" },
] as const;

const STATUS_COLOR: Record<string, string> = {
  not_contacted: "#8a93a6",
  message_sent: "#4aa3ff",
  replied: "#f2c14e",
  interested: "#5bbf87",
  not_interested: "#ef5350",
  invalid_number: "#6b7383",
};

const DAILY_SAFE_LIMIT = 30;

export default function WhatsAppPanel() {
  const [leads, setLeads] = useState<WhatsAppLead[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [filter, setFilter] = useState<string>("not_contacted");
  const [lang, setLang] = useState<"english" | "roman_urdu">("english");
  const [openId, setOpenId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [link, setLink] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const load = useCallback(async (f: string) => {
    try {
      const r = await api.getWhatsAppLeads(f);
      setLeads(r.leads); setCounts(r.counts);
    } catch { /* backend down */ }
  }, []);
  useEffect(() => { load(filter); }, [filter, load]);

  // Sent today — keeps the CEO under a volume that won't get the number banned.
  const sentToday = leads.filter((l) => {
    if (!l.sent_at) return false;
    return new Date(l.sent_at).toDateString() === new Date().toDateString();
  }).length;

  const prepare = async (l: WhatsAppLead) => {
    setBusy(l.id); setMsg(null); setOpenId(l.id); setDraft(""); setLink("");
    try {
      const r = await api.writeWhatsAppMessage(l.id, lang);
      if (!r.ok) { setMsg(`⚠ ${r.error}`); return; }
      setDraft(r.message || ""); setLink(r.link || "");
    } catch (e) { setMsg(`⚠ ${(e as Error).message}`); }
    finally { setBusy(null); }
  };

  // Re-encode the link whenever the CEO edits the text before sending.
  const linkFor = (l: WhatsAppLead) =>
    `https://wa.me/${l.number}?text=${encodeURIComponent(draft)}`;

  const openWhatsApp = async (l: WhatsAppLead) => {
    window.open(draft ? linkFor(l) : link, "_blank", "noopener");
    // Opening the chat is the moment worth recording — the CEO confirms below.
    setMsg("WhatsApp opened. Press send there, then mark it below.");
  };

  const setStatus = async (l: WhatsAppLead, status: string) => {
    setBusy(l.id);
    try {
      await api.updateWhatsAppLead(l.id, { status, message: draft || undefined });
      await load(filter);
    } finally { setBusy(null); }
  };

  const saveRemarks = async (l: WhatsAppLead, remarks: string) => {
    setBusy(l.id);
    try { await api.updateWhatsAppLead(l.id, { remarks }); await load(filter); }
    finally { setBusy(null); }
  };

  return (
    <div className="settings-card">
      <div className="settings-card-head">
        <h2>WhatsApp outreach</h2>
        <span className={`soon-tag ${sentToday >= DAILY_SAFE_LIMIT ? "" : "set"}`}>
          {sentToday}/{DAILY_SAFE_LIMIT} today
        </span>
      </div>
      <p className="pending-sub" style={{ color: "#8a93a6" }}>
        Only leads with a usable mobile number appear here. The message is written for you from that
        lead&apos;s site audit — you review it and press send in WhatsApp yourself.
        <strong> Nothing is sent automatically</strong>, which is what keeps your number safe.
      </p>

      {sentToday >= DAILY_SAFE_LIMIT && (
        <div className="draft-flags">
          ⚠ You&apos;ve opened {sentToday} chats today. Stop here — going much beyond {DAILY_SAFE_LIMIT}/day
          risks your number being flagged.
        </div>
      )}

      <div className="hunt-form" style={{ marginBottom: 10 }}>
        {STATUSES.map((s) => (
          <button key={s.key} className={`chip ${filter === s.key ? "active" : ""}`}
            onClick={() => setFilter(s.key)}>
            {s.label}{counts[s.key] ? ` (${counts[s.key]})` : s.key === "all" && counts.total ? ` (${counts.total})` : ""}
          </button>
        ))}
        <span style={{ marginLeft: "auto", display: "flex", gap: 6, alignItems: "center" }}>
          <span className="muted small">Language</span>
          <select className="af-input" style={{ width: 130 }} value={lang}
            onChange={(e) => setLang(e.target.value as "english" | "roman_urdu")}>
            <option value="english">English</option>
            <option value="roman_urdu">Roman Urdu</option>
          </select>
        </span>
      </div>

      {msg && <div className="pending-msg">{msg}</div>}

      {leads.length === 0 ? (
        <p className="muted small">No WhatsApp-reachable leads in this view.</p>
      ) : (
        <div className="table-wrap">
          <table className="leads-table">
            <thead>
              <tr><th>Business</th><th>Number</th><th>Status</th><th>Remarks</th><th></th></tr>
            </thead>
            <tbody>
              {leads.map((l) => (
                <tr key={l.id} className={openId === l.id ? "" : undefined}>
                  <td>
                    <span className="lead-name">{l.business_name}</span>
                    <span className="muted small"> · {l.city}</span>
                    {l.collection_reason && (
                      <div className="draft-reason" style={{ marginTop: 4 }}>{l.collection_reason.slice(0, 90)}</div>
                    )}
                    {openId === l.id && (
                      <div className="draft-edit" style={{ marginTop: 8 }}>
                        <textarea className="af-input" rows={4} value={draft}
                          onChange={(e) => setDraft(e.target.value)}
                          placeholder={busy === l.id ? "Writing…" : "Message will appear here"} />
                        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                          <button className="btn-mini primary" disabled={!draft}
                            onClick={() => openWhatsApp(l)}>Open WhatsApp →</button>
                          <button className="btn-mini" disabled={busy === l.id}
                            onClick={() => prepare(l)}>Rewrite</button>
                          <button className="btn-mini" onClick={() => setStatus(l, "message_sent")}>
                            ✓ Mark sent
                          </button>
                        </div>
                      </div>
                    )}
                  </td>
                  <td className="muted">+{l.number}</td>
                  <td>
                    <select className="af-input" style={{ minWidth: 130 }} value={l.status}
                      onChange={(e) => setStatus(l, e.target.value)}>
                      {STATUSES.filter((s) => s.key !== "all").map((s) => (
                        <option key={s.key} value={s.key}>{s.label}</option>
                      ))}
                    </select>
                    <div style={{ height: 3, marginTop: 4, borderRadius: 2,
                      background: STATUS_COLOR[l.status] || "#8a93a6" }} />
                  </td>
                  <td>
                    <input className="af-input" defaultValue={l.remarks} placeholder="e.g. asked for pricing"
                      onBlur={(e) => e.target.value !== l.remarks && saveRemarks(l, e.target.value)} />
                  </td>
                  <td className="row-actions">
                    <button className="btn-mini primary" disabled={busy === l.id}
                      onClick={() => prepare(l)}>
                      {busy === l.id ? "…" : openId === l.id ? "Hide" : "Message"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
