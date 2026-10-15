"use client";

import { useAuth } from "@/lib/auth-context";
import type { User } from "@/lib/api";

// The cold caller's entire chrome: who he is, and a way out. No navigation,
// because there is nowhere else for him to go — the backend refuses every
// other route, and offering links that fail would only confuse him.
export default function CallerBar({ user, onProfile }: { user: User; onProfile: () => void }) {
  const { logout } = useAuth();
  return (
    <header className="caller-bar">
      <div className="caller-brand">
        <span className="caller-dot" />
        <strong>Call Desk</strong>
      </div>
      <div className="caller-right">
        <button className="btn-mini" onClick={onProfile}>{user.name || "Profile"}</button>
        <button className="btn-mini" onClick={logout}>Logout</button>
      </div>
    </header>
  );
}
