"use client";

import { useCallback, useEffect, useState } from "react";
import * as api from "@/lib/api";
import type { FollowupItem } from "@/lib/api";

// Leads that were emailed once and never chased. This panel exists because the
// first 37 cold emails produced 30 leads that never got a second touch — and in
// cold outreach most replies arrive on the second, third or fourth email.
//
// Drafting is the automated part. Everything written here still lands in the
// normal review queue and needs approval before it is sent.

const ANGLE_LABEL: Record<string, string> = {
  gentle_bump: "Gentle bump",
  new_angle: "New angle",
  breakup: "Breakup",
};

const ANGLE_HINT: Record<string, string> = {
  gentle_bump: "Short nudge — assumes the first email got buried",
  new_angle: "Different approach — the first angle didn't land",
  breakup: "Final email — closes the file, leaves the door open",
};

export default function FollowupPanel() {
  const [items, setItems] = useState<FollowupItem[]>([]);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [count, setCount] = useState(20);

  const load = useCallback(async () => {
    try {
      const r = await api.getFollowupsDue(100);
      setItems(r.items ?? []);
      setErr(null);
    } catch (e) {
      setErr((e as Error).message);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const draft = async () => {
    setBusy(true); setMsg(null); setErr(null);
    try {
      const r = await api.draftFollowups({ count });
      setMsg(r.message ?? `Queued ${r.queued ?? 0} follow-ups.`);
      // The writer runs in the background; give it a moment before refreshing.
      setTimeout(load, 4000);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const byAngle = items.reduce<Record<string, number>>((acc, i) => {
    acc[i.angle] = (acc[i.angle] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <section className="fu-panel">
      <div className="fu-head">
        <div>
          <h3 className="fu-title">Follow-ups due</h3>
          <p className="fu-sub">
            Leads that never replied. Most replies come from the 2nd–4th email.
          </p>
        </div>
        <span className="fu-total">{items.length}</span>
      </div>

      {err && <div className="fu-err">{err}</div>}
      {msg && <div className="fu-msg">{msg}</div>}

      {items.length > 0 && (
        <div className="fu-chips">
          {Object.entries(byAngle).map(([a, n]) => (
            <span key={a} className={`fu-chip fu-${a}`} title={ANGLE_HINT[a]}>
              {ANGLE_LABEL[a] ?? a} · {n}
            </span>
          ))}
        </div>
      )}

      {items.length === 0 ? (
        <p className="fu-empty">Nothing due right now. Follow-ups appear here 3 days after the first email.</p>
      ) : (
        <>
          <div className="fu-actions">
            <label className="fu-lbl">
              Write
              <input
                type="number" min={1} max={100} value={count}
                onChange={(e) => setCount(Math.max(1, Math.min(100, Number(e.target.value) || 1)))}
                className="fu-num"
              />
              follow-ups
            </label>
            <button className="fu-btn" onClick={draft} disabled={busy}>
              {busy ? "Writing…" : "Draft follow-ups"}
            </button>
          </div>

          <ul className="fu-list">
            {items.slice(0, 25).map((i) => (
              <li key={i.lead_id} className="fu-item">
                <div className="fu-item-main">
                  <span className="fu-biz">{i.business_name}</span>
                  <span className="fu-meta">
                    {[i.city, i.niche].filter(Boolean).join(" · ")}
                  </span>
                </div>
                <div className="fu-item-side">
                  <span className={`fu-chip fu-${i.angle}`}>{ANGLE_LABEL[i.angle] ?? i.angle}</span>
                  <span className="fu-sent">{i.emails_sent} sent</span>
                </div>
              </li>
            ))}
          </ul>
          {items.length > 25 && (
            <p className="fu-more">…and {items.length - 25} more waiting.</p>
          )}
        </>
      )}
    </section>
  );
}
