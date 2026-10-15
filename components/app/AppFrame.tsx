"use client";

import { useState } from "react";
import { useAuth } from "@/lib/auth-context";
import NavRail from "@/components/ui/NavRail";
import AuthScreen from "@/components/auth/AuthScreen";
import ProfileModal from "@/components/ui/ProfileModal";
import CallDesk from "@/components/calls/CallDesk";
import CallerBar from "@/components/calls/CallerBar";

// Gates the whole app: shows a loader, then the login/setup screen if there's no
// session, otherwise the nav rail + page. Protected pages never render (and thus
// never fetch) until a user is present.
export default function AppFrame({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const [profileOpen, setProfileOpen] = useState(false);

  if (loading) return <div className="app-loading">Loading…</div>;
  if (!user) return <AuthScreen />;

  // A cold caller gets his own application, not the office with pages hidden.
  // He has one job, the backend refuses him everything else anyway, and a nav
  // rail full of links that 403 would only confuse someone non-technical.
  if (user.role === "caller") {
    return (
      <div className="caller-shell">
        <CallerBar user={user} onProfile={() => setProfileOpen(true)} />
        <div className="caller-main"><CallDesk callerName={user.name || ""} /></div>
        {profileOpen && <ProfileModal onClose={() => setProfileOpen(false)} />}
      </div>
    );
  }

  return (
    <div className="app-shell">
      <NavRail user={user} onProfile={() => setProfileOpen(true)} />
      <div className="app-main">{children}</div>
      {profileOpen && <ProfileModal onClose={() => setProfileOpen(false)} />}
    </div>
  );
}
