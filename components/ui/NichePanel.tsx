"use client";

import { useCallback, useEffect, useState } from "react";
import * as api from "@/lib/api";
import type { NicheRecord } from "@/lib/api";

// Niche-finding workflow UI: CEO requests niches -> Agent 1 generates (Claude) ->
// Supervisor sanity-check -> CEO approves ONE (hard checkpoint). Approving only
// records the decision; NO scraping is triggered in this phase.
export default function NichePanel({ onChanged }: { onChanged: () => void }) {
  const [industry, setIndustry] = useState("");
  const [country, setCountry] = useState("");
  const [city, setCity] = useState("");
  const [pending, setPending] = useState<NicheRecord[]>([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [banner, setBanner] = useState<string | null>(null);

  const loadPending = useCallback(async () => {
    try { setPending(await api.getPendingNiches()); } catch { /* ignore */ }
  }, []);
  useEffect(() => { loadPending(); const t = setInterval(loadPending, 3000); return () => clearInterval(t); }, [loadPending]);

  const request = async () => {
    // All fields optional now — blank => Agent 1 self-selects industry/country.
    setBusy(true); setErr(null); setBanner(null);
    try {
      const res = await api.findNiches({ industry: industry.trim(), country: country.trim(), city: city.trim() });
      if (res.ok) { await loadPending(); onChanged(); }
      else setErr(res.error || "Failed to generate niches");
    } catch (e) { setErr((e as Error).message); }
    finally { setBusy(false); }
  };

  const approve = async (rec: NicheRecord, name: string) => {
    setBusy(true);
    try {
      const r = await api.approveNiche(rec.id, name);
      setBanner(`Niche approved: ${r.approved_niche} — ${r.note || "lead generation has started."}`);
      await loadPending(); onChanged();
    } catch (e) { setErr((e as Error).message); }
    finally { setBusy(false); }
  };
  const rejectAll = async (rec: NicheRecord) => {
    setBusy(true);
    try { await api.rejectNiches(rec.id); await loadPending(); onChanged(); }
    finally { setBusy(false); }
  };

  return (
    <div className="niche-panel">
      <div className="niche-head">
        <span>🔎 Niche Research (Agent 1)</span>
      </div>

      <div className="niche-request">
        <input className="af-input" placeholder="Industry (optional)" value={industry} onChange={(e) => setIndustry(e.target.value)} />
        <input className="af-input" placeholder="Country (optional)" value={country} onChange={(e) => setCountry(e.target.value)} />
        <input className="af-input" placeholder="City (optional)" value={city} onChange={(e) => setCity(e.target.value)} />
        <button className="btn-mini primary" disabled={busy} onClick={request}>
          {busy ? "Working…" : "Request niches"}
        </button>
      </div>
      <div className="niche-hint">
        Leave these blank and Agent 1 will pick a promising industry and country on its own judgment.
      </div>

      {err && <div className="backend-warn" style={{ marginTop: 8 }}>⚠ {err}</div>}
      {banner && <div className="niche-banner">✓ {banner}</div>}

      {pending.map((rec) => (
        <div key={rec.id} className="niche-set">
          <div className="niche-set-head">
            {rec.industry} · {rec.city ? `${rec.city}, ` : ""}{rec.country}
            <span className="niche-await">Awaiting your approval</span>
          </div>
          {rec.selection_reasoning && (
            <div className="self-select-note">
              🤖 Agent 1 selected this space itself: <strong>{rec.industry} in {rec.country}</strong> — {rec.selection_reasoning}
            </div>
          )}
          {rec.supervisor_note && <div className="supervisor-note">🧑‍💼 Supervisor’s note: {rec.supervisor_note}</div>}
          <div className="niche-list">
            {rec.niches.map((n) => (
              <div key={n.niche_name} className="niche-item">
                <div className="niche-name">{n.niche_name}</div>
                <div className="niche-reason">{n.reasoning}</div>
                <button className="btn-mini primary" disabled={busy} onClick={() => approve(rec, n.niche_name)}>Approve this niche</button>
              </div>
            ))}
          </div>
          <button className="btn-mini" disabled={busy} onClick={() => rejectAll(rec)}>Reject all / Try again</button>
        </div>
      ))}
    </div>
  );
}
