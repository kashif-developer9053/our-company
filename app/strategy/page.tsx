"use client";

import { useCallback, useEffect, useState } from "react";
import * as api from "@/lib/api";
import type { StrategicReview, CoachingProposal } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

export default function StrategyPage() {
  const { user } = useAuth();
  const [review, setReview] = useState<StrategicReview | null>(null);
  const [proposals, setProposals] = useState<CoachingProposal[]>([]);
  const [busy, setBusy] = useState(false);
  const [banner, setBanner] = useState<string | null>(null);

  const load = useCallback(async () => {
    try { setReview(await api.getStrategicReview()); setProposals(await api.getProposals()); } catch { /* */ }
  }, []);
  useEffect(() => { if (user?.role === "admin") load(); }, [load, user]);

  if (user?.role !== "admin") return <div className="page-body"><div className="backend-warn">Admins only.</div></div>;

  const run = async () => { setBusy(true); try { setReview(await api.runStrategicReview()); await load(); } finally { setBusy(false); } };
  const approve = async (id: string) => { const r = await api.approveProposal(id); setBanner(r.message); load(); };
  const reject = async (id: string) => { await api.rejectProposal(id); load(); };

  return (
    <div className="page-body">
      <div className="page-head">
        <div><h1>Supervisor · Strategy</h1><p className="page-sub">Senior analysis of real performance + coaching proposals (you approve any instruction change).</p></div>
        <button className="btn open" disabled={busy} onClick={run}>{busy ? "Analyzing…" : "Run strategic review"}</button>
      </div>
      {banner && <div className="niche-banner">✓ {banner}</div>}

      <div className="panel">
        <div className="panel-head"><h2>What the Supervisor noticed</h2>{review && <span className="muted">{review.created_at?.slice(0, 16).replace("T", " ")}</span>}</div>
        {!review && <div className="muted small">No review yet — click “Run strategic review”.</div>}
        {review && (
          <>
            <ul className="build-warnings" style={{ listStyle: "none" }}>
              {review.observations.map((o, i) => <li key={i} style={{ paddingLeft: 0 }}>• {o}</li>)}
            </ul>
            <div className="build-label" style={{ marginTop: 12 }}>Strategic direction</div>
            <div className="it-diag">{review.strategy}</div>
          </>
        )}
      </div>

      <div className="panel">
        <div className="panel-head"><h2>Coaching proposals — need your approval</h2><span className="muted">{proposals.length}</span></div>
        {proposals.length === 0 && <div className="muted small">No pending coaching proposals.</div>}
        {proposals.map((p) => (
          <div key={p.id} className="build-card">
            <div className="build-head"><span className="lead-name">{p.agent_id}</span></div>
            <div className="build-desc">{p.reason}</div>
            <div className="build-section">
              <div className="build-label">Proposed instruction change (not applied until you approve)</div>
              <div className="reply-suggest-text" style={{ whiteSpace: "pre-wrap" }}>{p.proposed_instructions.slice(-400)}</div>
            </div>
            <div className="build-actions">
              <button className="btn-mini primary" onClick={() => approve(p.id)}>Approve &amp; apply</button>
              <button className="btn-mini danger" onClick={() => reject(p.id)}>Reject</button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
