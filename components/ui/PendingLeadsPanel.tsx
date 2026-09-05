"use client";

import { useCallback, useEffect, useState } from "react";
import * as api from "@/lib/api";
import type { PendingBatch } from "@/lib/api";
import LeadReason from "./LeadReason";

// APPROVAL CHECKPOINT: leads scraped by Agent 1 and verified by Agent 2 wait
// here. Nothing enters the working CRM — and no outreach is written — until the
// CEO approves. Approving hands the batch straight to Agent 3.
export default function PendingLeadsPanel({ onChanged }: { onChanged?: () => void }) {
  const [batches, setBatches] = useState<PendingBatch[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [selected, setSelected] = useState<Record<string, Set<string>>>({});

  const load = useCallback(async () => {
    try {
      const r = await api.getPendingLeads();
      setBatches(r.batches);
      // default: everything in each batch is selected
      const sel: Record<string, Set<string>> = {};
      r.batches.forEach((b) => { sel[b.batch_id] = new Set(b.leads.map((l) => l.id)); });
      setSelected(sel);
    } catch { /* */ }
  }, []);
  useEffect(() => { load(); }, [load]);

  if (batches.length === 0) return null;

  const toggle = (batchId: string, leadId: string) => {
    setSelected((s) => {
      const next = new Set(s[batchId] ?? []);
      if (next.has(leadId)) next.delete(leadId); else next.add(leadId);
      return { ...s, [batchId]: next };
    });
  };

  const approve = async (b: PendingBatch) => {
    const chosen = Array.from(selected[b.batch_id] ?? []);
    if (chosen.length === 0) { setMsg("Select at least one lead, or reject the batch."); return; }
    setBusy(b.batch_id);
    try {
      const all = chosen.length === b.leads.length;
      const r = await api.approveLeadBatch(b.batch_id, all ? undefined : chosen);
      const o = r.outreach;
      setMsg(
        o?.started
          ? `✅ ${r.approved} leads added to your CRM. Agent 3 is now writing outreach for ${o.count} of them.`
          : o?.reason === "email_not_configured"
            ? `✅ ${r.approved} leads added to your CRM. Agent 3 can't send yet — configure email in Settings (${o.queued} queued).`
            : `✅ ${r.approved} leads added to your CRM.`
      );
      await load();
      onChanged?.();
    } catch (e) { setMsg(`⚠ ${(e as Error).message}`); }
    finally { setBusy(null); }
  };

  const reject = async (b: PendingBatch) => {
    if (!confirm(`Reject all ${b.leads.length} leads in this batch?`)) return;
    setBusy(b.batch_id);
    try {
      const r = await api.rejectLeadBatch(b.batch_id);
      setMsg(`Rejected ${r.rejected} leads.`);
      await load();
      onChanged?.();
    } finally { setBusy(null); }
  };

  return (
    <div className="pending-wrap">
      {msg && <div className="pending-msg">{msg}</div>}
      {batches.map((b) => {
        const sel = selected[b.batch_id] ?? new Set<string>();
        return (
          <div key={b.batch_id} className="settings-card pending-batch">
            <div className="settings-card-head">
              <h2>✋ {b.leads.length} leads need your approval</h2>
              <span className="soon-tag">{b.niche} · {b.city || b.country}</span>
            </div>
            <p className="pending-sub">
              Agent 1 found these and Agent 2 verified them. They are <strong>not</strong> in your CRM yet.
              Uncheck any you don&apos;t want, then approve — Agent 3 writes outreach only for approved leads.
            </p>

            <div className="table-wrap">
              <table className="leads-table">
                <thead>
                  <tr>
                    <th style={{ width: 32 }}></th>
                    <th>Business</th><th>Contact</th><th>Website</th><th>Why this lead? (click for evidence)</th>
                  </tr>
                </thead>
                <tbody>
                  {b.leads.map((l) => (
                    <tr key={l.id} className={sel.has(l.id) ? "" : "row-muted"}>
                      <td>
                        <input type="checkbox" checked={sel.has(l.id)} onChange={() => toggle(b.batch_id, l.id)} />
                      </td>
                      <td>{l.business_name}</td>
                      <td className="muted">
                        <div>{l.email || "—"}
                          {l.email_confidence === "guessed" && <span className="soon-tag" style={{ marginLeft: 6 }}>guessed</span>}
                        </div>
                        <div style={{ fontSize: 11 }}>{l.phone || ""}</div>
                      </td>
                      <td className="muted">
                        {l.website ? (l.has_working_website ? "live" : "down") : "none"}
                      </td>
                      <td><LeadReason lead={l} compact /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="pending-actions">
              <button className="btn-mini primary" disabled={busy === b.batch_id} onClick={() => approve(b)}>
                {busy === b.batch_id ? "Approving…" : `Approve ${sel.size} → add to CRM`}
              </button>
              <button className="btn-mini danger" disabled={busy === b.batch_id} onClick={() => reject(b)}>
                Reject batch
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
