"use client";

import { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { useRouter } from "next/navigation";
import * as api from "@/lib/api";
import type { AppNotification } from "@/lib/api";

const KIND_META: Record<string, { icon: string; color: string; label: string }> = {
  approval: { icon: "✋", color: "#e0b341", label: "Needs approval" },
  config: { icon: "⚙", color: "#4aa3ff", label: "Setup needed" },
  alert: { icon: "⚠", color: "#e06c6c", label: "Problem" },
  info: { icon: "✓", color: "#5bbf87", label: "Update" },
};

// The CEO's inbox. Polls for anything that needs attention — lead batches to
// approve, missing email config, agent failures — so nothing waits unseen.
export default function NotificationBell() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<AppNotification[]>([]);
  const [unread, setUnread] = useState(0);

  const load = useCallback(async () => {
    try {
      const r = await api.getNotifications();
      setItems(r.notifications);
      setUnread(r.unread);
    } catch { /* backend down — stay quiet */ }
  }, []);

  useEffect(() => {
    load();
    const t = setInterval(load, 15000); // gentle poll
    return () => clearInterval(t);
  }, [load]);

  const openItem = async (n: AppNotification) => {
    try { await api.markNotificationRead(n.id); } catch { /* */ }
    setOpen(false);
    load();
    if (n.action === "leads_pending") router.push("/leads?pending=1");
    else if (n.action === "settings_email") router.push("/settings");
    else if (n.action === "replies_pending") router.push("/leads");
  };

  const readAll = async () => {
    try { await api.markAllNotificationsRead(); } catch { /* */ }
    load();
  };

  return (
    <>
      <button className="notif-bell" onClick={() => setOpen(true)} title="Notifications">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none">
          <path d="M12 3a6 6 0 0 0-6 6v3.6L4.5 15h15L18 12.6V9a6 6 0 0 0-6-6ZM10 18a2 2 0 0 0 4 0"
            stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" strokeLinecap="round" />
        </svg>
        {unread > 0 && <span className="notif-badge">{unread > 9 ? "9+" : unread}</span>}
      </button>

      {open && typeof document !== "undefined" && createPortal(
        <div className="chat-overlay" onClick={() => setOpen(false)}>
          <div className="chat-window" onClick={(e) => e.stopPropagation()} style={{ width: 460 }}>
            <div className="chat-head">
              <div>
                <div className="name">Notifications</div>
                <div className="role">{unread} unread · things waiting on you</div>
              </div>
              <button className="x" onClick={() => setOpen(false)} aria-label="Close">×</button>
            </div>

            {items.length > 0 && (
              <div style={{ marginBottom: 8 }}>
                <button className="btn-mini" onClick={readAll}>Mark all read</button>
              </div>
            )}

            <div className="notif-list">
              {items.length === 0 && (
                <div className="chat-hint">Nothing needs your attention right now.</div>
              )}
              {items.map((n) => {
                const m = KIND_META[n.kind] || KIND_META.info;
                return (
                  <button key={n.id} className={`notif-item ${n.read ? "" : "unread"}`} onClick={() => openItem(n)}>
                    <span className="notif-icon" style={{ color: m.color }}>{m.icon}</span>
                    <span className="notif-text">
                      <span className="notif-title">{n.title}</span>
                      <span className="notif-body">{n.body}</span>
                      <span className="notif-meta" style={{ color: m.color }}>{m.label}</span>
                    </span>
                  </button>
                );
              })}
            </div>
          </div>
        </div>,
        document.body
      )}
    </>
  );
}
