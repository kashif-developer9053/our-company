import type { OfficeStatus } from "@/types/officeTypes";

// PHASE 1: the fake status object. It lives entirely in the frontend and drives
// every visual (lighting, character presence, tags, animations). Its shape is
// identical to the real status board we will wire up in a later phase, so
// swapping this file for a live WebSocket/API feed is a drop-in replacement.
//
// Every agent starts "offline" because no backend / Claude API is connected yet.
// Use the DEV DEBUG PANEL in the running app to flip these and preview all
// states without a backend.
export const initialOfficeStatus: OfficeStatus = {
  office_open: false,
  meeting_in_progress: false,
  agents: {
    supervisor: { status: "offline", location: "supervisor_room" },
    agent1: { status: "offline", location: "desk_1" },
    agent2: { status: "offline", location: "desk_2" },
    agent3: { status: "offline", location: "desk_3" },
    it_monitor: { status: "offline", location: "it_room" },
  },
};
