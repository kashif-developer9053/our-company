"use client";

import type { ApiLead } from "@/lib/api";
import { leadStatusMeta } from "@/lib/api";
import LeadReason from "@/components/ui/LeadReason";

export function LeadStatusBadge({ status }: { status: string }) {
  const meta = leadStatusMeta(status);
  return (
    <span className="lead-badge" style={{ color: meta.color, borderColor: meta.color }}>
      {meta.label}
    </span>
  );
}

interface Props {
  leads: ApiLead[];
  onEdit?: (lead: ApiLead) => void;
  onDelete?: (lead: ApiLead) => void;
}

// Lead table shared by Reports (read-only) and CRM (with edit/delete actions).
export default function LeadsTable({ leads, onEdit, onDelete }: Props) {
  const actions = !!(onEdit || onDelete);
  return (
    <div className="table-wrap">
      <table className="leads-table">
        <thead>
          <tr>
            <th>Business</th>
            <th>Niche / Location</th>
            <th>Contact</th>
            <th>Status</th>
            <th>Why this lead?</th>
            <th>Remarks</th>
            <th>When</th>
            {actions && <th></th>}
          </tr>
        </thead>
        <tbody>
          {leads.map((l) => (
            <tr key={l.id}>
              <td>
                <span className="lead-name">{l.business_name}</span>
                <span className="lead-id">{l.id}</span>
              </td>
              <td>
                {l.niche}
                {l.city ? <span className="muted"> · {l.city}</span> : null}
              </td>
              {/* Contact route matters operationally: a phone-only lead cannot
                  be emailed at all, and most leads here are phone-only. Showing
                  it stops those being queued for outreach that must fail. */}
              <td className="lead-contact">
                {l.email ? (
                  <a href={`mailto:${l.email}`} className="lead-email" title={l.email}>{l.email}</a>
                ) : (
                  <span className="lead-noemail">no email</span>
                )}
                {l.phone ? (
                  <a href={`tel:${l.phone.replace(/\s+/g, "")}`} className="lead-phone">{l.phone}</a>
                ) : null}
                {!l.email && l.phone && <span className="lead-hint">WhatsApp only</span>}
              </td>
              <td>
                <LeadStatusBadge status={l.status} />
                {l.status === "interested_awaiting_review" && <span className="review-tag">Needs Your Review</span>}
              </td>
              <td><LeadReason lead={l} compact /></td>
              <td className="lead-remarks">
                {l.notes && <div className="remark-note">{l.notes}</div>}
                <div className="muted small">{l.last_action}</div>
              </td>
              <td className="muted">{l.last_action_timestamp}</td>
              {actions && (
                <td className="row-actions">
                  {onEdit && <button className="btn-mini" onClick={() => onEdit(l)}>Edit</button>}
                  {onDelete && <button className="btn-mini danger" onClick={() => onDelete(l)}>Delete</button>}
                </td>
              )}
            </tr>
          ))}
          {leads.length === 0 && (
            <tr><td colSpan={actions ? 8 : 7} className="muted" style={{ padding: 16 }}>No leads.</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
