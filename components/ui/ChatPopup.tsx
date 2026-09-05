"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { LiveAgent, ChatMsg, NextOption } from "@/lib/api";
import * as api from "@/lib/api";
import { roleLabel } from "@/lib/api";
import { STATUS_META, type AnyStatus } from "@/types/officeTypes";
import ITHealthPanel from "./ITHealthPanel";

// Phase 7: real live chat for EVERY agent (Supervisor, Agent 1/2/3, IT Tech, and
// custom agents). Opening a chat sends the character to the CEO office
// (in_ceo_office → walk animation); closing restores their prior status (walk
// back). Background jobs are unaffected — chat/movement is purely visual.
export default function ChatPopup({ agent, onClose, onLeadsChanged }: {
  agent: LiveAgent; onClose: () => void; onLeadsChanged?: () => void;
}) {
  const meta = STATUS_META[(agent.status as AnyStatus)] || STATUS_META.offline;
  const isIT = agent.id === "it_monitor";
  const isResearcher = agent.id === "agent1";
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  // Agent 1: hunt qualified leads straight from the chat.
  const [genNiche, setGenNiche] = useState("");
  const [genCity, setGenCity] = useState("");
  const [genTarget, setGenTarget] = useState(50);
  const [genBusy, setGenBusy] = useState(false);
  const [nextOptions, setNextOptions] = useState<NextOption[]>([]);
  const [lastHunt, setLastHunt] = useState<{ niche: string; city: string } | null>(null);
  const bodyRef = useRef<HTMLDivElement | null>(null);
  // Capture the status the agent had when the chat opened, to restore on close.
  const priorStatus = useRef(agent.status);

  useEffect(() => {
    // Walk to the CEO office for the duration of the chat.
    api.updateAgent(agent.id, { status: "in_ceo_office" }).catch(() => {});
    return () => {
      const back = priorStatus.current === "in_ceo_office" ? "idle" : priorStatus.current;
      api.updateAgent(agent.id, { status: back }).catch(() => {});
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => { bodyRef.current?.scrollTo(0, bodyRef.current.scrollHeight); }, [messages, sending]);

  const send = async () => {
    const text = input.trim();
    if (!text || sending) return;
    const history = messages;
    setMessages((m) => [...m, { role: "user", content: text }]);
    setInput("");
    setSending(true);
    try {
      const res = await api.agentChat(agent.id, text, history);
      if (res.ok && res.reply) setMessages((m) => [...m, { role: "agent", content: res.reply as string }]);
      else setMessages((m) => [...m, { role: "agent", content: `⚠ Sorry, I couldn't process that — ${res.error || "Claude API error"}` }]);
    } catch (e) {
      setMessages((m) => [...m, { role: "agent", content: `⚠ Sorry, I couldn't process that — ${(e as Error).message}` }]);
    } finally {
      setSending(false);
    }
  };

  // Agent 1's lead hunt, run from inside the chat. Keeps searching until it has
  // `genTarget` leads that each have a verified contact AND real site problems,
  // then offers the CEO the next-step choices as buttons.
  const runHunt = async (over?: { niche?: string; city?: string }) => {
    const n = (over?.niche ?? genNiche).trim();
    const c = over?.city ?? genCity.trim();
    if (!n || genBusy) return;
    setGenBusy(true);
    setNextOptions([]);
    setMessages((m) => [...m, {
      role: "user",
      content: `Find me ${genTarget} qualified leads for "${n}"${c ? " in " + c : ""}.`,
    }]);
    try {
      const res = await api.harvestLeads({ niche: n, city: c, target: genTarget });
      if (!res.ok) {
        setMessages((m) => [...m, { role: "agent", content: `⚠ Couldn't run the hunt — ${res.error}` }]);
        return;
      }
      const rej = res.rejected;
      const detail = rej
        ? ` I examined ${res.examined} businesses over ${res.rounds} search rounds and rejected ${rej.no_contact} with no verified contact and ${rej.good_site} whose sites are already fine.`
        : "";
      const staged = res.added
        ? ` ${res.added} are waiting for your approval on the CRM page — nothing is in the CRM yet.`
        : "";
      setMessages((m) => [...m, {
        role: "agent",
        content: `${res.complete ? "✅" : "⚠"} ${res.message ?? ""}${detail}${staged}`,
      }]);
      setLastHunt({ niche: n, city: c });
      setNextOptions(res.next_options ?? []);
      onLeadsChanged?.();
    } catch (e) {
      setMessages((m) => [...m, { role: "agent", content: `⚠ Couldn't run the hunt — ${(e as Error).message}` }]);
    } finally { setGenBusy(false); }
  };

  const chooseNext = (action: string) => {
    setNextOptions([]);
    if (action === "stop") {
      setMessages((m) => [...m, { role: "agent", content: "Understood — review the leads on the CRM page whenever you're ready." }]);
      return;
    }
    if (action === "more_same_niche") { runHunt({ niche: lastHunt?.niche }); return; }
    if (action === "widen_location") { setGenCity(""); runHunt({ niche: lastHunt?.niche, city: "" }); return; }
    if (action === "different_niche") {
      setGenNiche("");
      setMessages((m) => [...m, { role: "agent", content: "Sure — type the new niche below and I'll start a fresh hunt." }]);
    }
  };

  const hint = {
    supervisor: "Ask about status, what's pending, or give instructions.",
    agent1: "Ask about the niche research or reasoning.",
    agent2: "Ask about verified/rejected leads or duplicate logic.",
    agent3: "Ask about outreach sent, replies, or the interested queue.",
    it_monitor: "Ask why something's failing or about recent checks.",
  }[agent.id] || "Ask this agent about their work.";

  if (typeof document === "undefined") return null;

  return createPortal(
    <div className="chat-overlay" onClick={onClose}>
      <div className="chat-window" onClick={(e) => e.stopPropagation()} style={{ width: 460 }}>
        <div className="chat-head">
          <div>
            <div className="name">{isIT ? "IT Technician — System Health" : `Chat with ${agent.name}`}</div>
            <div className="role">
              {roleLabel(agent.role_key)} ·{" "}
              <span className="info-tag"><span className="dot" style={{ background: meta.color }} />{meta.label}</span>
            </div>
          </div>
          <button className="x" onClick={onClose} aria-label="Close">×</button>
        </div>

        {isIT && <ITHealthPanel />}

        <div className="chat-thread" ref={bodyRef} style={isIT ? { height: 200, marginTop: 10 } : undefined}>
          {messages.length === 0 && <div className="chat-hint">{hint}</div>}
          {messages.map((m, i) => (
            <div key={i} className={`bubble ${m.role === "user" ? "me" : "agent"}`}>{m.content}</div>
          ))}
          {sending && <div className="bubble agent typing"><span></span><span></span><span></span></div>}
        </div>
        {isResearcher && (
          <>
            {nextOptions.length > 0 && (
              <div className="hunt-next" style={{ marginTop: 8 }}>
                <div className="build-label">What should I do next?</div>
                {nextOptions.map((o) => (
                  <button key={o.action} className="hunt-option" onClick={() => chooseNext(o.action)} disabled={genBusy}>
                    <span className="hunt-option-label">{o.label}</span>
                    <span className="hunt-option-hint">{o.hint}</span>
                  </button>
                ))}
              </div>
            )}
            <div className="lead-gen-row" style={{ display: "flex", gap: 6, margin: "8px 0", flexWrap: "wrap" }}>
              <input className="af-input" style={{ flex: 2, minWidth: 110 }} placeholder="Niche (e.g. dental clinic)" value={genNiche} onChange={(e) => setGenNiche(e.target.value)} disabled={genBusy} />
              <input className="af-input" style={{ flex: 1, minWidth: 80 }} placeholder="City (opt.)" value={genCity} onChange={(e) => setGenCity(e.target.value)} disabled={genBusy} />
              <input className="af-input" type="number" min={1} max={200} style={{ width: 70 }} value={genTarget} onChange={(e) => setGenTarget(Number(e.target.value))} disabled={genBusy} title="How many qualified leads" />
              <button className="btn-mini primary" onClick={() => runHunt()} disabled={genBusy || !genNiche.trim()}>
                {genBusy ? "Hunting…" : `Find ${genTarget}`}
              </button>
            </div>
          </>
        )}
        <div className="chat-input-row">
          <input
            className="af-input"
            placeholder={`Message ${agent.name}…`}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && send()}
            disabled={sending}
          />
          <button className="btn-mini primary" onClick={send} disabled={sending || !input.trim()}>Send</button>
        </div>
      </div>
    </div>,
    document.body
  );
}
