// Shared types for the Team Activity sidebar, Outreach Report, and CRM.
// Shapes are designed to map cleanly onto real "agent activity/logs" and
// "CRM/lead" APIs later — swapping the mock files for live data is a drop-in.

import type { AgentId, AnyStatus } from "./officeTypes";

export interface ActivityEntry {
  timestamp: string; // display string, e.g. "10:02 AM"
  message: string;
}

export interface AgentActivity {
  agentId: AgentId;
  name: string;
  role: string;
  status: AnyStatus; // default/mock status (live status overrides in the UI)
  currentTask: string;
  lastUpdated: string; // relative, e.g. "2 min ago"
  recentActivity: ActivityEntry[];
  errorDetail?: string;
}

export type LeadStatus =
  | "mailed"
  | "replied"
  | "not_interested"
  | "interested_awaiting_review";

export interface Lead {
  id: string;
  businessName: string;
  niche: string;
  status: LeadStatus;
  lastAction: string; // human label, e.g. "Follow-up email sent"
  lastActionTimestamp: string; // e.g. "2026-07-23 10:14"
}

export interface OutreachStats {
  leadsFound: number;
  leadsVerified: number;
  emailsSent: number;
  repliesReceived: number;
  interested: number;
  notInterested: number;
  pendingResponse: number;
}

export interface DailyReport {
  date: string;
  stats: OutreachStats;
  leads: Lead[];
}

export type DateRange = "today" | "week" | "month";

// Visual metadata for lead statuses (badge label + color).
export const LEAD_STATUS_META: Record<LeadStatus, { label: string; color: string }> = {
  mailed: { label: "Mailed", color: "#8a93a6" },
  replied: { label: "Replied", color: "#4aa3ff" },
  not_interested: { label: "Not Interested", color: "#ef5350" },
  interested_awaiting_review: { label: "Interested — Awaiting You", color: "#f2c14e" },
};
