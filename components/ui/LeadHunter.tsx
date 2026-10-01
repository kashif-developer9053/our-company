"use client";

import { useEffect, useState } from "react";
import * as api from "@/lib/api";
import type { NextOption } from "@/lib/api";

interface Result {
  found: number; target: number; complete: boolean; rounds: number; examined: number;
  elapsed_seconds: number; added: number; message: string; next_options: NextOption[];
  rejected: { no_contact?: number; good_site?: number; guessed_email_only?: number;
              too_big_for_sweep?: number; chain_branches?: number;
              wrong_contact_type?: number };
  // Purpose and area hunts walk several business types; these say which ones
  // actually produced something, so the next hunt can be aimed better.
  nichesSearched: string[];
  // Running totals for the niche, so "find more" reads as progress toward the
  // target rather than each hunt looking like it only found three or four.
  alreadyHeld: number; nicheTotal: number;
}

// Agent 1's lead hunt: keeps searching until it has `target` leads that BOTH
// have a verified (never guessed) contact AND evidenced website problems. When
// it finishes it asks the CEO what to do next.
export default function LeadHunter({ onDone }: { onDone?: () => void }) {
  const [niche, setNiche] = useState("");
  const [city, setCity] = useState("");
  const [country, setCountry] = useState("");
  const [target, setTarget] = useState(50);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [result, setResult] = useState<Result | null>(null);
  // The niche the last hunt actually ran on, so "find more" continues that
  // one even if the input box has since been edited.
  const [lastNiche, setLastNiche] = useState("");
  const [live, setLive] = useState("");
  // What we are selling. Website work is judged by the site audit; everything
  // else is judged by industry and size, because no scan reveals that a
  // business is tracking stock on paper.
  const [service, setService] = useState("website");
  // How the hunt picks who to search for. "niche" is the original behaviour;
  // the other two exist so finding leads does not depend on the CEO thinking
  // of the right business type every morning.
  const [mode, setMode] = useState<"niche" | "purpose" | "area">("niche");
  // Which contact route this campaign needs. Collecting phone-only businesses
  // for an email campaign wastes the hunt, and collecting landlines for a
  // WhatsApp campaign fills the desk with numbers nobody can message.
  const [contact, setContact] = useState<"both" | "email" | "whatsapp">("both");
  const [services, setServices] = useState<api.ServiceTarget[]>([]);
  useEffect(() => {
    api.getServices().then((r) => setServices(r.services ?? [])).catch(() => {});
  }, []);
  const chosen = services.find((s) => s.key === service);

  // Agent 1 publishes its progress to the status board while hunting; poll it
  // so a multi-round hunt shows what it is doing instead of a bare spinner.
  useEffect(() => {
    if (!busy) { setLive(""); return; }
    let on = true;
    const t = setInterval(async () => {
      try {
        const agents = await api.getAgents();
        const a1 = agents.find((a) => a.id === "agent1");
        if (on && a1?.task) setLive(a1.task);
      } catch { /* status board unavailable — keep the spinner */ }
    }, 3000);
    return () => { on = false; clearInterval(t); };
  }, [busy]);

  const run = async (opts?: { niche?: string; city?: string; country?: string; continueNiche?: boolean }) => {
    const n = (opts?.niche ?? niche).trim();
    // Only a niche hunt needs a niche. The other two modes need a place,
    // because they choose the business types themselves.
    if (busy) return;
    if (mode === "niche" && !n) return;
    if (mode !== "niche" && !city.trim() && !country.trim()) {
      setErr("Tell me where to look — a city or a country.");
      return;
    }
    // Keep the previous result on screen while hunting. Clearing it here
    // removed the "find more in this niche" button the moment it was
    // pressed, and an empty hunt then left nothing to click at all.
    setBusy(true); setErr(null);
    try {
      const r = await api.harvestLeads({
        niche: n,
        city: opts?.city ?? city.trim(),
        country: opts?.country ?? country.trim(),
        target,
        continue_niche: opts?.continueNiche ?? false,
        service,
        mode,
        contact,
      });
      if (!r.ok) { setErr(r.error || "Hunt failed."); return; }
      setLastNiche(n);

      // The hunt now runs in the background: nginx closes a proxied request
      // after 600s and a hunt can run far longer, which was the 504. Poll
      // until it finishes instead of holding the connection open.
      if (r.run_id) {
        await pollHunt(r.run_id, n);
        return;
      }
      setResult({
        found: r.found ?? 0, target: r.target ?? target, complete: !!r.complete,
        rounds: r.rounds ?? 0, examined: r.examined ?? 0, elapsed_seconds: r.elapsed_seconds ?? 0,
        added: r.added ?? 0, message: r.message ?? "", next_options: r.next_options ?? [],
        rejected: r.rejected ?? {},
        alreadyHeld: r.already_held ?? 0,
        nicheTotal: r.niche_total ?? (r.added ?? 0),
        nichesSearched: [],
      });
      onDone?.();
    } catch (e) { setErr((e as Error).message); }
    finally { setBusy(false); }
  };

  const pollHunt = async (runId: string, n: string) => {
    for (;;) {
      await new Promise((r) => setTimeout(r, 4000));
      let st;
      try { st = await api.getHuntStatus(runId); }
      catch { continue; }                     // a blip should not kill the hunt view
      if (!st.ok) { setErr(st.error || "Lost track of that hunt."); return; }
      if (st.message) setLive(st.message);
      if (st.status === "running") continue;
      if (st.status === "error") { setErr(st.error || st.message || "Hunt failed."); return; }

      setResult({
        found: st.found ?? 0, target: st.target ?? target, complete: !!st.complete,
        rounds: st.rounds ?? 0, examined: st.examined ?? 0,
        elapsed_seconds: st.elapsed_seconds ?? 0, added: st.added ?? 0,
        message: st.message ?? "", next_options: st.next_options ?? [],
        rejected: st.rejected ?? {},
        alreadyHeld: st.already_held ?? 0,
        nicheTotal: st.niche_total ?? (st.added ?? 0),
        nichesSearched: st.niches_searched ?? [],
      });
      onDone?.();
      return;
    }
  };

  const choose = (action: string) => {
    if (action === "stop") { setResult(null); return; }
    // Keep mining the same niche, counting toward the same target.
    if (action === "more_same_niche") { run({ niche: lastNiche || niche, continueNiche: true }); return; }
    if (action === "widen_location") { setCity(""); run({ niche: lastNiche || niche, city: "", continueNiche: true }); return; }
    if (action === "different_niche") { setResult(null); setNiche(""); return; }
  };

  return (
    <div className="settings-card">
      <div className="settings-card-head">
        <h2>Agent 1 · Lead hunt</h2>
      </div>
      <p className="pending-sub" style={{ color: "#8a93a6" }}>
        Agent 1 keeps searching until it has the number of leads you ask for. A lead only counts if it has a
        <strong> real contact we actually found</strong> (published email or listed phone — never a guessed
        address) <strong>and</strong> a website with real problems we can fix.
      </p>

      <div className="hunt-service">
        <label className="build-label">How should Agent 1 choose who to search for?</label>
        <div className="hunt-modes">
          {([
            { k: "niche", t: "I know the business type",
              d: "You name it — dentists, furniture makers. Exact control." },
            { k: "purpose", t: "I know what I'm selling",
              d: "Name only the service. Agent 1 walks the business types that run on it." },
            { k: "area", t: "Just find me small businesses",
              d: "Name only a place. Agent 1 asks what is there — every trade, mixed — and works out what each one needs." },
          ] as const).map((m) => (
            <button key={m.k} type="button" disabled={busy}
              className={`hunt-mode ${mode === m.k ? "on" : ""}`}
              onClick={() => setMode(m.k)}>
              <strong>{m.t}</strong>
              <span>{m.d}</span>
            </button>
          ))}
        </div>

        {mode !== "area" && (
          <>
            <label className="build-label">What contact do you need?</label>
        <div className="hunt-contact">
          {([
            { k: "both", t: "Either", d: "Email or phone — collect whatever they publish." },
            { k: "email", t: "Email only", d: "Skip businesses with no address. For mail campaigns." },
            { k: "whatsapp", t: "WhatsApp only", d: "Mobiles only. Landlines are skipped, not collected." },
          ] as const).map((c) => (
            <button key={c.k} type="button" disabled={busy}
              className={`hunt-mode ${contact === c.k ? "on" : ""}`}
              onClick={() => setContact(c.k)}>
              <strong>{c.t}</strong>
              <span>{c.d}</span>
            </button>
          ))}
        </div>

        <label className="build-label">What are you selling?</label>
            <select className="af-input" value={service} disabled={busy}
              onChange={(e) => setService(e.target.value)}>
              {services.map((s) => (
                <option key={s.key} value={s.key}>{s.label}</option>
              ))}
            </select>
          </>
        )}
        {mode === "area" && (
          <p className="hunt-hint">
            No niche and no service: Agent 1 searches the place itself — main bazar,
            commercial area, industrial estate — and takes back whatever mix of trades
            is there, working out what each one needs. A website for the shop with none,
            stock tracking for the manufacturer. Chains, branches and anything too big
            are skipped, so what comes back is owner-run businesses.
          </p>
        )}
        {mode === "purpose" && chosen && chosen.niches.length > 0 && (
          <p className="hunt-hint">
            Agent 1 will search these itself, in order, until it has enough:{" "}
            <strong>{chosen.niches.slice(0, 5).join(", ")}</strong>
            {chosen.niches.length > 5 && ` and ${chosen.niches.length - 5} more`}.
          </p>
        )}
        {mode === "niche" && chosen && chosen.signal !== "site_defect" && (
          <p className="hunt-hint">
            Looks for businesses where <strong>{chosen.pain}</strong> — their website
            is not the test, so a company with a good site still counts. Big chains
            are skipped: they already run this software.
            {chosen.niches.length > 0 && (
              <>
                <br />Try a niche like:{" "}
                {chosen.niches.slice(0, 6).map((n) => (
                  <button key={n} type="button" className="hunt-nichechip"
                    onClick={() => setNiche(n)}>{n}</button>
                ))}
              </>
            )}
          </p>
        )}
      </div>

      <div className="hunt-form">
        {mode === "niche" && (
          <input className="af-input" placeholder="Niche (e.g. dental clinic)" value={niche}
            onChange={(e) => setNiche(e.target.value)} disabled={busy} />
        )}
        <input className="af-input"
          placeholder={mode === "niche" ? "City (optional)" : "City (e.g. Gujranwala)"}
          value={city} onChange={(e) => setCity(e.target.value)} disabled={busy} />
        <input className="af-input"
          placeholder={mode === "niche" ? "Country (optional)" : "Country"}
          value={country} onChange={(e) => setCountry(e.target.value)} disabled={busy} />
        <input className="af-input" type="number" min={1} max={200} style={{ width: 90 }} value={target}
          onChange={(e) => setTarget(Number(e.target.value))} disabled={busy} title="How many qualified leads" />
        <button className="btn-mini primary" onClick={() => run()}
          disabled={busy || (mode === "niche" ? !niche.trim() : !city.trim() && !country.trim())}>
          {busy ? "Hunting…" : `Find ${target} leads`}
        </button>
      </div>

      {busy && (
        <div className="hunt-busy">
          <span className="spinner" /> Agent 1 is searching, checking contacts and auditing websites.
          This can take several minutes for large targets.
          {live && <div className="hunt-live">{live}</div>}
        </div>
      )}

      {err && <div className="team-error" style={{ marginTop: 10 }}>⚠ {err}</div>}

      {result && (
        <div className="hunt-result">
          <div className={`hunt-headline ${result.complete ? "ok" : "partial"}`}>
            {result.complete ? "✅" : "⚠"} Found {result.found} qualified leads this round
            {result.alreadyHeld > 0 && (
              <span className="hunt-running"> · {result.nicheTotal} total for this niche</span>
            )}
          </div>
          <p className="muted small">{result.message}</p>
          {result.nichesSearched.length > 0 && (
            <p className="hunt-hint">
              Found leads in:{" "}
              {result.nichesSearched.map((n) => (
                <button key={n} type="button" className="hunt-nichechip"
                  title="Hunt this business type on its own"
                  onClick={() => { setMode("niche"); setNiche(n); }}>{n}</button>
              ))}
            </p>
          )}
          <div className="hunt-stats">
            <span>{result.examined} businesses examined</span>
            <span>{result.rounds} search rounds</span>
            <span>{result.rejected.no_contact ?? 0} rejected — no verified contact</span>
            <span>{result.rejected.good_site ?? 0} rejected — site already fine</span>
            {!!result.rejected.too_big_for_sweep && (
              <span>{result.rejected.too_big_for_sweep} skipped — too big or too new</span>
            )}
            {!!result.rejected.wrong_contact_type && (
              <span>{result.rejected.wrong_contact_type} skipped — not the contact type you asked for</span>
            )}
            {!!result.rejected.chain_branches && (
              <span>{result.rejected.chain_branches} skipped — branches of chains</span>
            )}
            <span>{Math.round(result.elapsed_seconds / 60)} min</span>
          </div>
          {result.added > 0 && (
            <div className="pending-msg" style={{ marginTop: 10 }}>
              {result.added} leads are waiting for your approval below — nothing is in the CRM yet.
            </div>
          )}

          <div className="hunt-next">
            <div className="build-label">What should Agent 1 do next?</div>
            {result.next_options.map((o) => (
              <button key={o.action}
                className={`hunt-option${o.primary ? " primary-opt" : ""}`}
                onClick={() => choose(o.action)} disabled={busy}>
                <span className="hunt-option-label">{o.label}</span>
                <span className="hunt-option-hint">{o.hint}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
