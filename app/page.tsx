"use client";

import { useState } from "react";
import dynamic from "next/dynamic";
import { useOfficeStatus } from "@/lib/useOfficeStatus";
import * as api from "@/lib/api";
import TopBar from "@/components/ui/TopBar";
import DebugPanel from "@/components/ui/DebugPanel";
import ChatPopup from "@/components/ui/ChatPopup";
import TeamActivitySidebar from "@/components/ui/TeamActivitySidebar";
import OutreachSummary from "@/components/ui/OutreachSummary";
import NichePanel from "@/components/ui/NichePanel";
import PipelineBanner from "@/components/ui/PipelineBanner";
import StandupPanel from "@/components/ui/StandupPanel";

// Phaser must never be server-rendered — load the canvas client-side only.
const OfficeCanvas = dynamic(() => import("@/components/office/OfficeCanvas"), {
  ssr: false,
});

export default function Home() {
  // PHASE 2: state now comes from the real backend status board (polled), not a
  // mock file. Mutations call the API, then refresh for an immediate update.
  const { status, error, refresh } = useOfficeStatus();
  const [activeChar, setActiveChar] = useState<string | null>(null);
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);

  const officeOpen = status?.office_open ?? false;

  const toggleOffice = async () => {
    await api.setOffice(!officeOpen);
    refresh();
  };
  const setAgentStatus = async (id: string, s: string) => {
    await api.updateAgent(id, { status: s });
    refresh();
  };
  const setMeeting = async (inProgress: boolean) => {
    await api.setMeeting(inProgress);
    refresh();
  };

  const activeAgent = activeChar && status ? status.agents[activeChar] : null;

  return (
    <div className="office-layout">
      <TeamActivitySidebar
        status={status}
        selectedId={selectedAgent}
        onSelect={setSelectedAgent}
        onChanged={refresh}
      />

      <main className="office-center">
        <TopBar officeOpen={officeOpen} onToggle={toggleOffice} />

        {error && (
          <div className="backend-warn">
            ⚠ Can’t reach the backend at {api.API_BASE} ({error}). Start it with:
            <code> uvicorn app_entry:app</code> in <code>/backend</code>.
          </div>
        )}

        <PipelineBanner />

        <div className="game-shell">
          <OfficeCanvas
            status={status}
            onCharacterClick={setActiveChar}
            highlightId={selectedAgent}
          />
        </div>

        <div className="hint">
          Live data from the Python backend ({status?.backend ?? "connecting…"}).
          Click <strong>Supervisor</strong> or <strong>Agent 1</strong> on the map
          for a real Claude chat; use the panel below to run niche research.
        </div>

        <NichePanel onChanged={refresh} />
      </main>

      <OutreachSummary />

      <DebugPanel
        status={status}
        onSetAgentStatus={setAgentStatus}
        onSetOffice={(o) => api.setOffice(o).then(refresh)}
        onSetMeeting={setMeeting}
      />

      {activeAgent && (
        <ChatPopup agent={activeAgent} onClose={() => setActiveChar(null)} />
      )}

      {status?.meeting_in_progress && <StandupPanel onEnd={refresh} />}
    </div>
  );
}
