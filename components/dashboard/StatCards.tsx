import type { OutreachStats } from "@/types/dashboardTypes";

const FIELDS: { key: keyof OutreachStats; label: string; accent: string }[] = [
  { key: "leadsFound", label: "Leads Found", accent: "#4aa3ff" },
  { key: "leadsVerified", label: "Leads Verified", accent: "#26c6da" },
  { key: "emailsSent", label: "Emails Sent", accent: "#7e8cff" },
  { key: "repliesReceived", label: "Replies Received", accent: "#59c48a" },
  { key: "interested", label: "Interested", accent: "#f2c14e" },
  { key: "notInterested", label: "Not Interested", accent: "#ef5350" },
  { key: "pendingResponse", label: "Pending Response", accent: "#8a93a6" },
];

// Row/grid of summary stat cards. `only` limits which stats to show (used by
// the compact office-page summary).
export default function StatCards({
  stats,
  only,
}: {
  stats: OutreachStats;
  only?: (keyof OutreachStats)[];
}) {
  const fields = only ? FIELDS.filter((f) => only.includes(f.key)) : FIELDS;
  return (
    <div className="stat-grid">
      {fields.map((f) => (
        <div key={f.key} className="stat-card">
          <div className="stat-value" style={{ color: f.accent }}>
            {stats[f.key]}
          </div>
          <div className="stat-label">{f.label}</div>
        </div>
      ))}
    </div>
  );
}
