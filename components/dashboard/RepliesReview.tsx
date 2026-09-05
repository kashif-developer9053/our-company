"use client";

import { useCallback, useEffect, useState } from "react";
import * as api from "@/lib/api";
import type { PendingReply } from "@/lib/api";

// "Client Replies" review: interested/question/unclear replies surface here with
// the classification + a Claude-suggested response. NOTHING is auto-sent — the
// CEO must Send as-is, Edit & send, or Write manually.
export default function RepliesReview({ onChanged }: { onChanged: () => void }) {
  const [pending, setPending] = useState<PendingReply[]>([]);
  const [editing, setEditing] = useState<Record<string, string>>({});
  const [mode, setMode] = useState<Record<string, "as_is" | "edit" | "manual">>({});
  const [busy, setBusy] = useState<string | null>(null);

  const load = useCallback(async () => {
    try { setPending(await api.getPendingReplies()); } catch { /* ignore */ }
  }, []);
  useEffect(() => { load(); const t = setInterval(load, 5000); return () => clearInterval(t); }, [load]);

  if (pending.length === 0) return null;

  const setModeFor = (id: string, m: "as_is" | "edit" | "manual", suggested: string) => {
    setMode({ ...mode, [id]: m });
    if (m === "edit") setEditing({ ...editing, [id]: suggested });
    if (m === "manual") setEditing({ ...editing, [id]: "" });
  };

  const send = async (p: PendingReply) => {
    const m = mode[p.id] || "as_is";
    setBusy(p.id);
    try {
      const body = m === "as_is" ? undefined : editing[p.id];
      const r = await api.sendLeadReply(p.id, m, body);
      if (!r.ok) { alert(r.error || "Send failed"); return; }
      await load(); onChanged();
    } catch (e) { alert((e as Error).message); } finally { setBusy(null); }
  };

  return (
    <div className="panel replies-panel">
      <div className="panel-head">
        <h2>Client replies — needs your review <span className="review-count">{pending.length}</span></h2>
      </div>
      {pending.map((p) => {
        const m = mode[p.id] || "as_is";
        return (
          <div key={p.id} className="reply-card">
            <div className="reply-top">
              <div><span className="lead-name">{p.business_name}</span> <span className="muted">{p.email}</span></div>
              <span className="lead-badge" style={{ color: "#f2c14e", borderColor: "#f2c14e" }}>{p.classification || "reply"}</span>
            </div>
            <div className="reply-quote"><span className="reply-label">Their reply</span>{p.reply || "(no text)"}</div>
            {p.reasoning && <div className="reply-reason">Claude: {p.reasoning}</div>}

            <div className="reply-suggest">
              <span className="reply-label">Suggested response</span>
              {m === "as_is" ? (
                <div className="reply-suggest-text">{p.suggested_reply || "(none generated)"}</div>
              ) : (
                <textarea className="af-input" rows={4} value={editing[p.id] ?? ""} onChange={(e) => setEditing({ ...editing, [p.id]: e.target.value })} placeholder={m === "manual" ? "Write your own reply…" : "Edit the suggested reply…"} />
              )}
            </div>

            <div className="reply-actions">
              <div className="reply-modes">
                <button className={`chip ${m === "as_is" ? "active" : ""}`} onClick={() => setModeFor(p.id, "as_is", p.suggested_reply)}>Send as-is</button>
                <button className={`chip ${m === "edit" ? "active" : ""}`} onClick={() => setModeFor(p.id, "edit", p.suggested_reply)}>Edit & send</button>
                <button className={`chip ${m === "manual" ? "active" : ""}`} onClick={() => setModeFor(p.id, "manual", p.suggested_reply)}>Write manually</button>
              </div>
              <button className="btn-mini primary" disabled={busy === p.id} onClick={() => send(p)}>Send reply</button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
