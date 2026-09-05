// Shared types for the whole office UI. When the real backend/WebSocket status
// board arrives in a later phase, it must emit this EXACT shape so nothing else
// in the codebase has to change structurally — only the data source.

export type AgentId =
  | "supervisor"
  | "agent1"
  | "agent2"
  | "agent3"
  | "it_monitor";

// Status set for the four "worker" agents + supervisor.
export type AgentStatus =
  | "offline"
  | "idle"
  | "working"
  | "error"
  | "in_meeting"
  | "in_ceo_office";

// The IT Technician reports health instead of work status.
export type ItStatus =
  | "offline"
  | "ok"
  | "warning"
  | "risk"
  | "in_meeting"
  | "in_ceo_office";

// Union of every status value any character can hold.
export type AnyStatus = AgentStatus | ItStatus;

export interface AgentState {
  status: AgentStatus;
  location: string;
}

export interface ItState {
  status: ItStatus;
  location: string;
}

export interface OfficeStatus {
  office_open: boolean;
  meeting_in_progress: boolean;
  agents: {
    supervisor: AgentState;
    agent1: AgentState;
    agent2: AgentState;
    agent3: AgentState;
    it_monitor: ItState;
  };
}

// Visual metadata for every possible status: the human label + the color of the
// little status dot shown in a character's floating tag and in the debug panel.
export const STATUS_META: Record<AnyStatus, { label: string; color: string }> = {
  offline: { label: "Offline", color: "#9aa0a6" },
  idle: { label: "Idle", color: "#66bb6a" },
  working: { label: "Working", color: "#42a5f5" },
  error: { label: "Error", color: "#ef5350" },
  in_meeting: { label: "In Meeting", color: "#ba68c8" },
  in_ceo_office: { label: "In CEO Office", color: "#26c6da" },
  ok: { label: "OK", color: "#66bb6a" },
  warning: { label: "Warning", color: "#ffca28" },
  risk: { label: "Risk", color: "#ef5350" },
};

// The status options each agent can be flipped to in the dev debug panel.
export const AGENT_STATUS_OPTIONS: AgentStatus[] = [
  "offline",
  "idle",
  "working",
  "error",
  "in_meeting",
  "in_ceo_office",
];

export const IT_STATUS_OPTIONS: ItStatus[] = [
  "offline",
  "ok",
  "warning",
  "risk",
  "in_meeting",
  "in_ceo_office",
];
