"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import type { User } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";

const ICONS: Record<string, ReactNode> = {
  office: (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
      <path d="M3 21h18M5 21V5a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v16M13 21V9a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v12" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
      <path d="M8 8h1M8 12h1M8 16h1M16 12h1M16 16h1" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  ),
  reports: (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
      <path d="M4 20V4M4 20h16" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      <rect x="7" y="12" width="3" height="5" stroke="currentColor" strokeWidth="1.6" />
      <rect x="12" y="9" width="3" height="8" stroke="currentColor" strokeWidth="1.6" />
      <rect x="17" y="6" width="3" height="11" stroke="currentColor" strokeWidth="1.6" />
    </svg>
  ),
  leads: (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
      <rect x="3" y="5" width="18" height="14" rx="2" stroke="currentColor" strokeWidth="1.6" />
      <path d="M3 9h18M9 5v14" stroke="currentColor" strokeWidth="1.6" />
    </svg>
  ),
  users: (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
      <circle cx="9" cy="8" r="3" stroke="currentColor" strokeWidth="1.6" />
      <path d="M3 20c0-3.3 2.7-6 6-6s6 2.7 6 6" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
      <path d="M16 3.5a3 3 0 0 1 0 5.8M21 20a5.5 5.5 0 0 0-4-5.3" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  ),
  settings: (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
      <circle cx="12" cy="12" r="3" stroke="currentColor" strokeWidth="1.6" />
      <path d="M12 3v3M12 18v3M3 12h3M18 12h3M5.6 5.6l2.1 2.1M16.3 16.3l2.1 2.1M18.4 5.6l-2.1 2.1M7.7 16.3l-2.1 2.1" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  ),
  grow: (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
      <path d="M12 20v-8M12 12c0-3 2-5 5-5 0 3-2 5-5 5ZM12 14c0-2.5-1.7-4-4-4 0 2.5 1.7 4 4 4Z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
    </svg>
  ),
  knowledge: (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
      <path d="M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2V5Z" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
      <path d="M8 7h7M8 11h7" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  ),
  outreach: (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
      <rect x="3" y="5" width="18" height="14" rx="2" stroke="currentColor" strokeWidth="1.6" />
      <path d="m3 7 9 6 9-6" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
    </svg>
  ),
  strategy: (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
      <circle cx="12" cy="12" r="8" stroke="currentColor" strokeWidth="1.6" />
      <path d="M12 8v4l3 2" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  ),
};

export default function NavRail({ user, onProfile }: { user: User; onProfile: () => void }) {
  const pathname = usePathname();
  const { logout } = useAuth();
  const isAdmin = user.role === "admin";

  // Settings + User Management are ADMIN-only and genuinely not rendered for others.
  const items = [
    { href: "/", label: "Office", icon: ICONS.office, show: true },
    { href: "/reports", label: "Reports", icon: ICONS.reports, show: true },
    { href: "/leads", label: "CRM", icon: ICONS.leads, show: true },
    { href: "/outreach", label: "Outreach", icon: ICONS.outreach, show: true },
    { href: "/strategy", label: "Strategy", icon: ICONS.strategy, show: isAdmin },
    { href: "/knowledge", label: "Knowledge", icon: ICONS.knowledge, show: isAdmin },
    { href: "/grow", label: "Grow", icon: ICONS.grow, show: isAdmin },
    { href: "/users", label: "Users", icon: ICONS.users, show: isAdmin },
    { href: "/settings", label: "Settings", icon: ICONS.settings, show: isAdmin },
  ].filter((i) => i.show);

  return (
    <nav className="nav-rail">
      <div className="nav-logo" title="AI Agency">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
          <path d="M3 21h18M5 21V5a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v16M13 21V9a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v12" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" />
        </svg>
      </div>

      <div className="nav-items">
        {items.map((it) => {
          const active = it.href === "/" ? pathname === "/" : pathname.startsWith(it.href);
          return (
            <Link key={it.href} href={it.href} className={`nav-item ${active ? "active" : ""}`} title={it.label}>
              {it.icon}
              <span>{it.label}</span>
            </Link>
          );
        })}
      </div>

      <div className="nav-user">
        <button className="nav-avatar" onClick={onProfile} title="My profile">
          {user.name.slice(0, 1).toUpperCase()}
        </button>
        <div className="nav-user-name" title={`${user.name} · ${user.role}`}>{user.name.split(" ")[0]}</div>
        <div className="nav-user-role">{user.role}</div>
        <button className="nav-logout" onClick={logout} title="Log out">Log out</button>
      </div>
    </nav>
  );
}
