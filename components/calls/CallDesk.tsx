"use client";

import { useCallback, useEffect, useState } from "react";
import * as api from "@/lib/api";

// The cold caller's whole application.
//
// He is not technical and he is mid-call, so the screen is built around one
// decision at a time: here is the next business, here is what to say, here is
// what happened. Everything he needs during a call is on one card — looking
// something up elsewhere while a stranger waits on the line is how calls die.
export default function CallDesk({ callerName }: { callerName: string }) {
  const [leads, setLeads] = useState<api.CallLead[]>([]);
  const [stats, setStats] = useState<api.CallStats | null>(null);
  const [statuses, setStatuses] = useState<api.CallStatusOption[]>([]);
  const [openId, setOpenId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [showDone, setShowDone] = useState(false);
  const [draftRemarks, setDraftRemarks] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    try {
      const r = await api.getCallQueue(showDone ? "all" : "open");
      if (!r.ok) { setErr(r.error || "Could not load your list."); return; }
      setLeads(r.leads ?? []);
      setStats(r.stats ?? null);
      setStatuses(r.statuses ?? []);
      setErr(null);
    } catch (e) { setErr((e as Error).message); }
  }, [showDone]);

  useEffect(() => { load(); }, [load]);

  const save = async (id: string, patch: { status?: string; remarks?: string; logged_call?: boolean }) => {
    setBusy(true);
    try {
      const r = await api.updateCallLead({ lead_id: id, ...patch });
      if (!r.ok) setErr(r.error || "Could not save.");
      else { setErr(null); await load(); }
    } catch (e) { setErr((e as Error).message); }
    finally { setBusy(false); }
  };

  // Opening WhatsApp counts as an attempt, so the day's number is real even
  // when nobody picks up. He can still change the outcome afterwards.
  const call = (l: api.CallLead) => {
    window.open(l.wa_call_link, "_blank", "noopener");
    save(l.id, { logged_call: true });
  };

  const open = leads.find((l) => l.id === openId) || null;

  return (
    <div className="call-desk">
      <header className="call-head">
        <div>
          <h1>Call list</h1>
          <p className="muted small">Salam {callerName || "ji"} — aaj ke calls</p>
        </div>
        <label className="call-toggle">
          <input type="checkbox" checked={showDone} onChange={(e) => setShowDone(e.target.checked)} />
          Finished bhi dikhayein
        </label>
      </header>

      {stats && (
        <div className="call-stats">
          <Stat big label="Aaj calls kiye" value={stats.calls_today} tone="neutral" />
          <Stat big label="Baqi hain" value={stats.open} tone="neutral" />
          <Stat label="Interested" value={stats.by_status.interested ?? 0} tone="good" />
          <Stat label="Meeting fixed" value={stats.by_status.meeting_fixed ?? 0} tone="good" />
          <Stat label="Call back" value={stats.by_status.call_back ?? 0} tone="warn" />
          <Stat label="No answer" value={stats.by_status.no_answer ?? 0} tone="warn" />
          <Stat label="Not interested" value={stats.by_status.not_interested ?? 0} tone="bad" />
        </div>
      )}

      {err && <div className="team-error">⚠ {err}</div>}

      {leads.length === 0 && !err && (
        <div className="call-empty">
          <p>Abhi list khali hai.</p>
          <p className="muted small">Jab nayi leads add hongi, yahan aa jayengi.</p>
        </div>
      )}

      <div className="call-list">
        {leads.map((l) => {
          const isOpen = openId === l.id;
          return (
            <div key={l.id} className={`call-card ${isOpen ? "open" : ""}`}>
              <button className="call-card-head" onClick={() => setOpenId(isOpen ? null : l.id)}>
                <div className="call-card-main">
                  <span className="call-biz">{l.business_name}</span>
                  <span className="muted small">
                    {[l.niche, l.city].filter(Boolean).join(" · ")}
                  </span>
                </div>
                <div className="call-card-side">
                  <StatusPill status={l.status} statuses={statuses} />
                  {l.calls_made > 0 && (
                    <span className="muted small">{l.calls_made}× call</span>
                  )}
                  <span className="call-chevron">{isOpen ? "▴" : "▾"}</span>
                </div>
              </button>

              {isOpen && (
                <div className="call-body">
                  {/* 1. WHO — everything he may be asked about the business */}
                  <section className="call-sec">
                    <h3>Business</h3>
                    <dl className="call-facts">
                      <dt>Naam</dt><dd>{l.business_name}</dd>
                      <dt>Kaam</dt><dd>{l.niche || "—"}</dd>
                      <dt>Shehar</dt><dd>{l.city || "—"}</dd>
                      <dt>Number</dt><dd>+{l.number}</dd>
                      {l.website && (
                        <>
                          <dt>Website</dt>
                          <dd>
                            <a href={l.website.startsWith("http") ? l.website : `https://${l.website}`}
                               target="_blank" rel="noopener noreferrer" className="site-link">
                              kholein ↗
                            </a>
                          </dd>
                        </>
                      )}
                      {!!l.reviews_count && (
                        <>
                          <dt>Google</dt>
                          <dd>{l.rating ? `${l.rating}★ · ` : ""}{l.reviews_count} reviews</dd>
                        </>
                      )}
                      <dt>Number kahan se</dt>
                      <dd>{l.source || "Google Maps"} {l.collected_at && `· ${l.collected_at}`}</dd>
                    </dl>
                  </section>

                  {/* 2. WHY — the one thing he must be able to answer */}
                  <section className="call-sec why">
                    <h3>Call kyun kar rahe hain</h3>
                    <p>{l.why || "Is business ko hamari service ki zaroorat ho sakti hai."}</p>
                    {l.message_status && (
                      <p className="call-note">
                        ⚠ Is lead ko pehle WhatsApp message bheja ja chuka hai
                        {l.message_sent_at ? ` (${l.message_sent_at.slice(0, 10)})` : ""}.
                        Shuru mein ye zaroor bata dein.
                      </p>
                    )}
                  </section>

                  {/* 3. WHAT TO SAY */}
                  <section className="call-sec script">
                    <h3>Kya kehna hai</h3>
                    {l.script.steps.map((s) => (
                      <div key={s.n} className="call-step">
                        <span className="call-step-n">{s.n}</span>
                        <div>
                          <div className="call-step-title">{s.title}</div>
                          <p className="call-say">{s.say}</p>
                          {s.note && <p className="call-step-note">{s.note}</p>}
                        </div>
                      </div>
                    ))}
                    {l.script.extra_service && (
                      <p className="call-say muted">{l.script.extra_service}</p>
                    )}
                    <div className="call-closes">
                      <div><strong>Agar haan kahein:</strong><p className="call-say">{l.script.close_interested}</p></div>
                      <div><strong>Agar mana karein:</strong><p className="call-say">{l.script.close_not_interested}</p></div>
                    </div>
                  </section>

                  {/* 4. OBJECTIONS — collapsed, opened when it happens */}
                  <details className="call-sec">
                    <summary><h3 style={{ display: "inline" }}>Agar ye kahein to…</h3></summary>
                    {l.script.objections.map((o, i) => (
                      <div key={i} className="call-obj">
                        <div className="call-obj-q">{o.q}</div>
                        <div className="call-say">{o.a}</div>
                      </div>
                    ))}
                  </details>

                  <details className="call-sec">
                    <summary><h3 style={{ display: "inline" }}>Yaad rakhein</h3></summary>
                    <ul className="call-rules">
                      {l.script.rules.map((r, i) => <li key={i}>{r}</li>)}
                    </ul>
                  </details>

                  {/* 5. THE CALL + what happened */}
                  <section className="call-sec action">
                    <button className="call-btn-main" disabled={busy || !l.number}
                            onClick={() => call(l)}>
                      📞 WhatsApp par call karein
                    </button>

                    <div className="call-status-grid">
                      {statuses.map((s) => (
                        <button key={s.key} disabled={busy}
                          className={`call-status-btn ${s.tone} ${l.status === s.key ? "on" : ""}`}
                          onClick={() => save(l.id, { status: s.key })}>
                          {s.label}
                        </button>
                      ))}
                    </div>

                    <label className="build-label">Remarks (jo baat hui)</label>
                    <textarea className="af-input" rows={3}
                      placeholder="Misaal: kal 3 baje call karne ko kaha hai"
                      value={draftRemarks[l.id] ?? l.remarks}
                      onChange={(e) => setDraftRemarks({ ...draftRemarks, [l.id]: e.target.value })} />
                    <button className="btn-mini primary" disabled={busy}
                      onClick={() => save(l.id, { remarks: draftRemarks[l.id] ?? l.remarks })}>
                      {busy ? "Save ho raha…" : "Remarks save karein"}
                    </button>

                    {l.history.length > 0 && (
                      <details className="call-hist">
                        <summary>Pehle kya hua ({l.history.length})</summary>
                        {l.history.slice().reverse().map((h, i) => (
                          <div key={i} className="call-hist-row">
                            <span className="muted small">{h.at}</span>
                            {h.status && <span> · {h.status}</span>}
                            {h.called && <span> · call kiya</span>}
                            {h.remarks && <div className="muted small">{h.remarks}</div>}
                          </div>
                        ))}
                      </details>
                    )}
                  </section>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function Stat({ label, value, tone, big }: { label: string; value: number; tone: string; big?: boolean }) {
  return (
    <div className={`call-stat ${tone} ${big ? "big" : ""}`}>
      <span className="call-stat-v">{value}</span>
      <span className="call-stat-l">{label}</span>
    </div>
  );
}

function StatusPill({ status, statuses }: { status: string; statuses: api.CallStatusOption[] }) {
  const s = statuses.find((x) => x.key === status);
  if (!s) return null;
  return <span className={`call-pill ${s.tone}`}>{s.label}</span>;
}
