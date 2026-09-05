"use client";

import { useEffect, useState } from "react";
import * as api from "@/lib/api";
import type { ApiLead, LeadStats, PipelineRun } from "@/lib/api";
import StatCards from "@/components/dashboard/StatCards";
import LeadsTable from "@/components/dashboard/LeadsTable";
import OutreachChart from "@/components/dashboard/OutreachChart";

export default function ReportsPage() {
  const [stats, setStats] = useState<LeadStats | null>(null);
  const [leads, setLeads] = useState<ApiLead[]>([]);
  const [runs, setRuns] = useState<PipelineRun[]>([]);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let on = true;
    const load = async () => {
      try {
        const [s, l, r] = await Promise.all([api.getLeadStats(), api.getLeads(), api.getPipelineRuns()]);
        if (on) { setStats(s.stats); setLeads(l); setRuns(r); setErr(null); }
      } catch (e) {
        if (on) setErr((e as Error).message);
      }
    };
    load();
    const t = setInterval(load, 4000);
    return () => { on = false; clearInterval(t); };
  }, []);

  return (
    <div className="page-body">
      <div className="page-head">
        <div>
          <h1>Daily Outreach Report</h1>
          <p className="page-sub">Live totals from the CRM · {leads.length} leads</p>
        </div>
        <span className="live-badge"><span className="pulse" /> Live</span>
      </div>

      {err && <div className="backend-warn">⚠ Can’t reach backend ({err}).</div>}

      {stats && <StatCards stats={stats} />}

      <div className="panel">
        <div className="panel-head">
          <h2>Outreach volume · last 7 days</h2>
          <span className="muted">illustrative trend</span>
        </div>
        <OutreachChart />
      </div>

      <div className="panel">
        <div className="panel-head">
          <h2>Lead-generation runs</h2>
          <span className="muted">{runs.length} runs</span>
        </div>
        {runs.length === 0 && <div className="muted small">No lead-gen runs yet. Approve a niche on the Office page to start one.</div>}
        {runs.map((r) => (
          <div key={r.id} className={`run-row ${r.status}`}>
            <div className="run-title">
              <span className={`run-dot ${r.status}`} /> {r.niche_name} · {r.city || r.country}
            </div>
            <div className="run-msg">{r.message || (r.status === "running" ? "Running…" : r.status)}</div>
          </div>
        ))}
      </div>

      <div className="panel">
        <div className="panel-head">
          <h2>Lead activity</h2>
          <span className="muted">{leads.length} leads</span>
        </div>
        <LeadsTable leads={leads} />
      </div>
    </div>
  );
}
