"use client";

import { useState } from "react";
import { useAuth } from "@/lib/auth-context";

// Shown whenever there's no valid session. If no users exist yet, it becomes the
// first-run "Create Admin Account" setup; otherwise it's the login form.
export default function AuthScreen() {
  const { needsSetup, login, doSetup } = useAuth();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErr(null);
    setBusy(true);
    try {
      if (needsSetup) await doSetup(name.trim(), email.trim(), password);
      else await login(email.trim(), password);
    } catch (e2) {
      setErr((e2 as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="auth-screen">
      <form className="auth-card" onSubmit={submit}>
        <div className="auth-brand">
          <svg width="30" height="30" viewBox="0 0 24 24" fill="none">
            <path d="M3 21h18M5 21V5a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v16M13 21V9a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v12" stroke="#7ee0a2" strokeWidth="1.6" strokeLinejoin="round" />
          </svg>
          <span>AI Agency · Virtual Office</span>
        </div>

        <h1>{needsSetup ? "Create Admin Account" : "Sign in"}</h1>
        <p className="auth-sub">
          {needsSetup
            ? "No users exist yet — set up the first administrator."
            : "Enter your credentials to access the office."}
        </p>

        {needsSetup && (
          <input className="af-input" placeholder="Your name" value={name} onChange={(e) => setName(e.target.value)} required />
        )}
        <input className="af-input" type="email" placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} required />
        <input className="af-input" type="password" placeholder="Password" value={password} onChange={(e) => setPassword(e.target.value)} required minLength={6} />

        {err && <div className="auth-err">{err}</div>}

        <button className="btn open auth-submit" disabled={busy} type="submit">
          {busy ? "Please wait…" : needsSetup ? "Create admin & continue" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
