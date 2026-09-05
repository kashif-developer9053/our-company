"use client";

import { useCallback, useEffect, useState } from "react";
import * as api from "@/lib/api";
import type { SettingKey } from "@/lib/api";
import { useAuth } from "@/lib/auth-context";
import { ProvidersSection, CompanySection, UsageSection } from "@/components/settings/AiSettings";

export default function SettingsPage() {
  const { user } = useAuth();
  const [keys, setKeys] = useState<SettingKey[]>([]);
  const [cap, setCap] = useState(25);
  const [encSet, setEncSet] = useState(true);
  const [inputs, setInputs] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, { ok: boolean; message: string }>>({});
  const [err, setErr] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const s = await api.getSettings();
      setKeys(s.keys); setCap(s.config.daily_send_cap); setEncSet(s.encryption_secret_set); setErr(null);
    } catch (e) { setErr((e as Error).message); }
  }, []);
  useEffect(() => { if (user?.role === "admin") load(); }, [load, user]);

  if (user?.role !== "admin") {
    return <div className="page-body"><div className="backend-warn">Admins only.</div></div>;
  }

  const byName = (n: string) => keys.find((k) => k.key_name === n);

  const save = async (keyName: string) => {
    const val = (inputs[keyName] || "").trim();
    if (!val) return;
    setBusy(keyName);
    try { await api.saveSetting(keyName, val); setInputs({ ...inputs, [keyName]: "" }); await load(); }
    catch (e) { alert((e as Error).message); } finally { setBusy(null); }
  };
  const remove = async (keyName: string) => {
    if (!confirm(`Remove ${keyName}?`)) return;
    setBusy(keyName);
    try { await api.deleteSetting(keyName); await load(); } finally { setBusy(null); }
  };
  const runTest = async (id: string, fn: () => Promise<{ ok: boolean; message: string }>) => {
    setBusy(id);
    try { setResults({ ...results, [id]: await fn() }); } finally { setBusy(null); }
  };
  const sameAsSmtp = async () => {
    setBusy("same");
    try { await api.imapSameAsSmtp(); await load(); } catch (e) { alert((e as Error).message); } finally { setBusy(null); }
  };
  const saveCap = async () => {
    setBusy("cap");
    try { await api.saveConfig(cap); await load(); } finally { setBusy(null); }
  };

  const claude = byName("claude_api_key");

  return (
    <div className="page-body">
      <div className="page-head">
        <div><h1>Settings</h1><p className="page-sub">Secrets are encrypted server-side; only masked previews are shown.</p></div>
      </div>
      {err && <div className="backend-warn">⚠ {err}</div>}
      {!encSet && <div className="team-error" style={{ maxWidth: 720 }}>ENCRYPTION_SECRET is not set on the server — keys use an insecure dev fallback. Set it for production.</div>}

      {/* Claude */}
      {claude && (
        <div className="settings-card">
          <div className="settings-card-head"><h2>{claude.label}</h2><span className={`soon-tag ${claude.is_set ? "set" : ""}`}>{claude.is_set ? "Set" : "Not set"}</span></div>
          {claude.is_set && <div className="key-mask">{claude.masked}</div>}
          <div className="key-row">
            <input className="af-input" type="password" placeholder={claude.is_set ? "Replace key…" : "Paste Claude API key…"} value={inputs.claude_api_key || ""} onChange={(e) => setInputs({ ...inputs, claude_api_key: e.target.value })} />
            <button className="btn-mini primary" disabled={busy === "claude_api_key"} onClick={() => save("claude_api_key")}>{claude.is_set ? "Update" : "Save"}</button>
            {claude.is_set && <button className="btn-mini danger" onClick={() => remove("claude_api_key")}>Remove</button>}
          </div>
          <div className="test-row">
            <button className="btn-mini" disabled={busy === "tclaude"} onClick={() => runTest("tclaude", api.testClaude)}>Test Key</button>
            {results.tclaude && <span className={`test-result ${results.tclaude.ok ? "ok" : "bad"}`}>{results.tclaude.ok ? "✓ " : "✕ "}{results.tclaude.message}</span>}
          </div>
        </div>
      )}

      {/* SMTP */}
      {/* Brevo — HTTPS sending, works where the ISP blocks SMTP ports. */}
      {byName("brevo_api_key") && (
        <div className="settings-card">
          <div className="settings-card-head">
            <h2>Email — Sending via Brevo (recommended)</h2>
            <span className={`soon-tag ${byName("brevo_api_key")!.is_set ? "set" : ""}`}>
              {byName("brevo_api_key")!.is_set ? "Set" : "Not set"}
            </span>
          </div>
          <p style={{ fontSize: 12.5, color: "#8a93a6", marginBottom: 10 }}>
            Sends over HTTPS instead of SMTP, so it works even when your internet provider blocks
            mail ports. Free tier: 300 emails/day. Get a key at brevo.com → SMTP &amp; API → API Keys.
            When set, this is used instead of the SMTP settings below.
          </p>
          <div className="key-row">
            <input className="af-input" type="password"
              placeholder={byName("brevo_api_key")!.is_set ? "Replace key…" : "xkeysib-…"}
              value={inputs.brevo_api_key || ""}
              onChange={(e) => setInputs({ ...inputs, brevo_api_key: e.target.value })} />
            <button className="btn-mini primary" disabled={busy === "brevo_api_key"}
              onClick={() => save("brevo_api_key")}>Save</button>
            {byName("brevo_api_key")!.is_set && (
              <button className="btn-mini danger" onClick={() => remove("brevo_api_key")}>Remove</button>
            )}
          </div>
          <div className="cred-row">
            <label>Sender display name</label>
            <div className="key-row">
              <input className="af-input" placeholder="Kashif Rehman"
                value={inputs.sender_display_name ?? byName("sender_display_name")?.value ?? ""}
                onChange={(e) => setInputs({ ...inputs, sender_display_name: e.target.value })} />
              <button className="btn-mini primary" onClick={() => save("sender_display_name")}>Save</button>
            </div>
          </div>
          <div className="test-row">
            <button className="btn-mini" disabled={busy === "tsmtp"} onClick={() => runTest("tsmtp", api.testSmtp)}>
              Test sending connection
            </button>
            {results.tsmtp && <span className={`test-result ${results.tsmtp.ok ? "ok" : "bad"}`}>
              {results.tsmtp.ok ? "✓ " : "✕ "}{results.tsmtp.message}</span>}
          </div>
          <p className="cred-help">
            Your sending address (below) must be a <strong>verified sender</strong> in Brevo —
            add and confirm kashif@eldiancore.pro there first.
          </p>
        </div>
      )}

      <CredCard title="Email — Sending (SMTP)" emailKey={byName("smtp_email")} pwKey={byName("smtp_app_password")}
        hostKey={byName("smtp_host")} portKey={byName("smtp_port")}
        hostPlaceholder="smtp.hostinger.com (blank = Gmail)" portPlaceholder="465"
        inputs={inputs} setInputs={setInputs} save={save} remove={remove} busy={busy}
        test={<><button className="btn-mini" disabled={busy === "tsmtp"} onClick={() => runTest("tsmtp", api.testSmtp)}>Test SMTP connection</button>{results.tsmtp && <span className={`test-result ${results.tsmtp.ok ? "ok" : "bad"}`}>{results.tsmtp.ok ? "✓ " : "✕ "}{results.tsmtp.message}</span>}</>}
        help="Leave Host/Port blank for Gmail. For Hostinger use smtp.hostinger.com port 465, and your full mailbox password. For Gmail/Workspace use an App Password, not your account password." />

      {/* IMAP */}
      <CredCard title="Email — Inbox (IMAP, for reading replies)" emailKey={byName("imap_email")} pwKey={byName("imap_app_password")}
        hostKey={byName("imap_host")} portKey={byName("imap_port")}
        hostPlaceholder="imap.hostinger.com (blank = Gmail)" portPlaceholder="993"
        inputs={inputs} setInputs={setInputs} save={save} remove={remove} busy={busy}
        extra={<button className="btn-mini" disabled={busy === "same"} onClick={sameAsSmtp}>Same as sending email</button>}
        test={<><button className="btn-mini" disabled={busy === "timap"} onClick={() => runTest("timap", api.testImap)}>Test IMAP connection</button>{results.timap && <span className={`test-result ${results.timap.ok ? "ok" : "bad"}`}>{results.timap.ok ? "✓ " : "✕ "}{results.timap.message}</span>}</>}
        help="Reading replies uses the same kind of Gmail App Password. Click “Same as sending email” to reuse the SMTP credentials." />

      {/* Daily cap */}
      <div className="settings-card">
        <div className="settings-card-head"><h2>Daily sending cap</h2></div>
        <p style={{ fontSize: 12.5, color: "#8a93a6", marginBottom: 8 }}>Max cold emails sent per day (protects your sending reputation). Extra leads queue for the next day.</p>
        <div className="key-row">
          <input className="af-input" type="number" min={1} max={500} value={cap} onChange={(e) => setCap(Number(e.target.value))} style={{ width: 120 }} />
          <button className="btn-mini primary" disabled={busy === "cap"} onClick={saveCap}>Save cap</button>
        </div>
      </div>

      <ProvidersSection />
      <CompanySection />
      <UsageSection />

      <div className="panel help-panel">
        <p><strong>How this works:</strong> keys are stored <strong>encrypted</strong> and used automatically by the backend. Only the server’s <code>ENCRYPTION_SECRET</code> must be set at hosting level — everything else is managed here.</p>
      </div>
    </div>
  );
}

function CredCard({ title, emailKey, pwKey, hostKey, portKey, hostPlaceholder, portPlaceholder,
                    inputs, setInputs, save, remove, busy, test, help, extra }: any) {
  if (!emailKey || !pwKey) return null;
  const both = emailKey.is_set && pwKey.is_set;
  return (
    <div className="settings-card">
      <div className="settings-card-head"><h2>{title}</h2><span className={`soon-tag ${both ? "set" : ""}`}>{both ? "Set" : "Not set"}</span></div>

      {/* Mail server — blank uses the Gmail defaults. */}
      {hostKey && portKey && (
        <div className="cred-row">
          <label>Mail server <span style={{ textTransform: "none", letterSpacing: 0 }}>(leave blank for Gmail)</span></label>
          <div className="key-row">
            <input className="af-input" placeholder={hostPlaceholder}
              value={inputs[hostKey.key_name] ?? hostKey.value ?? ""}
              onChange={(e: any) => setInputs({ ...inputs, [hostKey.key_name]: e.target.value })} />
            <input className="af-input" style={{ maxWidth: 110 }} placeholder={portPlaceholder}
              value={inputs[portKey.key_name] ?? portKey.value ?? ""}
              onChange={(e: any) => setInputs({ ...inputs, [portKey.key_name]: e.target.value })} />
            <button className="btn-mini primary" disabled={busy === hostKey.key_name}
              onClick={async () => { await save(hostKey.key_name); await save(portKey.key_name); }}>Save</button>
          </div>
        </div>
      )}
      <div className="cred-row">
        <label>Email address</label>
        <div className="key-row">
          <input className="af-input" placeholder="you@gmail.com" value={inputs[emailKey.key_name] ?? emailKey.value ?? ""} onChange={(e) => setInputs({ ...inputs, [emailKey.key_name]: e.target.value })} />
          <button className="btn-mini primary" disabled={busy === emailKey.key_name} onClick={() => save(emailKey.key_name)}>Save</button>
        </div>
      </div>
      <div className="cred-row">
        <label>App password {pwKey.is_set && <span className="key-mask-inline">{pwKey.masked}</span>}</label>
        <div className="key-row">
          <input className="af-input" type="password" placeholder={pwKey.is_set ? "Replace app password…" : "Gmail app password…"} value={inputs[pwKey.key_name] || ""} onChange={(e) => setInputs({ ...inputs, [pwKey.key_name]: e.target.value })} />
          <button className="btn-mini primary" disabled={busy === pwKey.key_name} onClick={() => save(pwKey.key_name)}>Save</button>
          {pwKey.is_set && <button className="btn-mini danger" onClick={() => remove(pwKey.key_name)}>Remove</button>}
        </div>
      </div>
      {extra && <div style={{ marginTop: 6 }}>{extra}</div>}
      <div className="test-row">{test}</div>
      {help && <p className="cred-help">{help}</p>}
    </div>
  );
}
