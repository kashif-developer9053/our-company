import type { AgentActivity } from "@/types/dashboardTypes";
import type { AgentId } from "@/types/officeTypes";

// PHASE 1.6 mock: per-agent activity for the Team Activity sidebar. The `status`
// here is only a default — the sidebar shows the LIVE status from the office
// status board so the badge always matches the map. Shape maps onto a future
// "agent activity/logs" API.
export const AGENT_ACTIVITY: Record<AgentId, AgentActivity> = {
  supervisor: {
    agentId: "supervisor",
    name: "Supervisor",
    role: "Manager",
    status: "idle",
    currentTask: "Reviewing Agent 1's niche suggestions",
    lastUpdated: "1 min ago",
    recentActivity: [
      { timestamp: "10:15 AM", message: "Compiled morning status report for CEO" },
      { timestamp: "10:09 AM", message: "Approved 3 of 4 niche suggestions" },
      { timestamp: "10:01 AM", message: "Started daily stand-up review" },
    ],
  },
  agent1: {
    agentId: "agent1",
    name: "Agent 1",
    role: "Researcher",
    status: "working",
    currentTask: "Scraping leads for: Dentists in Islamabad",
    lastUpdated: "2 min ago",
    recentActivity: [
      { timestamp: "10:12 AM", message: "Started scraping leads (42 found so far)" },
      { timestamp: "10:05 AM", message: "Niche approved by CEO" },
      { timestamp: "10:02 AM", message: "Found 4 niche suggestions" },
      { timestamp: "09:58 AM", message: "Began market research pass" },
    ],
  },
  agent2: {
    agentId: "agent2",
    name: "Agent 2",
    role: "Verifier",
    status: "working",
    currentTask: "Verifying 42 leads (checking duplicates + validity)",
    lastUpdated: "just now",
    recentActivity: [
      { timestamp: "10:14 AM", message: "Removed 6 duplicate leads" },
      { timestamp: "10:10 AM", message: "Verified 28 leads into CRM" },
      { timestamp: "10:06 AM", message: "Received lead batch from Agent 1" },
    ],
  },
  agent3: {
    agentId: "agent3",
    name: "Agent 3",
    role: "Outreach",
    status: "idle",
    currentTask: "Idle — waiting for verified leads to email",
    lastUpdated: "4 min ago",
    recentActivity: [
      { timestamp: "10:11 AM", message: "Sent 12 cold emails" },
      { timestamp: "10:03 AM", message: "Drafted personalized email templates" },
      { timestamp: "09:55 AM", message: "Reviewed reply queue (2 need CEO review)" },
    ],
  },
  it_monitor: {
    agentId: "it_monitor",
    name: "IT Tech",
    role: "System Health",
    status: "warning",
    currentTask: "Monitoring — Claude API latency slightly elevated",
    lastUpdated: "30 sec ago",
    recentActivity: [
      { timestamp: "10:15 AM", message: "Claude API p95 latency at 4.2s (warning)" },
      { timestamp: "10:00 AM", message: "All systems nominal" },
      { timestamp: "09:45 AM", message: "MongoDB + scraper health checks passed" },
    ],
    errorDetail:
      "Claude API response times are elevated (p95 = 4.2s vs 1.5s normal). Not failing yet — monitoring. If it degrades to timeouts, outreach message writing may slow down.",
  },
};
