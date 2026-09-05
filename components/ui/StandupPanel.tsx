"use client";

import { useEffect, useState } from "react";
import * as api from "@/lib/api";
import type { Standup } from "@/lib/api";

// Daily standup modal — shown while meeting_in_progress. The Supervisor's real
// per-agent summary is displayed; the CEO acknowledges to end the meeting (chosen
// over a fixed timer so the CEO actually reads it), with a 45s auto-end fallback
// so the office can never get stuck in the meeting state.
export default function StandupPanel({ onEnd }: { onEnd: () => void }) {
  const [standup, setStandup] = useState<Standup | null>(null);
  const [ending, setEnding] = useState(false);

  useEffect(() => {
    api.getStandup().then(setStandup).catch(() => {});
    const fallback = setTimeout(() => end(), 45000);
    return () => clearTimeout(fallback);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const end = async () => {
    if (ending) return;
    setEnding(true);
    try { await api.setMeeting(false); } catch { /* ignore */ }
    onEnd();
  };

  return (
    <div className="chat-overlay">
      <div className="chat-window standup-window" onClick={(e) => e.stopPropagation()}>
        <div className="chat-head">
          <div>
            <div className="name">☕ Daily Standup{standup?.date ? ` — ${standup.date}` : ""}</div>
            <div className="role">Everyone’s in the Meeting Room. Supervisor’s morning summary:</div>
          </div>
        </div>

        {standup?.summary && <div className="standup-summary">{standup.summary}</div>}

        <div className="standup-reports">
          {(standup?.reports || []).map((r, i) => (
            <div key={i} className="standup-report">
              <div className="standup-agent">{r.agent}</div>
              <div className="standup-text">{r.text}</div>
            </div>
          ))}
          {!standup && <div className="chat-hint">Gathering reports…</div>}
        </div>

        <button className="btn open standup-go" disabled={ending} onClick={end}>
          {ending ? "Starting the day…" : "Got it — start the day →"}
        </button>
      </div>
    </div>
  );
}
