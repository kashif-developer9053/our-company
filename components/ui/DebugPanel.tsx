"use client";

import { useState } from "react";
import type { LiveStatus } from "@/lib/api";
import { roleLabel } from "@/lib/api";
import { AGENT_STATUS_OPTIONS, IT_STATUS_OPTIONS } from "@/types/officeTypes";

interface Props {
  status: LiveStatus | null;
  onSetAgentStatus: (id: string, status: string) => void;
  onSetOffice: (open: boolean) => void;
  onSetMeeting: (inProgress: boolean) => void;
}

// DEV DEBUG PANEL — Phase 1 only, remove/hide in production.
// Now writes through to the backend status board (via the callbacks) rather than
// mutating a local mock object. Renders a row per agent from the live list.
export default function DebugPanel({ status, onSetAgentStatus, onSetOffice, onSetMeeting }: Props) {
  const [collapsed, setCollapsed] = useState(false);
  const agents = status ? Object.values(status.agents) : [];

  return (
    <div className={`debug-panel ${collapsed ? "collapsed" : ""}`}>
      <div className="debug-head" onClick={() => setCollapsed((c) => !c)}>
        <span>DEV DEBUG PANEL — writes to backend</span>
        <span>{collapsed ? "▲" : "▼"}</span>
      </div>

      {!collapsed && (
        <div className="debug-body">
          <label className="debug-flag">
            <input
              type="checkbox"
              checked={status?.office_open ?? false}
              onChange={(e) => onSetOffice(e.target.checked)}
            />
            office_open
          </label>
          <label className="debug-flag">
            <input
              type="checkbox"
              checked={status?.meeting_in_progress ?? false}
              onChange={(e) => onSetMeeting(e.target.checked)}
            />
            meeting_in_progress
          </label>

          <div className="debug-divider" />

          {agents.map((a) => {
            const options = a.role_key === "it_monitor" ? IT_STATUS_OPTIONS : AGENT_STATUS_OPTIONS;
            return (
              <div className="debug-row" key={a.id}>
                <span className="debug-name" title={roleLabel(a.role_key)}>{a.name}</span>
                <select value={a.status} onChange={(e) => onSetAgentStatus(a.id, e.target.value)}>
                  {options.map((o) => (
                    <option key={o} value={o}>{o}</option>
                  ))}
                  {/* Ensure the current status is selectable even if outside the set */}
                  {!options.includes(a.status as never) && <option value={a.status}>{a.status}</option>}
                </select>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
