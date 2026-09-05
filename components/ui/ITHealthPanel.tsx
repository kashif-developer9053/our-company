"use client";

import { useCallback, useEffect, useState } from "react";
import * as api from "@/lib/api";
import type { ITHealth } from "@/lib/api";

const OVERALL: Record<string, { dot: string; label: string; color: string }> = {
  ok: { dot: "🟢", label: "All systems normal", color: "#7ee0a2" },
  warning: { dot: "🟡", label: "Warning — needs attention", color: "#ffca28" },
  risk: { dot: "🔴", label: "Risk — action needed", color: "#ef5350" },
  unknown: { dot: "⚪", label: "Unknown", color: "#8a93a6" },
};

const COMP_META: Record<string, { label: string; color: string }> = {
  ok: { label: "OK", color: "#7ee0a2" },
  fail: { label: "Failing", color: "#ef5350" },
  unconfigured: { label: "Not set up", color: "#8a93a6" },
};

export default function ITHealthPanel() {
  const [health, setHealth] = useState<ITHealth | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try { setHealth(await api.getItStatus()); } catch { /* ignore */ }
  }, []);
  useEffect(() => { load(); const t = setInterval(load, 5000); return () => clearInterval(t); }, [load]);

  const runNow = async () => {
    setBusy(true);
    try { setHealth(await api.runItCheck()); } finally { setBusy(false); }
  };

  if (!health) return <div className="chat-body">Loading health status…</div>;
  const o = OVERALL[health.overall] || OVERALL.unknown;
  const c = health.components;
  const comp = (label: string, cc?: api.Component) => {
    const m = COMP_META[cc?.status || "unconfigured"] || COMP_META.unconfigured;
    return (
      <div className="it-comp" key={label}>
        <span className="it-comp-name">{label}</span>
        <span className="it-comp-status" style={{ color: m.color }}>
          {m.label}{cc?.response_time_ms != null ? ` · ${cc.response_time_ms}ms` : ""}
        </span>
      </div>
    );
  };

  return (
    <div className="it-panel">
      <div className="it-overall" style={{ borderColor: o.color }}>
        <span className="it-overall-dot">{o.dot}</span>
        <span style={{ color: o.color, fontWeight: 600 }}>{o.label}</span>
        <button className="btn-mini" style={{ marginLeft: "auto" }} disabled={busy} onClick={runNow}>
          {busy ? "Checking…" : "Run check now"}
        </button>
      </div>

      <div className="it-comps">
        {comp("Claude API", c.claude_api)}
        {comp("Database", c.mongodb)}
        {comp("Email sending (SMTP)", c.smtp)}
        {comp("Email inbox (IMAP)", c.imap)}
        {(c.agents || []).filter((a) => a.status === "error" || a.status === "risk").map((a) => (
          <div className="it-comp" key={a.agent_id}>
            <span className="it-comp-name">{a.name}</span>
            <span className="it-comp-status" style={{ color: "#ef5350" }}>
              error{a.stuck_minutes != null ? ` · ${a.stuck_minutes} min` : ""}
            </span>
          </div>
        ))}
      </div>

      <div className="it-diag-title">{health.overall === "ok" ? "Status" : "Diagnosis & suggested fix"}</div>
      <div className="it-diag">{health.explanation}</div>
      <div className="muted small" style={{ marginTop: 8 }}>Last checked: {health.checked_at?.slice(0, 19).replace("T", " ")}</div>
    </div>
  );
}
