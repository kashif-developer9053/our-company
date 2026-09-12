"use client";

import { useCallback, useEffect, useState } from "react";
import * as api from "@/lib/api";
import type { MailItem, MailCounts } from "@/lib/api";

// A familiar mail-client layout for outreach: folder rail on the left, message
// list in the middle, full message on the right. Drafts are the only folder with
// actions — nothing is ever sent without an explicit approval here.
const FOLDERS = [
  { key: "drafts", label: "Drafts", icon: "M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" },
  // Approved but held back by the daily send cap. Without this folder they
  // were invisible: gone from Drafts, not yet in Sent.
  { key: "queued", label: "Queued", icon: "M12 8v4l3 2M12 22a10 10 0 1 1 0-20 10 10 0 0 1 0 20Z" },
  { key: "sent", label: "Sent", icon: "m22 2-7 20-4-9-9-4Z" },
  { key: "inbox", label: "Inbox", icon: "M22 12h-6l-2 3h-4l-2-3H2M5.5 5h13l3.5 7v6a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-6Z" },
  { key: "archive", label: "Archive", icon: "M21 8v13H3V8M1 3h22v5H1zM10 12h4" },
  { key: "failed", label: "Failed", icon: "M12 9v4m0 4h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z" },
  { key: "rejected", label: "Discarded", icon: "M3 6h18M8 6V4h8v2M19 6l-1 14H6L5 6" },
] as const;

function Icon({ d }: { d: string }) {
  return (
    <svg width="17" height="17" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d={d} /></svg>
  );
}

function when(iso: string) {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const today = new Date();
  const sameDay = d.toDateString() === today.toDateString();
  return sameDay
    ? d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })
    : d.toLocaleDateString([], { day: "numeric", month: "short" });
}

export default function Mailbox({ onChanged }: { onChanged?: () => void }) {
  const [folder, setFolder] = useState<string>("drafts");
  const [items, setItems] = useState<MailItem[]>([]);
  const [counts, setCounts] = useState<MailCounts | null>(null);
  const [openId, setOpenId] = useState<string | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [view, setView] = useState<"design" | "text">("design");
  const [editing, setEditing] = useState(false);
  const [eTo, setETo] = useState(""); const [eSub, setESub] = useState(""); const [eBody, setEBody] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [replying, setReplying] = useState(false);
  const [replyText, setReplyText] = useState("");
  const [count, setCount] = useState(10);
  // Campaign filters: write to one city / industry at a time.
  const [city, setCity] = useState("");
  const [niche, setNiche] = useState("");
  const [targets, setTargets] = useState<{ total: number; cities: api.DraftTarget[]; niches: api.DraftTarget[] }>(
    { total: 0, cities: [], niches: [] });

  const load = useCallback(async (f: string) => {
    try {
      const r = await api.getMailbox(f);
      setItems(r.items); setCounts(r.counts);
      setPicked(new Set(f === "drafts" ? r.items.map((i) => i.id) : []));
      setOpenId(r.items[0]?.id ?? null);
    } catch { /* backend down */ }
  }, []);
  useEffect(() => { load(folder); }, [folder, load]);

  const loadTargets = useCallback(async () => {
    try {
      const r = await api.getDraftTargets();
      setTargets({ total: r.total, cities: r.cities, niches: r.niches });
    } catch { /* backend down */ }
  }, []);
  useEffect(() => { loadTargets(); }, [loadTargets]);

  const open = items.find((i) => i.id === openId) || null;

  // Opening a reply marks it read, so the unread highlight clears like a real
  // mail client. Fire-and-forget; a failure here must not block reading.
  useEffect(() => {
    if (!open || open.kind !== "inbound" || open.read || !open.lead_id) return;
    api.markReplyRead({ lead_id: open.lead_id, received_at: open.at })
      .then(() => { setItems((xs) => xs.map((x) => x.id === open.id ? { ...x, read: true } : x)); })
      .catch(() => {});
  }, [open]);

  const replyRef = (i: MailItem) => ({ lead_id: i.lead_id || "", received_at: i.at });

  const doArchive = async (i: MailItem) => {
    setBusy("arch");
    try {
      await (folder === "archive" ? api.unarchiveReply(replyRef(i)) : api.archiveReply(replyRef(i)));
      setMsg(folder === "archive" ? "Moved back to inbox." : "Archived.");
      await load(folder);
    } catch (e) { setMsg(`⚠ ${(e as Error).message}`); }
    finally { setBusy(null); }
  };

  const doDelete = async (i: MailItem) => {
    if (!confirm(`Delete this reply from ${i.business_name}?`)) return;
    setBusy("del");
    try { await api.deleteReply(replyRef(i)); setMsg("Deleted."); await load(folder); }
    catch (e) { setMsg(`⚠ ${(e as Error).message}`); }
    finally { setBusy(null); }
  };

  const doSendReply = async (i: MailItem) => {
    if (!replyText.trim()) { setMsg("Write a reply first."); return; }
    setBusy("reply");
    try {
      const r = await api.sendInboxReply({ ...replyRef(i), subject: `Re: ${i.subject}`, body: replyText });
      setMsg(r.ok ? (r.note || "Reply sent.") : `⚠ ${r.error}`);
      if (r.ok) { setReplying(false); setReplyText(""); await load(folder); }
    } catch (e) { setMsg(`⚠ ${(e as Error).message}`); }
    finally { setBusy(null); }
  };
  const isDrafts = folder === "drafts";

  const toggle = (id: string) => setPicked((s) => {
    const n = new Set(s); n.has(id) ? n.delete(id) : n.add(id); return n;
  });

  const writeBatch = async () => {
    setBusy("write"); setMsg(null);
    try {
      const r = await api.draftEmailBatch({ count, city: city || undefined, niche: niche || undefined });
      setMsg(r.note || `Agent 3 wrote ${r.drafted} email(s).`);
      await load("drafts"); setFolder("drafts"); loadTargets();
    } catch (e) { setMsg(`⚠ ${(e as Error).message}`); }
    finally { setBusy(null); }
  };

  const saveEdit = async () => {
    if (!open) return;
    setBusy("edit");
    try {
      await api.editDraft(open.id, { subject: eSub, body: eBody, to_email: eTo });
      setEditing(false); await load(folder);
    } catch (e) { setMsg(`⚠ ${(e as Error).message}`); }
    finally { setBusy(null); }
  };

  const sendPicked = async () => {
    const ids = Array.from(picked);
    if (!ids.length) { setMsg("Tick at least one email."); return; }
    if (!confirm(`Send ${ids.length} email(s) to real prospects now?`)) return;
    setBusy("send"); setMsg(null);
    try {
      const r = await api.approveAndSendDrafts({ draft_ids: ids });
      setMsg(r.ok ? (r.note || "Sending…") : `⚠ ${r.error}`);
      await load(folder); onChanged?.();
    } finally { setBusy(null); }
  };

  // Failed sends are kept, not discarded — a timeout or blocked port is usually
  // transient, so the draft can simply be re-queued and sent again.
  const retry = async (ids?: string[]) => {
    setBusy("retry"); setMsg(null);
    try {
      const r = await api.retryFailedDrafts(ids ? { draft_ids: ids } : {});
      setMsg(r.ok ? (r.note || "Retrying…") : `⚠ ${r.error}`);
      await load(folder); onChanged?.();
    } catch (e) { setMsg(`⚠ ${(e as Error).message}`); }
    finally { setBusy(null); }
  };

  const discardPicked = async () => {
    const ids = Array.from(picked);
    if (!ids.length || !confirm(`Discard ${ids.length} draft(s)?`)) return;
    setBusy("reject");
    try { await api.rejectDrafts({ draft_ids: ids }); setMsg(`Discarded ${ids.length}.`); await load(folder); }
    finally { setBusy(null); }
  };

  return (
    <div className="mailbox">
      {/* folder rail */}
      <aside className="mb-folders">
        <div className="mb-filters">
          <select className="af-input" value={city} onChange={(e) => setCity(e.target.value)} disabled={!!busy}>
            <option value="">All cities ({targets.total})</option>
            {targets.cities.map((c) => (
              <option key={c.value} value={c.value}>{c.value} ({c.count})</option>
            ))}
          </select>
          <select className="af-input" value={niche} onChange={(e) => setNiche(e.target.value)} disabled={!!busy}>
            <option value="">All industries</option>
            {targets.niches.map((n) => (
              <option key={n.value} value={n.value}>{n.value.slice(0, 22)} ({n.count})</option>
            ))}
          </select>
        </div>
        <button className="btn-mini primary mb-compose" onClick={writeBatch} disabled={busy === "write"}>
          {busy === "write" ? "Writing…" : `✎ Write ${count} email${count === 1 ? "" : "s"}`}
        </button>
        <div className="mb-count-row">
          <input className="af-input" type="number" min={1} max={50} value={count}
            onChange={(e) => setCount(Number(e.target.value))} disabled={!!busy} />
          <span className="muted small">at a time</span>
        </div>
        {FOLDERS.map((f) => {
          const n = counts
            ? (f.key === "inbox" ? (counts.unread ?? 0) : ((counts as any)[f.key] ?? 0))
            : 0;
          return (
            <button key={f.key} className={`mb-folder ${folder === f.key ? "active" : ""}`}
              onClick={() => { setFolder(f.key); setEditing(false); }}>
              <Icon d={f.icon} />
              <span className="mb-folder-label">{f.label}</span>
              {n > 0 && <span className="mb-badge">{n}</span>}
            </button>
          );
        })}
      </aside>

      {/* message list */}
      <div className="mb-list">
        <div className="mb-list-head">
          <span>{FOLDERS.find((f) => f.key === folder)?.label} · {items.length}</span>
          {isDrafts && items.length > 0 && (
            <span className="mb-list-actions">
              <button className="btn-mini" onClick={() => setPicked(new Set(items.map((i) => i.id)))}>All</button>
              <button className="btn-mini" onClick={() => setPicked(new Set())}>None</button>
            </span>
          )}
        </div>
        {items.length === 0 && <div className="mb-empty">Nothing here.</div>}
        {items.map((i) => (
          <button key={i.id}
            className={`mb-row ${openId === i.id ? "open" : ""} ${i.kind === "inbound" && !i.read ? "unread" : ""}`}
            onClick={() => { setOpenId(i.id); setEditing(false); setReplying(false); }}>
            {isDrafts && (
              <input type="checkbox" checked={picked.has(i.id)} onClick={(e) => e.stopPropagation()}
                onChange={() => toggle(i.id)} />
            )}
            <span className="mb-row-main">
              <span className="mb-row-top">
                <span className="mb-row-name">
                  {i.kind === "inbound" && !i.read && <span className="mb-dot" />}
                  {i.business_name || i.to_email}
                </span>
                <span className="mb-row-time">{when(i.at)}</span>
              </span>
              <span className="mb-row-subject">{i.subject}</span>
              <span className="mb-row-preview">{i.preview}</span>
            </span>
          </button>
        ))}
      </div>

      {/* reading pane */}
      <div className="mb-read">
        {msg && <div className="pending-msg" style={{ marginBottom: 10 }}>{msg}</div>}
        {!open ? (
          <div className="mb-empty">Select a message.</div>
        ) : (
          <>
            <div className="mb-read-head">
              <div>
                <div className="mb-read-subject">{open.subject}</div>
                <div className="muted small">
                  {open.kind === "inbound" ? "from " : "to "}{open.to_email}
                  {open.edited && <span className="soon-tag" style={{ marginLeft: 6 }}>edited</span>}
                </div>
              </div>
              {open.kind === "outbound" && (
                <div className="draft-actions">
                  <button className={`chip ${view === "design" ? "active" : ""}`} onClick={() => setView("design")}>Design</button>
                  <button className={`chip ${view === "text" ? "active" : ""}`} onClick={() => setView("text")}>Text</button>
                  {isDrafts && (
                    <button className="btn-mini" onClick={() => {
                      setEditing(!editing); setETo(open.to_email); setESub(open.subject); setEBody(open.body);
                    }}>{editing ? "Cancel" : "Edit"}</button>
                  )}
                </div>
              )}
            </div>

            {open.kind === "inbound" && (
              <div className="pending-actions" style={{ marginBottom: 12 }}>
                <button className="btn-mini primary" disabled={busy === "reply"}
                  onClick={() => { setReplying(!replying); setReplyText(open.suggested_reply || ""); }}>
                  {replying ? "Cancel reply" : "↩ Reply"}
                </button>
                <button className="btn-mini" disabled={busy === "arch"} onClick={() => doArchive(open)}>
                  {folder === "archive" ? "Move to inbox" : "Archive"}
                </button>
                <button className="btn-mini danger" disabled={busy === "del"} onClick={() => doDelete(open)}>
                  Delete
                </button>
              </div>
            )}

            {open.kind === "inbound" && replying && (
              <div className="draft-edit" style={{ marginBottom: 12 }}>
                <label className="build-label">Your reply to {open.to_email}</label>
                <textarea className="af-input" rows={8} value={replyText}
                  onChange={(e) => setReplyText(e.target.value)}
                  placeholder="Type your reply…" />
                <button className="btn-mini primary" disabled={busy === "reply"}
                  onClick={() => doSendReply(open)}>
                  {busy === "reply" ? "Sending…" : "Send reply"}
                </button>
                {open.suggested_reply && (
                  <p className="muted small" style={{ margin: 0 }}>
                    Pre-filled with Agent 3&apos;s suggestion — edit it before sending.
                  </p>
                )}
              </div>
            )}

            {open.error && <div className="draft-flags">⚠ {open.error}</div>}
            {open.collection_reason && <div className="draft-reason">Why this lead: {open.collection_reason}</div>}
            {open.reply_reasoning && <div className="draft-reason">Classified: {open.status} — {open.reply_reasoning}</div>}
            {(open.spam_flags?.length ?? 0) > 0 && <div className="draft-flags">⚠ {open.spam_flags!.join(" · ")}</div>}

            {editing ? (
              <div className="draft-edit">
                <label className="build-label">Send to</label>
                <input className="af-input" type="email" value={eTo} onChange={(e) => setETo(e.target.value)} />
                <label className="build-label" style={{ marginTop: 6 }}>Subject</label>
                <input className="af-input" value={eSub} onChange={(e) => setESub(e.target.value)} />
                <label className="build-label" style={{ marginTop: 6 }}>Message</label>
                <textarea className="af-input" rows={10} value={eBody} onChange={(e) => setEBody(e.target.value)} />
                <button className="btn-mini primary" disabled={busy === "edit"} onClick={saveEdit}>Save &amp; re-render</button>
              </div>
            ) : open.kind === "outbound" && view === "design" && open.html ? (
              <iframe className="mb-preview" title="Email preview" sandbox="" srcDoc={open.html} />
            ) : (
              <pre className="draft-text">{open.body}</pre>
            )}

            {isDrafts && !editing && (
              <div className="pending-actions">
                <button className="btn-mini primary" disabled={busy === "send"} onClick={sendPicked}>
                  {busy === "send" ? "Sending…" : `Approve & send ${picked.size}`}
                </button>
                <button className="btn-mini danger" disabled={busy === "reject"} onClick={discardPicked}>
                  Discard {picked.size}
                </button>
              </div>
            )}

            {folder === "failed" && (
              <div className="pending-actions">
                <button className="btn-mini primary" disabled={busy === "retry"}
                  onClick={() => retry([open.id])}>
                  {busy === "retry" ? "Retrying…" : "Retry this email"}
                </button>
                <button className="btn-mini" disabled={busy === "retry"} onClick={() => retry()}>
                  Retry all failed
                </button>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}
