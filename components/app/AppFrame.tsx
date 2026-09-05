"use client";

import { useState } from "react";
import { useAuth } from "@/lib/auth-context";
import NavRail from "@/components/ui/NavRail";
import AuthScreen from "@/components/auth/AuthScreen";
import ProfileModal from "@/components/ui/ProfileModal";

// Gates the whole app: shows a loader, then the login/setup screen if there's no
// session, otherwise the nav rail + page. Protected pages never render (and thus
// never fetch) until a user is present.
export default function AppFrame({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const [profileOpen, setProfileOpen] = useState(false);

  if (loading) return <div className="app-loading">Loading…</div>;
  if (!user) return <AuthScreen />;

  return (
    <div className="app-shell">
      <NavRail user={user} onProfile={() => setProfileOpen(true)} />
      <div className="app-main">{children}</div>
      {profileOpen && <ProfileModal onClose={() => setProfileOpen(false)} />}
    </div>
  );
}
