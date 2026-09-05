"use client";

import { useCallback, useEffect, useState } from "react";
import * as api from "@/lib/api";
import type { AgentRequest } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

export default function GrowPage() {
  const { user } = useAuth();
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");
  const [reasoning, setReasoning] = useState(true);
  const [requests, setRequests] = useState<AgentRequest[]>([]);
  const [busy, setBusy] = useState(false);
  const [banner, setBanner] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<Record<string, string>>({});
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    try { setRequests(await api.getAgentRequests()); setErr(null); }
    catch (e) { setErr((e as Error).message); }
  }, []);
  useEffect(() => { if (user?.role === "admin") load(); const t = setInterval(() => user?.role === "admin" && load(), 3000); return () => clearInterval(t); }, [load, user]);

  if (user?.role !== "admin") {
    return <div className="page-body"><div className="backend-warn">Admins only.</div></div>;
  }

  const submit = async () => {
    if (!name.trim() || !desc.trim()) return;
    setBusy(true); setBanner(null);
    try {
      const r = await api.requestNewAgent(name.trim(), desc.trim(), reasoning);
      setBanner(r.message); setName(""); setDesc(""); load();
    } catch (e) { alert((e as Error).message); } finally { setBusy(false); }
  };
  const approve = async (id: string) => {
    if (!confirm("Approve & deploy this agent? It will go live in the office immediately.")) return;
    try { const r = await api.approveAgentRequest(id); setBanner(r.message); load(); }
    catch (e) { alert((e as Error).message); }
  };
  const reject = async (id: string) => {
    try { const r = await api.rejectAgentRequest(id, feedback[id] || ""); setBanner(r.message); load(); }
    catch (e) { alert((e as Error).message); }
  };

  const pending = requests.filter((r) => r.status === "building" || r.status === "awaiting_review");
  const past = requests.filter((r) => r.status === "approved" || r.status === "rejected");

  return (
    <div className="page-body">
      <div className="page-head">
        <div><h1>Grow the Team</h1><p className="page-sub">Describe a new agent — IT Technician builds & tests it in isolation, you approve before it goes live.</p></div>
      </div>
      {err && <div className="backend-warn">⚠ {err}</div>}
      {banner && <div className="niche-banner">✓ {banner}</div>}

      <div className="panel">
        <div className="panel-head"><h2>Request a new agent</h2></div>
        <div className="grow-form">
          <input className="af-input" placeholder="Agent name (e.g. LinkedIn Outreach Agent)" value={name} onChange={(e) => setName(e.target.value)} />
          <textarea className="af-input" rows={3} placeholder="What should it do? Describe in plain language…" value={desc} onChange={(e) => setDesc(e.target.value)} />
          <label className="debug-flag"><input type="checkbox" checked={reasoning} onChange={(e) => setReasoning(e.target.checked)} /> Needs its own Claude reasoning (uncheck for purely mechanical, like Agent 2)</label>
          <button className="btn open" disabled={busy || !name.trim() || !desc.trim()} onClick={submit}>{busy ? "Submitting…" : "Request new agent"}</button>
        </div>
      </div>

      <div className="panel">
        <div className="panel-head"><h2>Pending agent requests</h2><span className="muted">{pending.length}</span></div>
        {pending.length === 0 && <div className="muted small">No pending requests.</div>}
        {pending.map((r) => (
          <div key={r.request_id} className="build-card">
            <div className="build-head">
              <div><span className="lead-name">{r.agent_name}</span> <span className="muted">{r.status === "building" ? "· building…" : ""}</span></div>
              {r.status === "awaiting_review" && (
                <span className={`build-verdict ${r.overall_ready ? "ok" : "bad"}`}>{r.overall_ready ? "✓ Passed all tests" : "✕ Some tests failed"}</span>
              )}
            </div>
            <div className="build-desc">{r.description_given}</div>

            {r.status === "building" && <div className="chat-hint" style={{ padding: 14 }}>IT Technician is generating and testing the code in isolation…</div>}

            {r.status === "awaiting_review" && (
              <>
                {!r.overall_ready && <div className="backend-warn" style={{ marginTop: 8 }}>⚠ This build failed one or more of its own tests — review carefully before approving.</div>}

                <div className="build-section">
                  <div className="build-label">Files added on approval</div>
                  <ul className="build-files">{(r.files_added || []).map((f, i) => <li key={i}><code>{f}</code></li>)}</ul>
                </div>

                <div className="build-section">
                  <div className="build-label">Isolated test results</div>
                  {(r.test_results || []).map((t, i) => (
                    <div key={i} className="build-test">
                      <span className={`build-dot ${t.passed ? "ok" : "bad"}`} />
                      <span className="build-test-name">{t.check_name}</span>
                      <span className="muted small">{t.detail}</span>
                    </div>
                  ))}
                </div>

                {(r.warnings || []).length > 0 && (
                  <div className="build-section">
                    <div className="build-label">Warnings / limitations</div>
                    <ul className="build-warnings">{r.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
                  </div>
                )}

                <div className="build-actions">
                  <input className="af-input" placeholder="Optional feedback (if rejecting, to retry later)…" value={feedback[r.request_id] || ""} onChange={(e) => setFeedback({ ...feedback, [r.request_id]: e.target.value })} />
                  <button className="btn-mini primary" onClick={() => approve(r.request_id)}>Approve &amp; Deploy</button>
                  <button className="btn-mini danger" onClick={() => reject(r.request_id)}>Reject</button>
                </div>
              </>
            )}
          </div>
        ))}
      </div>

      {past.length > 0 && (
        <div className="panel">
          <div className="panel-head"><h2>History</h2></div>
          {past.map((r) => (
            <div key={r.request_id} className="build-hist">
              <span className={`lead-badge`} style={{ color: r.status === "approved" ? "#7ee0a2" : "#8a93a6", borderColor: r.status === "approved" ? "#2f6f4f" : "#2a3040" }}>{r.status}</span>
              <span className="lead-name">{r.agent_name}</span>
              {r.deployed_file && <span className="muted small">→ <code>{r.deployed_file}</code></span>}
              {r.feedback && <span className="muted small">feedback: {r.feedback}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
