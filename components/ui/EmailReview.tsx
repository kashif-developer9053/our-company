"use client";

import { useCallback, useEffect, useState } from "react";
import * as api from "@/lib/api";
import type { EmailDraft } from "@/lib/api";

// CEO review desk: every drafted email is shown exactly as the recipient will
// see it (designed HTML in an isolated iframe), with the plain-text and the
// reason this lead was picked available alongside. Nothing sends without an
// explicit approval here.
export default function EmailReview({ onChanged }: { onChanged?: () => void }) {
  const [drafts, setDrafts] = useState<EmailDraft[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [view, setView] = useState<Record<string, "design" | "text">>({});
  const [editing, setEditing] = useState<string | null>(null);
  const [editSubject, setEditSubject] = useState("");
  const [editBody, setEditBody] = useState("");
  const [editTo, setEditTo] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [count, setCount] = useState(10);

  const load = useCallback(async () => {
    try {
      const r = await api.getDrafts("pending");
      setDrafts(r.drafts);
      setSelected(new Set(r.drafts.map((d) => d.id)));
    } catch { /* backend down */ }
  }, []);
  useEffect(() => { load(); }, [load]);

  const toggle = (id: string) => {
    setSelected((s) => {
      const n = new Set(s);
      if (n.has(id)) n.delete(id); else n.add(id);
      return n;
    });
  };

  const writeBatch = async () => {
    setBusy("write"); setMsg(null);
    try {
      const r = await api.draftEmailBatch({ count });
      setMsg(r.note ? r.note : `Agent 3 wrote ${r.drafted} email(s) — review them below.`);
      await load();
    } catch (e) { setMsg(`⚠ ${(e as Error).message}`); }
    finally { setBusy(null); }
  };

  const saveEdit = async (id: string) => {
    setBusy(id);
    try {
      await api.editDraft(id, { subject: editSubject, body: editBody, to_email: editTo });
      setEditing(null);
      await load();
    } finally { setBusy(null); }
  };

  const sendApproved = async () => {
    const ids = Array.from(selected);
    if (ids.length === 0) { setMsg("Tick at least one email to send."); return; }
    if (!confirm(`Send ${ids.length} email(s) to real prospects now?`)) return;
    setBusy("send"); setMsg(null);
    try {
      const r = await api.approveAndSendDrafts({ draft_ids: ids });
      setMsg(r.ok ? (r.note || "Sending…") : `⚠ ${r.error}`);
      await load();
      onChanged?.();
    } finally { setBusy(null); }
  };

  const rejectSelected = async () => {
    const ids = Array.from(selected);
    if (ids.length === 0) return;
    if (!confirm(`Discard ${ids.length} draft(s)?`)) return;
    setBusy("reject");
    try {
      await api.rejectDrafts({ draft_ids: ids });
      setMsg(`Discarded ${ids.length} draft(s).`);
      await load();
    } finally { setBusy(null); }
  };

  return (
    <div className="settings-card">
      <div className="settings-card-head">
        <h2>Email review {drafts.length > 0 && <span className="soon-tag">{drafts.length} awaiting you</span>}</h2>
      </div>
      <p className="pending-sub" style={{ color: "#8a93a6" }}>
        Agent 3 writes a different email for every prospect, built from the faults found on their own
        website plus your company details. Preview each one as the recipient sees it, edit anything,
        then approve. <strong>Nothing is sent until you approve it.</strong>
      </p>

      <div className="hunt-form" style={{ marginBottom: 12 }}>
        <input className="af-input" type="number" min={1} max={50} style={{ width: 80 }}
          value={count} onChange={(e) => setCount(Number(e.target.value))} disabled={!!busy} />
        <button className="btn-mini primary" onClick={writeBatch} disabled={busy === "write"}>
          {busy === "write" ? "Writing…" : `Write ${count} emails`}
        </button>
        {drafts.length > 0 && (
          <>
            <button className="btn-mini" onClick={() => setSelected(new Set(drafts.map((d) => d.id)))}>Select all</button>
            <button className="btn-mini" onClick={() => setSelected(new Set())}>Select none</button>
          </>
        )}
      </div>

      {msg && <div className="pending-msg">{msg}</div>}

      {drafts.length === 0 ? (
        <p className="muted small">No drafts waiting. Approve leads in the CRM, then write a batch above.</p>
      ) : (
        <>
          <div className="draft-list">
            {drafts.map((d) => {
              const mode = view[d.id] ?? "design";
              const isEditing = editing === d.id;
              return (
                <div key={d.id} className={`draft-card ${selected.has(d.id) ? "picked" : ""}`}>
                  <div className="draft-head">
                    <label className="draft-pick">
                      <input type="checkbox" checked={selected.has(d.id)} onChange={() => toggle(d.id)} />
                      <span>
                        <span className="lead-name">{d.business_name}</span>
                        <span className="muted small"> · {d.to_email}</span>
                      </span>
                    </label>
                    <div className="draft-actions">
                      <button className={`chip ${mode === "design" ? "active" : ""}`}
                        onClick={() => setView({ ...view, [d.id]: "design" })}>Design</button>
                      <button className={`chip ${mode === "text" ? "active" : ""}`}
                        onClick={() => setView({ ...view, [d.id]: "text" })}>Text</button>
                      <button className="btn-mini" onClick={() => {
                        setEditing(isEditing ? null : d.id);
                        setEditSubject(d.subject); setEditBody(d.body); setEditTo(d.to_email);
                      }}>{isEditing ? "Cancel" : "Edit"}</button>
                    </div>
                  </div>

                  <div className="draft-subject">
                    <span className="muted small">Subject:</span> {d.subject}
                    {d.edited && <span className="soon-tag" style={{ marginLeft: 6 }}>edited</span>}
                  </div>

                  {d.collection_reason && (
                    <div className="draft-reason">Why this lead: {d.collection_reason}</div>
                  )}
                  {d.spam_flags?.length > 0 && (
                    <div className="draft-flags">⚠ {d.spam_flags.join(" · ")}</div>
                  )}

                  {isEditing ? (
                    <div className="draft-edit">
                      <label className="build-label">Send to</label>
                      <input className="af-input" value={editTo} type="email"
                        onChange={(e) => setEditTo(e.target.value)} placeholder="recipient@example.com" />
                      <label className="build-label" style={{ marginTop: 6 }}>Subject</label>
                      <input className="af-input" value={editSubject}
                        onChange={(e) => setEditSubject(e.target.value)} placeholder="Subject" />
                      <label className="build-label" style={{ marginTop: 6 }}>Message</label>
                      <textarea className="af-input" rows={8} value={editBody}
                        onChange={(e) => setEditBody(e.target.value)} />
                      <button className="btn-mini primary" disabled={busy === d.id}
                        onClick={() => saveEdit(d.id)}>Save &amp; re-render</button>
                    </div>
                  ) : mode === "design" ? (
                    <iframe className="draft-preview" title={`Preview ${d.business_name}`}
                      sandbox="" srcDoc={d.preview_html || d.html} />
                  ) : (
                    <pre className="draft-text">{d.body}</pre>
                  )}
                </div>
              );
            })}
          </div>

          <div className="pending-actions">
            <button className="btn-mini primary" disabled={busy === "send"} onClick={sendApproved}>
              {busy === "send" ? "Sending…" : `Approve & send ${selected.size}`}
            </button>
            <button className="btn-mini danger" disabled={busy === "reject"} onClick={rejectSelected}>
              Discard {selected.size}
            </button>
          </div>
        </>
      )}
    </div>
  );
}
