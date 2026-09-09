"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import * as api from "@/lib/api";
import type { ApiLead } from "@/lib/api";
import RepliesReview from "@/components/dashboard/RepliesReview";
import Mailbox from "@/components/ui/Mailbox";
import FollowupPanel from "@/components/ui/FollowupPanel";

// Everything email lives here — kept OUT of the CRM, which is about the leads
// themselves. This page is the outreach cockpit: send, read replies, and see the
// exact email that went to each prospect.
const MAIL_STATUSES = ["mailed", "replied", "interested_awaiting_review", "not_interested"];

export default function OutreachPage() {
  const [leads, setLeads] = useState<ApiLead[]>([]);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const load = useCallback(async () => {
    try { setLeads(await api.getLeads()); setErr(null); }
    catch (e) { setErr((e as Error).message); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const mailed = useMemo(
    () => leads.filter((l) => MAIL_STATUSES.includes(l.status) || (l.outreach_history?.length ?? 0) > 0),
    [leads]
  );
  const readyToSend = useMemo(() => leads.filter((l) => l.status === "verified"), [leads]);

  const stats = useMemo(() => ({
    ready: readyToSend.length,
    sent: leads.filter((l) => (l.outreach_history ?? []).some((h) => h.type === "email")).length,
    replied: leads.filter((l) => ["replied", "interested_awaiting_review", "not_interested"].includes(l.status)).length,
    interested: leads.filter((l) => l.status === "interested_awaiting_review").length,
  }), [leads, readyToSend]);

  const check = async () => {
    setBusy("check"); setMsg(null);
    try {
      const r = await api.checkReplies();
      setMsg(r.ok ? `Checked inbox — processed ${r.processed ?? 0} new replies.` : `⚠ ${r.error || "Check failed"}`);
      load();
    } finally { setBusy(null); }
  };

  return (
    <div className="page-body">
      <div className="page-head">
        <div>
          <h1>Outreach</h1>
          <p className="page-sub">Cold email sending, replies, and the exact message sent to each lead.</p>
        </div>
        <div className="controls">
          <button className="btn-mini" disabled={busy === "check"} onClick={check}>
            {busy === "check" ? "Checking…" : "Check replies"}
          </button>
        </div>
      </div>

      {err && <div className="backend-warn">⚠ Can’t reach backend ({err}).</div>}
      {msg && <div className="pending-msg">{msg}</div>}

      <div className="stat-row">
        <div className="stat-card"><div className="stat-value">{stats.ready}</div><div className="stat-label">Approved, not yet emailed</div></div>
        <div className="stat-card"><div className="stat-value">{stats.sent}</div><div className="stat-label">Emails sent</div></div>
        <div className="stat-card"><div className="stat-value">{stats.replied}</div><div className="stat-label">Replies received</div></div>
        <div className="stat-card"><div className="stat-value">{stats.interested}</div><div className="stat-label">Interested — needs you</div></div>
      </div>

      <FollowupPanel />

      <Mailbox onChanged={load} />
      <RepliesReview onChanged={load} />

    </div>
  );
}
