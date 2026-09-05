"use client";

import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import * as api from "@/lib/api";
import type { AiProvider, InstrVersion, LiveAgent } from "@/lib/api";

// Per-agent config: AI provider/model (+fallback) and editable, versioned
// instructions (with test-before-live and revert). Admin-only actions are gated
// server-side too.
export default function AgentConfigModal({ agent, onClose, onChanged }: { agent: LiveAgent; onClose: () => void; onChanged: () => void }) {
  const [tab, setTab] = useState<"ai" | "instructions">("ai");
  const [providers, setProviders] = useState<AiProvider[]>([]);
  const cfg = agent.ai_config || { provider_id: "claude", model: "claude-sonnet-5", fallback_provider_id: null, fallback_model: null };
  const [provider, setProvider] = useState(cfg.provider_id);
  const [model, setModel] = useState(cfg.model);
  const [fbProvider, setFbProvider] = useState(cfg.fallback_provider_id || "");
  const [fbModel, setFbModel] = useState(cfg.fallback_model || "");
  const [saved, setSaved] = useState(false);
  const [fetched, setFetched] = useState<Record<string, string[]>>({});
  const [fetchingModels, setFetchingModels] = useState(false);
  const [fetchMsg, setFetchMsg] = useState<string | null>(null);

  const [active, setActive] = useState("");
  const [versions, setVersions] = useState<InstrVersion[]>([]);
  const [draft, setDraft] = useState("");
  const [sample, setSample] = useState("");
  const [testOut, setTestOut] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.getProviders().then(setProviders).catch(() => {});
    api.getInstructions(agent.id).then((r) => { setActive(r.active); setDraft(r.active); setVersions(r.versions); }).catch(() => {});
  }, [agent.id]);

  const modelsFor = (pid: string) => {
    const builtin = providers.find((p) => p.provider_id === pid)?.available_models || [];
    return fetched[pid]?.length ? fetched[pid] : builtin;
  };

  const fetchModels = async (pid: string) => {
    setFetchingModels(true); setFetchMsg(null);
    try {
      const r = await api.fetchProviderModels(pid);
      if (r.models?.length) {
        setFetched((f) => ({ ...f, [pid]: r.models }));
        setFetchMsg(`Loaded ${r.models.length} models${r.ok ? "" : " (built-in — " + r.error + ")"}`);
        if (!r.models.includes(model)) setModel(r.models[0]);
      } else {
        setFetchMsg(r.error || "No models returned.");
      }
    } catch (e) { setFetchMsg((e as Error).message); }
    finally { setFetchingModels(false); }
  };

  const saveAi = async () => {
    setBusy(true);
    try {
      await api.setAgentAiConfig(agent.id, { provider_id: provider, model, fallback_provider_id: fbProvider || null, fallback_model: fbModel || null });
      setSaved(true); setTimeout(() => setSaved(false), 2000); onChanged();
    } finally { setBusy(false); }
  };
  const saveInstr = async () => {
    setBusy(true);
    try { const r = await api.saveInstructions(agent.id, draft); const g = await api.getInstructions(agent.id); setActive(g.active); setVersions(g.versions); alert(`Saved as v${r.version} (now active).`); }
    catch (e) { alert((e as Error).message); } finally { setBusy(false); }
  };
  const revert = async (v: number) => {
    if (!confirm(`Revert to version ${v}?`)) return;
    await api.activateInstructions(agent.id, v); const g = await api.getInstructions(agent.id); setActive(g.active); setDraft(g.active); setVersions(g.versions);
  };
  const testDraft = async () => {
    setBusy(true); setTestOut(null);
    try { const r = await api.testDraftInstructions(agent.id, draft, sample || "Give me a short example of your work."); setTestOut(r.ok ? r.output : `Error: ${r.error}`); }
    catch (e) { setTestOut((e as Error).message); } finally { setBusy(false); }
  };

  if (typeof document === "undefined") return null;

  return createPortal(
    <div className="chat-overlay" onClick={onClose}>
      <div className="chat-window" onClick={(e) => e.stopPropagation()} style={{ width: 560 }}>
        <div className="chat-head">
          <div><div className="name">Configure {agent.name}</div><div className="role">AI provider &amp; editable instructions</div></div>
          <button className="x" onClick={onClose}>×</button>
        </div>
        <div className="cfg-tabs">
          <button className={`chip ${tab === "ai" ? "active" : ""}`} onClick={() => setTab("ai")}>AI Configuration</button>
          <button className={`chip ${tab === "instructions" ? "active" : ""}`} onClick={() => setTab("instructions")}>Instructions</button>
        </div>

        {tab === "ai" && (
          <div className="cfg-body">
            <label className="build-label">Provider</label>
            <select className="af-input" value={provider} onChange={(e) => { setProvider(e.target.value); setModel(modelsFor(e.target.value)[0] || ""); }}>
              {providers.map((p) => <option key={p.provider_id} value={p.provider_id} disabled={!p.is_set}>{p.display_name}{p.is_set ? "" : " (not connected)"}</option>)}
            </select>
            <div className="key-row" style={{ marginTop: 8, marginBottom: 4 }}>
              <label className="build-label" style={{ margin: 0, flex: 1 }}>Model</label>
              <button className="btn-mini" disabled={fetchingModels} onClick={() => fetchModels(provider)}>
                {fetchingModels ? "Fetching…" : "Fetch models"}
              </button>
            </div>
            {modelsFor(provider).length ? (
              <select className="af-input" value={model} onChange={(e) => setModel(e.target.value)}>
                {!modelsFor(provider).includes(model) && model && <option value={model}>{model} (current)</option>}
                {modelsFor(provider).map((m) => <option key={m} value={m}>{m}</option>)}
              </select>
            ) : <input className="af-input" value={model} onChange={(e) => setModel(e.target.value)} placeholder="Type a model id, or click Fetch models" />}
            {fetchMsg && <div className="muted small" style={{ marginTop: 4 }}>{fetchMsg}</div>}

            <label className="build-label" style={{ marginTop: 12 }}>Fallback provider (optional)</label>
            <select className="af-input" value={fbProvider} onChange={(e) => { setFbProvider(e.target.value); setFbModel(modelsFor(e.target.value)[0] || ""); }}>
              <option value="">None</option>
              {providers.filter((p) => p.is_set).map((p) => <option key={p.provider_id} value={p.provider_id}>{p.display_name}</option>)}
            </select>
            {fbProvider && (modelsFor(fbProvider).length ? (
              <select className="af-input" style={{ marginTop: 6 }} value={fbModel} onChange={(e) => setFbModel(e.target.value)}>{modelsFor(fbProvider).map((m) => <option key={m} value={m}>{m}</option>)}</select>
            ) : <input className="af-input" style={{ marginTop: 6 }} value={fbModel} onChange={(e) => setFbModel(e.target.value)} placeholder="fallback model id" />)}

            <div style={{ marginTop: 12 }}><button className="btn-mini primary" disabled={busy} onClick={saveAi}>Save AI config</button> {saved && <span className="test-result ok">Saved — effective next call</span>}</div>
          </div>
        )}

        {tab === "instructions" && (
          <div className="cfg-body">
            <label className="build-label">Active instructions (edit → Save new version)</label>
            <textarea className="af-input" rows={6} value={draft} onChange={(e) => setDraft(e.target.value)} />
            <div className="key-row" style={{ marginTop: 8 }}>
              <input className="af-input" placeholder="Sample message to test the draft…" value={sample} onChange={(e) => setSample(e.target.value)} />
              <button className="btn-mini" disabled={busy} onClick={testDraft}>Test draft</button>
              <button className="btn-mini primary" disabled={busy} onClick={saveInstr}>Save new version</button>
            </div>
            {testOut !== null && <div className="it-diag" style={{ marginTop: 8 }}><strong>Draft output:</strong> {testOut}</div>}
            <label className="build-label" style={{ marginTop: 12 }}>Version history</label>
            <div className="version-list">
              {versions.map((v) => (
                <div key={v.version} className="version-row">
                  <span>v{v.version} · {v.created_by} {v.is_active ? <span className="soon-tag set">active</span> : null}</span>
                  {!v.is_active && <button className="btn-mini" onClick={() => revert(v.version)}>Revert to this</button>}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>,
    document.body
  );
}
