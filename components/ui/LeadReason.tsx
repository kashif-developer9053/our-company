"use client";

import { useState } from "react";
import type { ApiLead } from "@/lib/api";

const SEV: Record<string, { color: string; label: string }> = {
  critical: { color: "#e06c6c", label: "critical" },
  high: { color: "#e0913f", label: "high" },
  medium: { color: "#e0c341", label: "medium" },
  low: { color: "#7f9ab5", label: "low" },
};

// Shows WHY a lead was collected: the headline problem found on their website,
// expandable into every finding with the evidence we actually observed.
export default function LeadReason({ lead, compact = false }: { lead: ApiLead; compact?: boolean }) {
  const [open, setOpen] = useState(false);
  const audit = lead.site_audit;
  const findings = audit?.findings ?? [];
  const reason = lead.collection_reason;

  if (!reason && findings.length === 0) {
    return <span className="muted small">—</span>;
  }

  const score = lead.opportunity_score ?? 0;
  const headline = audit?.headline || reason?.slice(0, 60) || "";

  return (
    <div className="lead-reason">
      <button className="lead-reason-head" onClick={() => setOpen(!open)} title="Show the evidence">
        <span className="reason-score" style={{ borderColor: score >= 60 ? "#e06c6c" : score >= 30 ? "#e0913f" : "#5a6a80" }}>
          {score}
        </span>
        <span className="reason-headline">{headline}</span>
        {findings.length > 0 && <span className="reason-toggle">{open ? "▴" : `▾ ${findings.length}`}</span>}
      </button>

      {open && (
        <div className="reason-detail">
          {reason && <p className="reason-summary">{reason}</p>}
          {findings.map((f) => {
            const s = SEV[f.severity] || SEV.low;
            return (
              <div key={f.code} className="reason-finding">
                <span className="reason-sev" style={{ color: s.color, borderColor: s.color }}>{s.label}</span>
                <div>
                  <div className="reason-title">{f.title}</div>
                  <div className="reason-evidence">{f.evidence}</div>
                  {!compact && <div className="reason-pitch">→ {f.pitch}</div>}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
