"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import * as api from "@/lib/api";
import type { ApiLead, LeadStats } from "@/lib/api";
import StatCards from "@/components/dashboard/StatCards";

// Compact right-side summary on the Office page, now backed by the real CRM API.
export default function OutreachSummary() {
  const [stats, setStats] = useState<LeadStats | null>(null);
  const [review, setReview] = useState<ApiLead[]>([]);

  useEffect(() => {
    let on = true;
    const load = async () => {
      try {
        const [s, leads] = await Promise.all([
          api.getLeadStats(),
          api.getLeads({ status: "interested_awaiting_review" }),
        ]);
        if (on) { setStats(s.stats); setReview(leads); }
      } catch {
        /* backend down — leave empty */
      }
    };
    load();
    const t = setInterval(load, 4000);
    return () => { on = false; clearInterval(t); };
  }, []);

  return (
    <aside className="outreach-summary">
      <div className="team-head">
        <span>Daily Outreach</span>
        <Link href="/reports" className="view-full">Full report →</Link>
      </div>

      {stats && <StatCards stats={stats} only={["leadsFound", "emailsSent", "interested", "pendingResponse"]} />}

      <div className="review-block">
        <div className="review-title">
          Needs your review <span className="review-count">{review.length}</span>
        </div>
        {review.length === 0 && <div className="muted small">Nothing awaiting review 🎉</div>}
        {review.map((l) => (
          <Link key={l.id} href="/leads" className="review-item">
            <span className="review-biz">{l.business_name}</span>
            <span className="review-niche">{l.niche}{l.city ? ` — ${l.city}` : ""}</span>
          </Link>
        ))}
      </div>
    </aside>
  );
}
