"use client";

import NotificationBell from "./NotificationBell";

interface Props {
  officeOpen: boolean;
  onToggle: () => void;
}

// Polished app header: gradient bar, building icon, live office indicator, and
// the Open/Close toggle. Behavior is unchanged from Phase 1.
export default function TopBar({ officeOpen, onToggle }: Props) {
  return (
    <header className="topbar">
      <div className="brand">
        <span className="brand-icon" aria-hidden>
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
            <path
              d="M3 21h18M5 21V5a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v16M13 21V9a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v12"
              stroke="currentColor"
              strokeWidth="1.6"
              strokeLinejoin="round"
            />
            <path d="M8 8h1M8 12h1M8 16h1M16 12h1M16 16h1" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
          </svg>
        </span>
        <div>
          <h1>AI Agency · Virtual Office</h1>
          <div className="phase">Phase 10 · multi-provider AI + memory + knowledge</div>
        </div>
      </div>

      <div className="controls">
        <NotificationBell />
        <span className={`status-pill ${officeOpen ? "on" : ""}`}>
          <span className="pill-dot" />
          {officeOpen ? "Office OPEN" : "Office CLOSED"}
        </span>
        <button className={`btn ${officeOpen ? "close" : "open"}`} onClick={onToggle}>
          {officeOpen ? "Close Office" : "Open Office"}
        </button>
      </div>
    </header>
  );
}
