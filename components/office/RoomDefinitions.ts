import type { AgentId } from "@/types/officeTypes";

// The office is rendered on a fixed logical canvas; Phaser's Scale.FIT scales it
// responsively. All coordinates are in this logical space. In Phase 1.5 the
// rooms TILE together (shared walls, no gaps) to read as one connected building.
export const WORLD = { width: 1280, height: 720 };

// Building interior bounds (exterior wall is drawn just outside this).
export const BUILDING = { x: 40, y: 40, w: 1200, h: 650 };

// Central hallway band centerline that pathing routes through.
export const CORRIDOR_Y = 365;

export interface Point {
  x: number;
  y: number;
}

export interface Door {
  x: number;
  y: number;
  horizontal: boolean; // true = opening in a horizontal wall (gap runs along x)
}

export interface RoomDef {
  id: string;
  label: string;
  x: number;
  y: number;
  width: number;
  height: number;
  floor: number; // base floor color
  accent: number; // label underline / trim
  door?: Door; // primary doorway connecting this room to the corridor
}

// ---- ROOMS (tiled: adjacent edges are shared walls) ------------------------
// Columns: L 40..470 | C 470..810 | R 810..1240
// Rows:    Top 40..300 | Mid 300..430 | Bottom 430..690
export const ROOMS: RoomDef[] = [
  {
    id: "ceo_office",
    label: "CEO OFFICE",
    x: 40, y: 40, width: 430, height: 260,
    floor: 0x3b2e2c, accent: 0xc0554f,
    door: { x: 255, y: 300, horizontal: true },
  },
  {
    id: "meeting_room",
    label: "MEETING ROOM",
    x: 470, y: 40, width: 340, height: 390,
    floor: 0x233a37, accent: 0x3f9c8f,
    door: { x: 470, y: 365, horizontal: false },
  },
  {
    id: "supervisor_room",
    label: "SUPERVISOR ROOM",
    x: 810, y: 40, width: 430, height: 260,
    floor: 0x24313f, accent: 0x4f8fb0,
    door: { x: 1025, y: 300, horizontal: true },
  },
  {
    id: "hallway1",
    label: "HALLWAY 1",
    x: 40, y: 300, width: 430, height: 130,
    floor: 0x2b3342, accent: 0x3a465c,
  },
  {
    id: "hallway2",
    label: "HALLWAY 2",
    x: 810, y: 300, width: 430, height: 130,
    floor: 0x2b3342, accent: 0x3a465c,
  },
  {
    id: "employee_room",
    label: "EMPLOYEE ROOM",
    x: 40, y: 430, width: 770, height: 260,
    floor: 0x263041, accent: 0x5b678a,
    door: { x: 200, y: 430, horizontal: true },
  },
  {
    id: "it_room",
    label: "IT ROOM",
    x: 810, y: 430, width: 430, height: 260,
    floor: 0x2a2733, accent: 0xd08a3a,
    door: { x: 1025, y: 430, horizontal: true },
  },
];

// Extra decorative doorways (visual only — not used for pathing).
export const EXTRA_DOORS: Door[] = [
  { x: 810, y: 365, horizontal: false }, // meeting <-> hallway2
  { x: 640, y: 430, horizontal: true }, // meeting <-> employee
];

// ---- HOME DESKS (default seat per character) -------------------------------
export const HOME_DESKS: Record<AgentId, Point> = {
  supervisor: { x: 1025, y: 170 },
  agent1: { x: 150, y: 585 },
  agent2: { x: 360, y: 585 },
  agent3: { x: 600, y: 585 },
  it_monitor: { x: 1025, y: 585 },
};

// Desk metadata used to draw desks, clickable zones, lamp glows, monitors.
export const DESK_SPRITES: {
  owner: AgentId;
  x: number;
  y: number;
  label: string;
}[] = [
  { owner: "supervisor", x: 1025, y: 170, label: "" },
  { owner: "agent1", x: 150, y: 585, label: "desk_1" },
  { owner: "agent2", x: 360, y: 585, label: "desk_2" },
  { owner: "agent3", x: 600, y: 585, label: "desk_3" },
  { owner: "it_monitor", x: 1025, y: 585, label: "" },
];

// ---- MEETING ROOM SEATS (around the table, one per character) --------------
export const MEETING_TABLE: Point = { x: 640, y: 235 };
export const MEETING_SEATS: Record<AgentId, Point> = {
  supervisor: { x: 640, y: 150 },
  agent1: { x: 555, y: 205 },
  agent2: { x: 725, y: 205 },
  agent3: { x: 575, y: 290 },
  it_monitor: { x: 705, y: 290 },
};

// ---- CEO (seated, always in residence when office is open) ------------------
export const CEO_DESK: Point = { x: 230, y: 158 };
export const CEO_SEAT: Point = { x: 230, y: 116 }; // behind desk, faces down
export const CEO_VISITOR_CHAIR: Point = { x: 230, y: 214 }; // across the desk

// The single entry/exit point (airlock on the Employee Room's bottom wall,
// aligned under the employee doorway so walk paths pass through the door).
export const MAIN_GATE: Point = { x: 200, y: 655 };

// ---- CHARACTER META --------------------------------------------------------
export type Accessory =
  | "supervisor"
  | "researcher"
  | "verifier"
  | "outreach"
  | "it"
  | "ceo"
  | "custom";

// Role → visual metadata (color + accessory). Used for BOTH default agents and
// CEO-added custom agents, so a new agent looks consistent with its role type.
export const ROLE_META: Record<string, { color: number; accessory: Accessory }> = {
  supervisor: { color: 0x4caf50, accessory: "supervisor" },
  researcher: { color: 0xef5350, accessory: "researcher" },
  verifier: { color: 0xf2c14e, accessory: "verifier" },
  outreach: { color: 0xab63d0, accessory: "outreach" },
  it_monitor: { color: 0xff9800, accessory: "it" },
  custom: { color: 0x26c6da, accessory: "custom" },
};

// Desks for CEO-added custom agents, placed along the top row of the Employee
// Room. Allocated in order as custom agents are created.
export const EXTRA_DESK_SLOTS: Point[] = [
  { x: 150, y: 478 },
  { x: 300, y: 478 },
  { x: 450, y: 478 },
  { x: 600, y: 478 },
  { x: 740, y: 478 },
];

export const AGENT_ORDER: AgentId[] = [
  "supervisor",
  "agent1",
  "agent2",
  "agent3",
  "it_monitor",
];

export const CHARACTER_META: Record<
  AgentId,
  { name: string; role: string; color: number; accessory: Accessory }
> = {
  supervisor: { name: "Supervisor", role: "Manager", color: 0x4caf50, accessory: "supervisor" },
  agent1: { name: "Agent 1", role: "Researcher", color: 0xef5350, accessory: "researcher" },
  agent2: { name: "Agent 2", role: "Verifier", color: 0xf2c14e, accessory: "verifier" },
  agent3: { name: "Agent 3", role: "Outreach", color: 0xab63d0, accessory: "outreach" },
  it_monitor: { name: "IT Tech", role: "System Health", color: 0xff9800, accessory: "it" },
};

// CEO character meta (not an agent; represents the human user, seated).
export const CEO_META = {
  name: "CEO",
  role: "You",
  color: 0x2c3a58, // dark suit
  accessory: "ceo" as Accessory,
};
