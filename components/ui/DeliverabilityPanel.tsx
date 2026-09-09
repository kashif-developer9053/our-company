"use client";

import { useCallback, useEffect, useState } from "react";
import * as api from "@/lib/api";
import type { Deliverability } from "@/lib/api";

// Bounce rate is the number that decides whether the sending domain survives.
// Before this panel existed, 58 guessed addresses had been mailed with no
// visibility at all into whether any of them bounced.
export default function DeliverabilityPanel() {
  const [d, setD] = useState<Deliverability | null>(null);
  const [hook, setHook] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    try { setD(await api.getDeliverability(30)); } catch { /* backend down */ }
  }, []);
  useEffect(() => { load(); }, [load]);

  const showHook = async () => {
    try { setHook((await api.getWebhookUrl()).path); } catch { /* ignore */ }
  };

  const runVerify = async () => {
    setBusy(true); setMsg(null);
    try {
      const r = await api.verifyEmails({ limit: 100, only_guessed: true });
      setMsg(r.message ?? `Checked ${r.checked}: ${JSON.stringify(r.results ?? {})}`);
      load();
    } catch (e) { setMsg((e as Error).message); }
    finally { setBusy(false); }
  };

  if (!d) return null;
  const risky = d.bounce_rate_pct >= 3;

  return (
    <section className="dl-panel">
      <div className="dl-head">
        <h3 className="dl-title">Deliverability</h3>
        <span className={`dl-badge ${risky ? "dl-bad" : "dl-good"}`}>
          {risky ? "At risk" : "Healthy"}
        </span>
      </div>

      <div className="dl-grid">
        <div className="dl-stat">
          <span className={`dl-val ${risky ? "dl-bad-t" : ""}`}>{d.bounce_rate_pct}%</span>
          <span className="dl-lbl">Bounce rate</span>
        </div>
        <div className="dl-stat">
          <span className="dl-val">{d.delivered}</span>
          <span className="dl-lbl">Delivered</span>
        </div>
        <div className="dl-stat">
          <span className="dl-val">{d.hard_bounces}</span>
          <span className="dl-lbl">Hard bounces</span>
        </div>
        <div className="dl-stat">
          <span className="dl-val">{d.suppressed_total}</span>
          <span className="dl-lbl">Suppressed</span>
        </div>
      </div>

      <p className="dl-note">
        {risky
          ? "Above 3% puts the sending domain at risk. Verify addresses before sending more."
          : "Keep hard bounces under 3%. Above 5% providers filter the whole domain."}
      </p>

      <div className="dl-actions">
        <button className="dl-btn" onClick={runVerify} disabled={busy}>
          {busy ? "Checking…" : "Verify guessed addresses"}
        </button>
        <button className="dl-btn dl-ghost" onClick={showHook}>Show webhook URL</button>
      </div>

      {hook && (
        <p className="dl-hook">
          Paste into Brevo → Settings → Webhooks (treat as a secret):<br />
          <code>{hook}</code>
        </p>
      )}
      {msg && <p className="dl-msg">{msg}</p>}
    </section>
  );
}
