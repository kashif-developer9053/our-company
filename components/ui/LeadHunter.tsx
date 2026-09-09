"use client";

import { useState } from "react";
import * as api from "@/lib/api";
import type { NextOption } from "@/lib/api";

interface Result {
  found: number; target: number; complete: boolean; rounds: number; examined: number;
  elapsed_seconds: number; added: number; message: string; next_options: NextOption[];
  rejected: { no_contact: number; good_site: number; guessed_email_only: number };
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

  const run = async (opts?: { niche?: string; city?: string; country?: string; continueNiche?: boolean }) => {
    const n = (opts?.niche ?? niche).trim();
    if (!n || busy) return;
    setBusy(true); setErr(null); setResult(null);
    try {
      const r = await api.harvestLeads({
        niche: n,
        city: opts?.city ?? city.trim(),
        country: opts?.country ?? country.trim(),
        target,
        continue_niche: opts?.continueNiche ?? false,
      });
      if (!r.ok) { setErr(r.error || "Hunt failed."); return; }
      setResult({
        found: r.found ?? 0, target: r.target ?? target, complete: !!r.complete,
        rounds: r.rounds ?? 0, examined: r.examined ?? 0, elapsed_seconds: r.elapsed_seconds ?? 0,
        added: r.added ?? 0, message: r.message ?? "", next_options: r.next_options ?? [],
        rejected: r.rejected ?? { no_contact: 0, good_site: 0, guessed_email_only: 0 },
        alreadyHeld: r.already_held ?? 0,
        nicheTotal: r.niche_total ?? (r.added ?? 0),
      });
      onDone?.();
    } catch (e) { setErr((e as Error).message); }
    finally { setBusy(false); }
  };

  const choose = (action: string) => {
    if (action === "stop") { setResult(null); return; }
    // Keep mining the same niche, counting toward the same target.
    if (action === "more_same_niche") { run({ continueNiche: true }); return; }
    if (action === "widen_location") { setCity(""); run({ city: "", continueNiche: true }); return; }
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

      <div className="hunt-form">
        <input className="af-input" placeholder="Niche (e.g. dental clinic)" value={niche}
          onChange={(e) => setNiche(e.target.value)} disabled={busy} />
        <input className="af-input" placeholder="City (optional)" value={city}
          onChange={(e) => setCity(e.target.value)} disabled={busy} />
        <input className="af-input" placeholder="Country (optional)" value={country}
          onChange={(e) => setCountry(e.target.value)} disabled={busy} />
        <input className="af-input" type="number" min={1} max={200} style={{ width: 90 }} value={target}
          onChange={(e) => setTarget(Number(e.target.value))} disabled={busy} title="How many qualified leads" />
        <button className="btn-mini primary" onClick={() => run()} disabled={busy || !niche.trim()}>
          {busy ? "Hunting…" : `Find ${target} leads`}
        </button>
      </div>

      {busy && (
        <div className="hunt-busy">
          <span className="spinner" /> Agent 1 is searching, checking contacts and auditing websites.
          This can take several minutes for large targets — watch its status in the office.
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
          <div className="hunt-stats">
            <span>{result.examined} businesses examined</span>
            <span>{result.rounds} search rounds</span>
            <span>{result.rejected.no_contact} rejected — no verified contact</span>
            <span>{result.rejected.good_site} rejected — site already fine</span>
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
