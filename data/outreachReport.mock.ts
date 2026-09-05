import type { DailyReport, DateRange, Lead } from "@/types/dashboardTypes";

// PHASE 1.6 mock: outreach/CRM data for the Reports dashboard and CRM page.
// Structure maps cleanly onto real CRM/lead data later.

// A pool of leads used across ranges + the CRM page.
export const ALL_LEADS: Lead[] = [
  { id: "L-1042", businessName: "SmileBright Dental", niche: "Dentists — Islamabad", status: "interested_awaiting_review", lastAction: "Positive reply received", lastActionTimestamp: "2026-07-23 10:14" },
  { id: "L-1041", businessName: "Capital Ortho Clinic", niche: "Dentists — Islamabad", status: "replied", lastAction: "Reply received (unclear)", lastActionTimestamp: "2026-07-23 10:09" },
  { id: "L-1040", businessName: "PearlCare Dentistry", niche: "Dentists — Islamabad", status: "mailed", lastAction: "Cold email sent", lastActionTimestamp: "2026-07-23 09:58" },
  { id: "L-1039", businessName: "Northside Family Dental", niche: "Dentists — Islamabad", status: "not_interested", lastAction: "Marked not interested (auto)", lastActionTimestamp: "2026-07-23 09:52" },
  { id: "L-1038", businessName: "BlueSky Physio", niche: "Physiotherapists — Lahore", status: "interested_awaiting_review", lastAction: "Positive reply received", lastActionTimestamp: "2026-07-23 09:47" },
  { id: "L-1037", businessName: "MoveWell Rehab", niche: "Physiotherapists — Lahore", status: "mailed", lastAction: "Cold email sent", lastActionTimestamp: "2026-07-23 09:40" },
  { id: "L-1036", businessName: "GreenLeaf Accounting", niche: "Accountants — Karachi", status: "replied", lastAction: "Reply received (question)", lastActionTimestamp: "2026-07-23 09:33" },
  { id: "L-1035", businessName: "Ledger & Co.", niche: "Accountants — Karachi", status: "mailed", lastAction: "Cold email sent", lastActionTimestamp: "2026-07-23 09:25" },
  { id: "L-1034", businessName: "Prime Tax Advisors", niche: "Accountants — Karachi", status: "not_interested", lastAction: "Marked not interested (auto)", lastActionTimestamp: "2026-07-23 09:18" },
  { id: "L-1033", businessName: "UrbanCut Salon", niche: "Salons — Islamabad", status: "mailed", lastAction: "Cold email sent", lastActionTimestamp: "2026-07-23 09:10" },
  { id: "L-1032", businessName: "Glow Aesthetics", niche: "Salons — Islamabad", status: "interested_awaiting_review", lastAction: "Positive reply received", lastActionTimestamp: "2026-07-22 17:04" },
  { id: "L-1031", businessName: "FitZone Gym", niche: "Gyms — Rawalpindi", status: "replied", lastAction: "Reply received (unclear)", lastActionTimestamp: "2026-07-22 16:41" },
  { id: "L-1030", businessName: "IronCore Fitness", niche: "Gyms — Rawalpindi", status: "mailed", lastAction: "Cold email sent", lastActionTimestamp: "2026-07-22 16:22" },
  { id: "L-1029", businessName: "PawPals Vet Clinic", niche: "Veterinarians — Lahore", status: "not_interested", lastAction: "Marked not interested (auto)", lastActionTimestamp: "2026-07-22 15:58" },
  { id: "L-1028", businessName: "Healthy Paws Vet", niche: "Veterinarians — Lahore", status: "mailed", lastAction: "Cold email sent", lastActionTimestamp: "2026-07-22 15:30" },
];

function countBy(leads: Lead[]) {
  return {
    interested: leads.filter((l) => l.status === "interested_awaiting_review").length,
    notInterested: leads.filter((l) => l.status === "not_interested").length,
    pendingResponse: leads.filter((l) => l.status === "mailed").length,
    replies: leads.filter((l) => l.status === "replied" || l.status === "interested_awaiting_review").length,
  };
}

const todayLeads = ALL_LEADS.slice(0, 10);
const t = countBy(todayLeads);

const weekLeads = ALL_LEADS;
const w = countBy(weekLeads);

// Reports keyed by range. Numbers are illustrative mock values.
export const OUTREACH_BY_RANGE: Record<DateRange, DailyReport> = {
  today: {
    date: "2026-07-23",
    stats: {
      leadsFound: 42,
      leadsVerified: 36,
      emailsSent: 28,
      repliesReceived: t.replies,
      interested: t.interested,
      notInterested: t.notInterested,
      pendingResponse: t.pendingResponse,
    },
    leads: todayLeads,
  },
  week: {
    date: "2026-07-17 → 2026-07-23",
    stats: {
      leadsFound: 214,
      leadsVerified: 181,
      emailsSent: 158,
      repliesReceived: 39,
      interested: 11,
      notInterested: 17,
      pendingResponse: w.pendingResponse + 46,
    },
    leads: weekLeads,
  },
  month: {
    date: "2026-07-01 → 2026-07-23",
    stats: {
      leadsFound: 903,
      leadsVerified: 742,
      emailsSent: 690,
      repliesReceived: 172,
      interested: 54,
      notInterested: 71,
      pendingResponse: 205,
    },
    leads: weekLeads,
  },
};

// 7-day outreach volume for the dashboard chart.
export const OUTREACH_TREND: { day: string; emailsSent: number; replies: number }[] = [
  { day: "Thu", emailsSent: 22, replies: 4 },
  { day: "Fri", emailsSent: 31, replies: 7 },
  { day: "Sat", emailsSent: 18, replies: 3 },
  { day: "Sun", emailsSent: 9, replies: 2 },
  { day: "Mon", emailsSent: 26, replies: 6 },
  { day: "Tue", emailsSent: 34, replies: 8 },
  { day: "Wed", emailsSent: 28, replies: 9 },
];
