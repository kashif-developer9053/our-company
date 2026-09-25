"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import * as api from "@/lib/api";
import type { WhatsAppLead } from "@/lib/api";

// WhatsApp outreach desk. The app WRITES the message and opens WhatsApp with it
// pre-typed — the CEO presses send themselves. Nothing is automated, because
// automated sending is what gets numbers permanently banned.
const STATUSES = [
  { key: "all", label: "All" },
  { key: "not_contacted", label: "Not contacted" },
  { key: "message_sent", label: "Message sent" },
  { key: "replied", label: "Replied" },
  { key: "interested", label: "Interested" },
  { key: "not_interested", label: "Not interested" },
] as const;

const STATUS_COLOR: Record<string, string> = {
  not_contacted: "#8a93a6",
  message_sent: "#4aa3ff",
  replied: "#f2c14e",
  interested: "#5bbf87",
  not_interested: "#ef5350",
  invalid_number: "#6b7383",
};

const DAILY_SAFE_LIMIT = 30;

export default function WhatsAppPanel() {
  const [leads, setLeads] = useState<WhatsAppLead[]>([]);
  const [counts, setCounts] = useState<Record<string, number>>({});
  // City and problem filters, plus their options, which come from the server
  // so they always reflect the leads that actually exist.
  const [cityFilter, setCityFilter] = useState("");
  const [issueFilter, setIssueFilter] = useState("");
  const [cities, setCities] = useState<api.WaFacet[]>([]);
  const [issues, setIssues] = useState<api.WaFacet[]>([]);
  const [filter, setFilter] = useState<string>("not_contacted");
  // Language per number: the same list mixes contacts who read English
  // comfortably with those who reply far better in Roman Urdu, so one global
  // setting was the wrong shape.
  const [rowLang, setRowLang] = useState<Record<string, string>>({});
  // Desktop app vs browser tab. Remembered, because whichever one works on
  // this machine is the one that works every time.
  // Held across renders so every later click can steer the SAME tab rather
  // than asking the browser for a new one.
  const waTab = useRef<Window | null>(null);
  const [waOpen, setWaOpen] = useState(false);
  // Desktop app is off by default: most people here work in WhatsApp Web.
  const [useDesktop, setUseDesktop] = useState(false);
  useEffect(() => {
    try {
      // v1 of this setting shipped defaulting to the desktop app, and that
      // choice is still sitting in browsers where it was never wanted — it
      // silently swallowed every click for anyone using WhatsApp Web. Drop the
      // old key so the browser default applies once, then respect the new one.
      localStorage.removeItem("wa_use_desktop");
      const v = localStorage.getItem("wa_mode_v2");
      if (v !== null) setUseDesktop(v === "desktop");
    } catch { /* private mode — fall back to the default */ }
  }, []);
  const toggleDesktop = (on: boolean) => {
    setUseDesktop(on);
    try { localStorage.setItem("wa_mode_v2", on ? "desktop" : "web"); } catch { /* ignore */ }
  };
  const [openId, setOpenId] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [link, setLink] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);

  const load = useCallback(async (f: string) => {
    try {
      const r = await api.getWhatsAppLeads(f, { city: cityFilter, issue: issueFilter });
      setLeads(r.leads); setCounts(r.counts);
      setCities(r.cities ?? []); setIssues(r.issues ?? []);
    } catch { /* backend down */ }
  }, [cityFilter, issueFilter]);
  useEffect(() => { load(filter); }, [filter, load]);

  // The indicator must not claim a link that no longer exists.
  useEffect(() => {
    const t = setInterval(() => {
      if (waOpen && (!waTab.current || waTab.current.closed)) setWaOpen(false);
    }, 3000);
    return () => clearInterval(t);
  }, [waOpen]);

  // Sent today — keeps the CEO under a volume that won't get the number banned.
  const sentToday = leads.filter((l) => {
    if (!l.sent_at) return false;
    return new Date(l.sent_at).toDateString() === new Date().toDateString();
  }).length;

  const prepare = async (l: WhatsAppLead, language?: string) => {
    // Default to the lead's own first (local) language.
    const useLang = language ?? rowLang[l.id]
      ?? l.languages?.[0]?.code ?? "english";
    setRowLang((m) => ({ ...m, [l.id]: useLang }));
    setBusy(l.id); setMsg(null); setOpenId(l.id); setDraft(""); setLink("");
    try {
      const r = await api.writeWhatsAppMessage(l.id, useLang);
      if (!r.ok) { setMsg(`⚠ ${r.error}`); return; }
      setDraft(r.message || ""); setLink(r.link || "");
    } catch (e) { setMsg(`⚠ ${(e as Error).message}`); }
    finally { setBusy(null); }
  };

  // Re-encode the link whenever the CEO edits the text before sending.
  // MUST stay on web.whatsapp.com. api.whatsapp.com is a landing page that
  // redirects here, so steering the linked tab at it navigated away from the
  // logged-in session and bounced back — which is why the link appeared to
  // fail and a fresh page loaded every time. Same origin as the tab we opened
  // means WhatsApp Web handles it internally and just switches chat.
  const linkFor = (l: WhatsAppLead) =>
    `https://web.whatsapp.com/send?phone=${l.number}` +
    `&text=${encodeURIComponent(draft)}&type=phone_number&app_absent=0`;

  // The desktop app is a single window that switches chats in place, so it
  // never stacks tabs. A browser CANNOT reuse a WhatsApp Web tab the user
  // opened themselves — same-origin rules mean our page has no handle on it —
  // so the desktop app is the only route that genuinely behaves as expected.
  // A browser can only steer a tab it opened. Clicking this once hands the
  // app a handle to WhatsApp Web; from then on every lead switches that same
  // tab instead of spawning a new one.
  const openWaTab = () => {
    const win = window.open("https://web.whatsapp.com/", "eldiancore_whatsapp");
    if (!win) {
      setMsg("⚠ Your browser blocked the tab — allow popups for this site, then try again.");
      return;
    }
    waTab.current = win;
    setWaOpen(true);
    win.focus();
    setMsg("WhatsApp Web linked. Leave that tab open and every message will reuse it.");
  };

  const desktopLink = (l: WhatsAppLead) =>
    `whatsapp://send?phone=${l.number}&text=${encodeURIComponent(draft)}`;

  const openWhatsApp = async (l: WhatsAppLead) => {
    if (useDesktop) {
      // A custom-scheme link cannot report whether the OS handled it, so if
      // the app is not installed the click appears to do nothing at all. Say
      // so explicitly, and point at the toggle rather than leaving the user
      // clicking a dead button.
      window.location.href = desktopLink(l);
      setMsg("Opening the WhatsApp app… Nothing happened? Untick “Use WhatsApp app” " +
             "to open in the browser instead.");
      return;
    }
    const url = draft ? linkFor(l) : link;

    // A page can only reuse a tab IT opened: window.open(url, name) looks up
    // the name among windows this origin created, so a WhatsApp tab opened by
    // hand is unreachable no matter what. The workable version is to hold our
    // own reference — open it once, then keep steering that same tab.
    //
    // waTab survives re-renders; the named target covers the case where the
    // reference is lost (a page refresh) but the tab is still open.
    const existing = waTab.current;
    if (existing && !existing.closed) {
      try {
        existing.location.href = url;   // same tab, straight to the next chat
        existing.focus();
        setMsg("Switched the open WhatsApp tab to this chat. Press send there.");
        return;
      } catch {
        // Cross-origin navigation was refused; fall through and re-open.
      }
    }

    const win = window.open(url, "eldiancore_whatsapp");
    if (!win) {
      setMsg("⚠ Your browser blocked the WhatsApp tab — allow popups for this site.");
      return;
    }
    waTab.current = win;
    setWaOpen(true);
    win.focus();
    setMsg("WhatsApp opened here. Keep this tab open — the next lead reuses it.");
  };

  const verifyNumbers = async () => {
    setBusy("verify"); setMsg(null);
    try {
      const r = await api.verifyWhatsAppNumbers({ limit: 500 });
      if (!r.ok) { setMsg(`⚠ ${r.error}`); return; }
      const c = r.counts || {};
      const credits = r.credits_remaining != null
        ? ` ${r.credits_remaining} credits left.` : "";
      setMsg(r.message ?? `Checked ${r.checked}: ${c.yes ?? 0} on WhatsApp, ` +
             `${(c.no ?? 0) + (c.skipped_landline ?? 0)} not, ${c.unknown ?? 0} unclear.${credits}`);
      await load(filter);
    } catch (e) { setMsg(`⚠ ${(e as Error).message}`); }
    finally { setBusy(null); }
  };

  const setStatus = async (l: WhatsAppLead, status: string) => {
    setBusy(l.id);
    try {
      await api.updateWhatsAppLead(l.id, { status, message: draft || undefined });
      await load(filter);
    } finally { setBusy(null); }
  };

  const saveRemarks = async (l: WhatsAppLead, remarks: string) => {
    setBusy(l.id);
    try { await api.updateWhatsAppLead(l.id, { remarks }); await load(filter); }
    finally { setBusy(null); }
  };

  return (
    <div className="settings-card">
      <div className="settings-card-head">
        <h2>WhatsApp outreach</h2>
        <span className={`soon-tag ${sentToday >= DAILY_SAFE_LIMIT ? "" : "set"}`}>
          {sentToday}/{DAILY_SAFE_LIMIT} today
        </span>
      </div>
      <p className="pending-sub" style={{ color: "#8a93a6" }}>
        Only leads with a usable mobile number appear here. The message is written for you from that
        lead&apos;s site audit — you review it and press send in WhatsApp yourself.
        <strong> Nothing is sent automatically</strong>, which is what keeps your number safe.
      </p>

      {sentToday >= DAILY_SAFE_LIMIT && (
        <div className="draft-flags">
          ⚠ You&apos;ve opened {sentToday} chats today. Stop here — going much beyond {DAILY_SAFE_LIMIT}/day
          risks your number being flagged.
        </div>
      )}

      <div className="hunt-form" style={{ marginBottom: 10 }}>
        {STATUSES.map((s) => (
          <button key={s.key} className={`chip ${filter === s.key ? "active" : ""}`}
            onClick={() => setFilter(s.key)}>
            {s.label}{counts[s.key] ? ` (${counts[s.key]})` : s.key === "all" && counts.total ? ` (${counts.total})` : ""}
          </button>
        ))}
        <span style={{ marginLeft: "auto", display: "flex", gap: 6, alignItems: "center" }}>
          <button className="btn-mini" type="button" onClick={openWaTab}
            title="Open WhatsApp Web once from here — every later click reuses this tab">
            {waOpen ? "✓ WhatsApp tab linked" : "Link WhatsApp tab"}
          </button>
          <label className="wa-modetoggle" title="The desktop app switches chats in one window; a browser opens tabs">
            <input type="checkbox" checked={useDesktop}
              onChange={(e) => toggleDesktop(e.target.checked)} />
            <span>Use WhatsApp app</span>
          </label>
        </span>
      </div>

      <div className="wa-filters">
        <select className="af-input" value={cityFilter}
          onChange={(e) => setCityFilter(e.target.value)}>
          <option value="">All cities</option>
          {cities.map((c) => (
            <option key={c.value} value={c.value}>{c.value} ({c.count})</option>
          ))}
        </select>
        <select className="af-input" value={issueFilter}
          onChange={(e) => setIssueFilter(e.target.value)}>
          <option value="">Any problem</option>
          {issues.map((i) => (
            <option key={i.value} value={i.value}>{i.value} ({i.count})</option>
          ))}
        </select>
        {(cityFilter || issueFilter) && (
          <button className="btn-mini" type="button"
            onClick={() => { setCityFilter(""); setIssueFilter(""); }}>
            Clear filters
          </button>
        )}
        <button className="btn-mini" type="button" disabled={busy === "verify"}
          title="Check which numbers actually have WhatsApp. Landlines are settled for free."
          onClick={verifyNumbers}>
          {busy === "verify" ? "Checking…" : "Verify numbers"}
        </button>
        <span className="muted small" style={{ marginLeft: "auto" }}>
          {leads.length} shown · newest first
        </span>
      </div>

      {msg && <div className="pending-msg">{msg}</div>}

      {leads.length === 0 ? (
        <p className="muted small">No WhatsApp-reachable leads in this view.</p>
      ) : (
        <div className="table-wrap">
          <table className="leads-table">
            <thead>
              <tr><th>Business</th><th>Problem</th><th>Number</th><th>WhatsApp</th><th>Status</th><th>Remarks</th><th></th></tr>
            </thead>
            <tbody>
              {leads.map((l) => (
                <tr key={l.id} className={openId === l.id ? "" : undefined}>
                  <td>
                    <span className="lead-name">{l.business_name}</span>
                    <span className="muted small"> · {l.city}</span>
                    {/* Where the number came from. Someone we messaged asked
                        how we got his details and there was no way to answer
                        from this screen — anyone contacting a stranger should
                        be able to say, before they press send. */}
                    {l.source && (
                      <div className="wa-source">
                        from {l.source}
                        {l.collected_at ? ` · ${l.collected_at}` : ""}
                        {l.source_url && (
                          <> · <a href={l.source_url} target="_blank" rel="noreferrer">source</a></>
                        )}
                      </div>
                    )}
                    {l.collection_reason && (
                      <div className="draft-reason" style={{ marginTop: 4 }}>{l.collection_reason.slice(0, 90)}</div>
                    )}
                    {openId === l.id && (
                      <div className="draft-edit" style={{ marginTop: 8 }}>
                        <textarea className="af-input" rows={4} value={draft}
                          onChange={(e) => setDraft(e.target.value)}
                          placeholder={busy === l.id ? "Writing…" : "Message will appear here"} />
                        <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                          <button className="btn-mini primary" disabled={!draft}
                            onClick={() => openWhatsApp(l)}>
                            {useDesktop ? "Open in WhatsApp app →" : "Open WhatsApp Web →"}
                          </button>
                          <button className="btn-mini" disabled={busy === l.id}
                            onClick={() => prepare(l)}>Rewrite</button>
                          <button className="btn-mini" onClick={() => setStatus(l, "message_sent")}>
                            ✓ Mark sent
                          </button>
                        </div>
                      </div>
                    )}
                  </td>
                  <td>
                    {l.issue
                      ? <span className="wa-issue">{l.issue}</span>
                      : <span className="muted small">—</span>}
                  </td>
                  <td className="muted">+{l.number}</td>
                  <td>
                    {l.has_whatsapp === "yes" ? <span className="wa-yes">✓ on WhatsApp</span>
                      : l.has_whatsapp === "no" ? <span className="wa-no">✗ no WhatsApp</span>
                      : l.has_whatsapp === "unknown" ? <span className="wa-unknown">? unverified</span>
                      : <span className="muted small">not checked</span>}
                  </td>
                  <td>
                    <select className="af-input" style={{ minWidth: 130 }} value={l.status}
                      onChange={(e) => setStatus(l, e.target.value)}>
                      {STATUSES.filter((s) => s.key !== "all").map((s) => (
                        <option key={s.key} value={s.key}>{s.label}</option>
                      ))}
                    </select>
                    <div style={{ height: 3, marginTop: 4, borderRadius: 2,
                      background: STATUS_COLOR[l.status] || "#8a93a6" }} />
                  </td>
                  <td>
                    <input className="af-input" defaultValue={l.remarks} placeholder="e.g. asked for pricing"
                      onBlur={(e) => e.target.value !== l.remarks && saveRemarks(l, e.target.value)} />
                  </td>
                  <td className="row-actions">
                    {/* Languages come from the lead's own country/city, so a
                        Jubail clinic offers Arabic and a Mexican one Spanish,
                        rather than Roman Urdu for everybody. The first is the
                        local language; English is always available. */}
                    <div className="wa-langbtns">
                      {(l.languages?.length ? l.languages
                        : [{ code: "english", label: "English" }]).map((lg, idx) => (
                        <button key={lg.code}
                          className={`btn-mini${idx === 0 ? " primary" : ""}`}
                          disabled={busy === l.id}
                          title={`Write this message in ${lg.label}`}
                          onClick={() => prepare(l, lg.code)}>
                          {busy === l.id && rowLang[l.id] === lg.code ? "…" : lg.label}
                        </button>
                      ))}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
