"use client";

import { useState } from "react";
import type { ApiLead } from "@/lib/api";

const SEV: Record<string, { color: string; label: string }> = {
  critical: { color: "#e06c6c", label: "critical" },
  high: { color: "#e0913f", label: "high" },
  medium: { color: "#e0c341", label: "medium" },
  low: { color: "#7f9ab5", label: "low" },
};

// What we can sell each purpose, in the words the CEO uses for it. Mirrors
// PURPOSES in backend/agent1/purposes.py — kept here rather than fetched
// because it is four words per entry and this table renders on every row.
const PURPOSE_LABEL: Record<string, string> = {
  website: "Website",
  booking: "Online booking",
  erp: "Inventory & production",
  crm: "Enquiry & customer management",
  pos: "Point of sale",
  lms: "School management",
  seo: "Search visibility",
};

// Shows WHY a lead was collected — what we can sell them, which is what the
// outreach will actually pitch.
//
// This used to lead with the site audit's top finding, so a furniture shop
// collected to sell it stock tracking was labelled "No HTTPS (insecure site)".
// That is not why we collected it, it is not what we will write to them, and
// it made every lead look like a website lead. The audit findings are still
// here as evidence, one click away.
export default function LeadReason({ lead, compact = false }: { lead: ApiLead; compact?: boolean }) {
  const [open, setOpen] = useState(false);
  const audit = lead.site_audit;
  const findings = audit?.findings ?? [];
  const reason = lead.collection_reason;
  const purposes = (lead.purposes ?? []).filter((p) => PURPOSE_LABEL[p]);

  if (!reason && findings.length === 0 && purposes.length === 0) {
    return <span className="muted small">—</span>;
  }

  const score = lead.opportunity_score ?? 0;
  // What we are selling comes first. The audit headline is a fallback for
  // leads collected before purposes existed.
  const headline = purposes.length
    ? purposes.map((p) => PURPOSE_LABEL[p]).join(" + ")
    : audit?.headline || reason?.slice(0, 60) || "";

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
          {findings.length > 0 && (
            <p className="reason-summary muted" style={{ fontSize: 10.5 }}>
              What we found on their site. This is our own evidence — it is not
              what the outreach message says.
            </p>
          )}
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
