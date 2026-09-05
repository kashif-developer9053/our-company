import type { AnyStatus } from "@/types/officeTypes";
import { STATUS_META } from "@/types/officeTypes";
import { CharacterSprite } from "./CharacterSprite";
import {
  WORLD,
  BUILDING,
  CORRIDOR_Y,
  ROOMS,
  RoomDef,
  Door,
  EXTRA_DOORS,
  HOME_DESKS,
  DESK_SPRITES,
  MEETING_TABLE,
  MEETING_SEATS,
  CEO_DESK,
  CEO_SEAT,
  CEO_VISITOR_CHAIR,
  CEO_META,
  MAIN_GATE,
  ROLE_META,
  EXTRA_DESK_SLOTS,
  Point,
} from "./RoomDefinitions";

// Loose shape of one agent coming from the backend status board.
interface LiveAgentLike {
  id: string;
  name: string;
  role_key: string;
  status: string;
  is_default: boolean;
}
interface LiveStatusLike {
  office_open: boolean;
  meeting_in_progress: boolean;
  agents: Record<string, LiveAgentLike>;
}

export const CHARACTER_CLICK_EVENT = "office:character-click";

// Dynamic desk-monitor screen positions (kept out of the static bake so the
// screen color can track each agent's status).
const MON: Record<string, Point> = {
  supervisor: { x: 1025, y: 196 },
  agent1: { x: 150, y: 610 },
  agent2: { x: 360, y: 610 },
  agent3: { x: 600, y: 610 },
  it_monitor: { x: 1025, y: 610 },
};

// ---- color helpers ---------------------------------------------------------
function clamp(n: number) { return Math.max(0, Math.min(255, Math.round(n))); }
function darken(hex: number, f: number): number {
  return (clamp(((hex >> 16) & 0xff) * f) << 16) | (clamp(((hex >> 8) & 0xff) * f) << 8) | clamp((hex & 0xff) * f);
}
function lighten(hex: number, a: number): number {
  return (clamp(((hex >> 16) & 0xff) + 255 * a) << 16) | (clamp(((hex >> 8) & 0xff) + 255 * a) << 8) | clamp((hex & 0xff) + 255 * a);
}

// Screen glow color for a given status.
function screenColor(st: AnyStatus): { color: number; on: boolean } {
  switch (st) {
    case "offline": return { color: 0x27303f, on: false };
    case "working": return { color: 0x4aa3ff, on: true };
    case "error":
    case "risk": return { color: 0xef5350, on: true };
    case "warning": return { color: 0xffca28, on: true };
    default: return { color: 0x2bd0d9, on: true }; // idle / ok / in_meeting / in_ceo_office
  }
}

export default function createOfficeScene(Phaser: any) {
  return class OfficeScene extends Phaser.Scene {
    private characters: Record<string, CharacterSprite> = {};
    private ceo!: CharacterSprite;
    private ceoLamp: any;
    private ceoIdleStarted = false;
    private roomOverlays: any[] = [];
    private warmOverlay: any;
    private deskLamps: Record<string, any> = {};
    private deskScreens: Record<string, { screen: any; glow: any }> = {};
    private officeOpen = false;
    // True until the first syncStatus after this scene was (re)created. On a page
    // reload the office may ALREADY be open — staff belong at their desks, so we
    // place them there instead of replaying the walk-in-from-the-gate animation.
    private firstSync = true;
    private highlightId: string | null = null;
    private highlightRing: any;

    // Dynamic-agent bookkeeping.
    private agentHome: Record<string, Point> = {};
    private agentSeat: Record<string, Point> = {}; // meeting seat
    private agentName: Record<string, string> = {};
    private customDeskObjs: Record<string, any[]> = {}; // objects to destroy on removal
    private customSlotByAgent: Record<string, number> = {};

    constructor() { super("OfficeScene"); }

    create() {
      this.drawSpaceBackground();
      this.drawFloors();
      this.drawWallsAndDoors();
      this.drawFurniture();
      this.drawGate();
      this.drawRoomLabels();
      this.bakeStaticScenery();

      this.createDeskLamps();
      this.createDeskScreens();
      this.createDeskClickZones();
      // Characters are created dynamically from the backend agent list (below).
      this.createCeo();
      this.createHighlightRing();
      this.createLighting();

      this.roomOverlays.forEach((o) => o.setAlpha(0.85));
      this.warmOverlay.setAlpha(0);

      this.game.events.on("office:sync", this.syncStatus, this);
      this.game.events.on("office:highlight", this.onHighlight, this);
      this.events.once("shutdown", () => {
        this.game.events.off("office:sync", this.syncStatus, this);
        this.game.events.off("office:highlight", this.onHighlight, this);
      });
      this.game.events.emit("office:ready");
    }

    private createHighlightRing() {
      const g = this.add.graphics().setDepth(39);
      g.lineStyle(8, 0x7ee0a2, 0.18); g.strokeCircle(0, 0, 26);
      g.lineStyle(3, 0x7ee0a2, 0.95); g.strokeCircle(0, 0, 26);
      g.setVisible(false);
      this.highlightRing = g;
    }

    private onHighlight = (id: string | null) => {
      this.highlightId = id;
    };

    // Phaser calls this each frame — keep the highlight ring on the selected
    // character (which may be walking).
    update(time: number) {
      if (!this.highlightRing) return;
      const ch = this.highlightId ? this.characters[this.highlightId] : null;
      if (ch && ch.present && ch.container.visible) {
        this.highlightRing.setVisible(true);
        this.highlightRing.setPosition(ch.container.x, ch.container.y + 2);
        this.highlightRing.setScale(1 + Math.sin(time * 0.006) * 0.08);
      } else {
        this.highlightRing.setVisible(false);
      }
    }

    private bakeStaticScenery() {
      const objs = this.children.list.slice();
      const rt = this.add.renderTexture(0, 0, WORLD.width, WORLD.height).setOrigin(0, 0).setDepth(2);
      rt.draw(objs);
      objs.forEach((o: any) => o.destroy());
    }

    // ---- background --------------------------------------------------------
    private drawSpaceBackground() {
      const g = this.add.graphics().setDepth(0);
      g.fillStyle(0x05070d, 1);
      g.fillRect(0, 0, WORLD.width, WORLD.height);
      for (let i = 0; i < 120; i++) {
        g.fillStyle(0xffffff, 0.1 + Math.random() * 0.5);
        const s = Math.random() < 0.85 ? 1 : 2;
        g.fillRect(Math.random() * WORLD.width, Math.random() * WORLD.height, s, s);
      }
      // Faint planet for sci-fi vibe.
      g.fillStyle(0x243b5a, 0.5);
      g.fillCircle(1180, 90, 60);
      g.fillStyle(0x2f4d74, 0.5);
      g.fillCircle(1165, 78, 60);
    }

    // ---- continuous tiled floor -------------------------------------------
    private tileFloor(x: number, y: number, w: number, h: number, base: number, alt: number) {
      const g = this.add.graphics().setDepth(2);
      g.fillStyle(base, 1);
      g.fillRect(x, y, w, h);
      const t = 32;
      for (let j = 0; j * t < h; j++)
        for (let i = 0; i * t < w; i++) {
          if ((i + j) % 2 === 0) continue;
          const tx = x + i * t, ty = y + j * t;
          g.fillStyle(alt, 1);
          g.fillRect(tx, ty, Math.min(t, x + w - tx), Math.min(t, y + h - ty));
        }
    }

    private drawFloors() {
      // Building base (fills seams so the interior reads as one continuous floor).
      const base = this.add.graphics().setDepth(2);
      base.fillStyle(0x2b3342, 1);
      base.fillRect(BUILDING.x, BUILDING.y, BUILDING.w, BUILDING.h);
      ROOMS.forEach((r) => this.tileFloor(r.x, r.y, r.width, r.height, r.floor, darken(r.floor, 0.85)));
    }

    // ---- walls + doorways --------------------------------------------------
    private drawWallsAndDoors() {
      // Interior divider walls (thin, light).
      const iw = this.add.graphics().setDepth(3);
      iw.lineStyle(3, 0x46536e, 1);
      ROOMS.forEach((r) => iw.strokeRect(r.x, r.y, r.width, r.height));

      // Exterior wall (thick, dark) with an inner highlight.
      const ew = this.add.graphics().setDepth(3);
      ew.lineStyle(8, 0x161c28, 1);
      ew.strokeRoundedRect(BUILDING.x - 4, BUILDING.y - 4, BUILDING.w + 8, BUILDING.h + 8, 18);
      ew.lineStyle(2, 0x54617e, 0.8);
      ew.strokeRoundedRect(BUILDING.x, BUILDING.y, BUILDING.w, BUILDING.h, 14);

      // Cut doorways through interior walls.
      const doors: Door[] = [
        ...ROOMS.filter((r) => r.door).map((r) => r.door as Door),
        ...EXTRA_DOORS,
      ];
      doors.forEach((d) => this.drawDoorway(d));
    }

    private drawDoorway(d: Door) {
      const gap = 70, thick = 10;
      const g = this.add.graphics().setDepth(3);
      // Erase the wall segment with floor-toned threshold.
      g.fillStyle(0x33405a, 1);
      if (d.horizontal) {
        g.fillRect(d.x - gap / 2, d.y - thick / 2, gap, thick);
        g.fillStyle(0x1c2431, 1); // door posts
        g.fillRect(d.x - gap / 2 - 4, d.y - 7, 5, 14);
        g.fillRect(d.x + gap / 2 - 1, d.y - 7, 5, 14);
        g.fillStyle(0x5a6a86, 0.5); // threshold line
        g.fillRect(d.x - gap / 2, d.y - 1, gap, 2);
      } else {
        g.fillRect(d.x - thick / 2, d.y - gap / 2, thick, gap);
        g.fillStyle(0x1c2431, 1);
        g.fillRect(d.x - 7, d.y - gap / 2 - 4, 14, 5);
        g.fillRect(d.x - 7, d.y + gap / 2 - 1, 14, 5);
        g.fillStyle(0x5a6a86, 0.5);
        g.fillRect(d.x - 1, d.y - gap / 2, 2, gap);
      }
    }

    private drawRoomLabels() {
      ROOMS.forEach((r) => {
        const label = this.add.text(r.x + 14, r.y + 10, r.label, {
          fontFamily: "system-ui, sans-serif", fontSize: "12px", fontStyle: "bold", color: "#e7d7a0",
        }).setDepth(7);
        const u = this.add.graphics().setDepth(7);
        u.fillStyle(r.accent, 1);
        u.fillRect(r.x + 14, r.y + 27, Math.min(label.width, 120), 2);
      });
    }

    // ---- furniture primitives ---------------------------------------------
    private desk(x: number, y: number, w: number, h: number, top: number) {
      const g = this.add.graphics().setDepth(4);
      g.fillStyle(0x000000, 0.28); g.fillRoundedRect(x - w / 2 + 3, y - h / 2 + 5, w, h, 7);
      g.fillStyle(darken(top, 0.75), 1); g.fillRoundedRect(x - w / 2, y - h / 2, w, h, 7);
      g.fillStyle(top, 1); g.fillRoundedRect(x - w / 2, y - h / 2, w, h - 5, 7);
      g.lineStyle(1, lighten(top, 0.12), 0.8); g.strokeRoundedRect(x - w / 2 + 3, y - h / 2 + 3, w - 6, h - 10, 5);
    }
    private monitorBezel(x: number, y: number) {
      const g = this.add.graphics().setDepth(5);
      g.fillStyle(0x20283a, 1); g.fillRect(x - 3, y + 8, 6, 6); g.fillRect(x - 9, y + 13, 18, 3);
      g.fillStyle(0x11161f, 1); g.fillRoundedRect(x - 18, y - 13, 36, 25, 3);
      g.lineStyle(1, 0x3a465c, 1); g.strokeRoundedRect(x - 18, y - 13, 36, 25, 3);
    }
    private keyboard(x: number, y: number) {
      const g = this.add.graphics().setDepth(5);
      g.fillStyle(0xc9d2e0, 1); g.fillRoundedRect(x - 14, y - 5, 28, 11, 2);
      g.lineStyle(1, 0x8a94a8, 0.8); for (let i = -10; i <= 10; i += 4) g.lineBetween(x + i, y - 3, x + i, y + 4);
    }
    private mug(x: number, y: number, c = 0xcf5a4a) {
      const g = this.add.graphics().setDepth(5);
      g.fillStyle(c, 1); g.fillCircle(x, y, 5); g.lineStyle(2, c, 1); g.strokeCircle(x + 7, y, 3);
      g.fillStyle(lighten(c, 0.3), 1); g.fillCircle(x, y, 2.4);
    }
    private papers(x: number, y: number) {
      const g = this.add.graphics().setDepth(5);
      g.fillStyle(0xe9edf4, 1); g.fillRoundedRect(x - 8, y - 5, 16, 12, 1);
      g.fillStyle(0xf6f8fc, 1); g.fillRoundedRect(x - 6, y - 7, 16, 12, 1);
      g.lineStyle(1, 0xaab4c6, 1); g.lineBetween(x - 3, y - 3, x + 7, y - 3); g.lineBetween(x - 3, y, x + 7, y);
    }
    private officeChair(x: number, y: number, color: number) {
      const g = this.add.graphics().setDepth(3);
      g.lineStyle(3, 0x2a3242, 1);
      for (let a = 0; a < 5; a++) { const an = (a / 5) * Math.PI * 2; g.lineBetween(x, y + 2, x + Math.cos(an) * 13, y + 2 + Math.sin(an) * 13); }
      g.fillStyle(0x2a3242, 1); g.fillCircle(x, y + 2, 4);
      g.fillStyle(color, 1); g.fillRoundedRect(x - 12, y - 12, 24, 20, 6);
      g.fillStyle(lighten(color, 0.12), 1); g.fillRoundedRect(x - 12, y - 18, 24, 9, 5);
      g.lineStyle(2, darken(color, 0.6), 1); g.strokeRoundedRect(x - 12, y - 12, 24, 20, 6);
    }
    private plant(x: number, y: number, potColor = 0xb5713a, scale = 1) {
      const g = this.add.graphics().setDepth(4);
      const s = scale;
      g.fillStyle(0x000000, 0.25); g.fillEllipse(x, y + 16 * s, 26 * s, 8 * s);
      g.fillStyle(potColor, 1);
      g.fillPoints([{ x: x - 11 * s, y: y + 4 * s }, { x: x + 11 * s, y: y + 4 * s }, { x: x + 8 * s, y: y + 16 * s }, { x: x - 8 * s, y: y + 16 * s }], true);
      g.fillStyle(darken(potColor, 0.8), 1); g.fillRect(x - 11 * s, y + 2 * s, 22 * s, 4 * s);
      g.fillStyle(0x2f8a4c, 1); g.fillCircle(x, y - 6 * s, 13 * s);
      g.fillStyle(0x3fa35c, 1); g.fillCircle(x - 9 * s, y, 9 * s); g.fillCircle(x + 9 * s, y, 9 * s);
      g.fillStyle(0x4cbb6a, 1); g.fillCircle(x - 3 * s, y - 10 * s, 7 * s);
    }
    private sofa(x: number, y: number, w: number, color = 0x8a3d38) {
      const g = this.add.graphics().setDepth(4);
      g.fillStyle(0x000000, 0.25); g.fillRoundedRect(x - w / 2 + 3, y - 12, w, 34, 8);
      g.fillStyle(color, 1); g.fillRoundedRect(x - w / 2, y - 16, w, 36, 9);
      g.fillStyle(lighten(color, 0.1), 1); g.fillRoundedRect(x - w / 2 + 8, y - 12, w - 16, 24, 6);
      g.lineStyle(2, darken(color, 0.6), 1); g.strokeRoundedRect(x - w / 2, y - 16, w, 36, 9);
    }
    private cabinet(x: number, y: number) {
      const g = this.add.graphics().setDepth(4);
      g.fillStyle(0x000000, 0.22); g.fillRoundedRect(x - 15, y - 16, 30, 44, 4);
      g.fillStyle(0x59647c, 1); g.fillRoundedRect(x - 15, y - 20, 30, 44, 4);
      g.lineStyle(1, 0x2a3242, 1); g.lineBetween(x - 15, y - 2, x + 15, y - 2);
      g.fillStyle(0x38425a, 1); g.fillRect(x - 4, y - 14, 8, 3); g.fillRect(x - 4, y + 6, 8, 3);
      g.strokeRoundedRect(x - 15, y - 20, 30, 44, 4);
    }
    private serverRack(x: number, y: number) {
      const g = this.add.graphics().setDepth(4);
      g.fillStyle(0x000000, 0.28); g.fillRoundedRect(x - 20 + 3, y - 29, 40, 68, 5);
      g.fillStyle(0x1a2130, 1); g.fillRoundedRect(x - 20, y - 34, 40, 68, 5);
      g.lineStyle(1, 0x3a465c, 1); g.strokeRoundedRect(x - 20, y - 34, 40, 68, 5);
      const cols = [0x39d98a, 0xffca28, 0x39d98a, 0x4aa3ff, 0xef5350, 0x39d98a];
      for (let i = 0; i < 6; i++) {
        g.fillStyle(0x0c111a, 1); g.fillRect(x - 15, y - 28 + i * 10, 30, 7);
        g.fillStyle(cols[i], 0.95); g.fillRect(x - 13, y - 27 + i * 10, 3, 5);
        g.fillStyle(0x2a3446, 1); g.fillRect(x - 7, y - 27 + i * 10, 20, 5);
      }
    }
    private screenWall(x: number, y: number, cols: number, rows: number, tint = 0x39d98a) {
      const g = this.add.graphics().setDepth(4);
      for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) {
        const mx = x + c * 36, my = y + r * 28;
        g.fillStyle(0x0f141c, 1); g.fillRoundedRect(mx, my, 32, 24, 3);
        g.fillStyle(tint, 0.6); g.fillRect(mx + 3, my + 3, 26, 18);
        g.fillStyle(lighten(tint, 0.2), 0.5); g.fillRect(mx + 3, my + 3, 26, 4);
        g.lineStyle(1, 0x3a465c, 1); g.strokeRoundedRect(mx, my, 32, 24, 3);
      }
    }
    private rug(x: number, y: number, w: number, h: number, color: number) {
      const g = this.add.graphics().setDepth(3);
      g.fillStyle(color, 0.14); g.fillRoundedRect(x - w / 2, y - h / 2, w, h, 10);
      g.lineStyle(3, color, 0.26); g.strokeRoundedRect(x - w / 2 + 6, y - h / 2 + 6, w - 12, h - 12, 8);
    }
    private whiteboard(x: number, y: number, w: number) {
      const g = this.add.graphics().setDepth(4);
      g.fillStyle(0x2a3346, 1); g.fillRoundedRect(x - w / 2 - 3, y - 3, w + 6, 30, 3);
      g.fillStyle(0xf3f6fb, 1); g.fillRoundedRect(x - w / 2, y, w, 24, 2);
      g.lineStyle(2, 0x4aa3ff, 0.8); g.lineBetween(x - w / 2 + 8, y + 7, x - w / 2 + w * 0.5, y + 7);
      g.lineStyle(2, 0x39d98a, 0.8); g.lineBetween(x - w / 2 + 8, y + 14, x - w / 2 + w * 0.7, y + 14);
    }
    private clock(x: number, y: number) {
      const g = this.add.graphics().setDepth(5);
      g.fillStyle(0xe9edf4, 1); g.fillCircle(x, y, 9); g.lineStyle(2, 0x2a3242, 1); g.strokeCircle(x, y, 9);
      g.lineBetween(x, y, x, y - 6); g.lineBetween(x, y, x + 4, y + 2);
    }
    private picture(x: number, y: number, tint: number) {
      const g = this.add.graphics().setDepth(5);
      g.fillStyle(0x6d5236, 1); g.fillRoundedRect(x - 13, y - 10, 26, 20, 2);
      g.fillStyle(tint, 0.8); g.fillRect(x - 10, y - 7, 20, 14);
      g.fillStyle(lighten(tint, 0.2), 0.8); g.fillTriangle(x - 10, y + 7, x - 2, y - 2, x + 4, y + 7);
    }
    private waterCooler(x: number, y: number) {
      const g = this.add.graphics().setDepth(4);
      g.fillStyle(0xd8e6ef, 1); g.fillRoundedRect(x - 10, y - 26, 20, 18, 4);
      g.fillStyle(0x7fc4e8, 0.85); g.fillRoundedRect(x - 8, y - 24, 16, 14, 3);
      g.fillStyle(0xe9edf4, 1); g.fillRoundedRect(x - 12, y - 8, 24, 22, 3);
      g.lineStyle(1, 0x9aa6ba, 1); g.strokeRoundedRect(x - 12, y - 8, 24, 22, 3);
    }
    private coffeeMachine(x: number, y: number) {
      const g = this.add.graphics().setDepth(4);
      g.fillStyle(0x2b3342, 1); g.fillRoundedRect(x - 12, y - 20, 24, 30, 3);
      g.fillStyle(0x11161f, 1); g.fillRoundedRect(x - 8, y - 6, 16, 12, 2);
      g.fillStyle(0x6d4a2f, 1); g.fillRect(x - 5, y - 2, 10, 7);
      g.fillStyle(0x39d98a, 1); g.fillCircle(x + 7, y - 15, 2);
    }

    // ---- per-room furniture -----------------------------------------------
    private drawFurniture() {
      // CEO OFFICE.
      this.rug(230, 165, 320, 170, 0xc0554f);
      this.desk(CEO_DESK.x, CEO_DESK.y, 150, 54, 0x6d5236);
      this.monitorBezel(190, CEO_DESK.y - 4); // faces the CEO
      this.papers(275, CEO_DESK.y);
      this.mug(300, CEO_DESK.y + 6, 0xd9c98a);
      this.officeChair(CEO_VISITOR_CHAIR.x, CEO_VISITOR_CHAIR.y, 0x415a70);
      this.sofa(110, 235, 92);
      this.plant(70, 90, 0x4f8fb0, 1.1);
      this.plant(430, 95, 0xb5713a, 0.9);
      this.cabinet(430, 175);
      this.clock(255, 58);
      this.picture(150, 70, 0x59c48a);

      // SUPERVISOR ROOM.
      this.rug(1025, 175, 260, 130, 0x4f8fb0);
      this.screenWall(985, 62, 3, 1, 0x39d98a);
      this.desk(1025, 196, 150, 48, 0x33405a);
      this.papers(1065, 196);
      this.mug(1060, 178, 0x59c48a);
      this.cabinet(870, 120); this.cabinet(908, 120);
      this.plant(1190, 250, 0x4f8fb0, 1);
      this.picture(1170, 70, 0x4aa3ff);

      // MEETING ROOM.
      this.meetingTable();
      this.whiteboard(640, 62, 150);
      this.plant(500, 400, 0x3f9c8f, 0.9);
      this.plant(770, 400, 0xb5713a, 0.9);

      // EMPLOYEE ROOM (3 cubicles).
      this.rug(400, 590, 720, 210, 0x5b678a);
      (["agent1", "agent2", "agent3"] as const).forEach((id) => {
        const d = HOME_DESKS[id];
        const dv = this.add.graphics().setDepth(3);
        dv.fillStyle(0x323d52, 1);
        dv.fillRoundedRect(d.x - 62, d.y - 6, 6, 96, 3);
        dv.fillRoundedRect(d.x + 56, d.y - 6, 6, 96, 3);
        dv.fillStyle(0x2a3446, 1); dv.fillRoundedRect(d.x - 62, d.y - 6, 124, 6, 3);
        this.desk(d.x, d.y + 34, 100, 34, 0x33405a);
        this.monitorBezel(MON[id].x, MON[id].y - 8);
        this.keyboard(d.x, d.y + 50);
      });
      this.waterCooler(90, 500);
      this.coffeeMachine(150, 500);
      this.plant(760, 500, 0x5b678a, 1);

      // IT ROOM.
      this.rug(1025, 590, 340, 210, 0xd08a3a);
      this.serverRack(870, 505); this.serverRack(920, 505);
      this.screenWall(985, 480, 2, 2, 0x4aa3ff);
      this.desk(1025, 620, 120, 40, 0x33405a);
      this.monitorBezel(MON.it_monitor.x, MON.it_monitor.y - 8);
      this.keyboard(1025, 636);
      this.plant(1190, 660, 0xd08a3a, 1);

      // HALLWAY decor.
      this.plant(430, 360, 0x3a465c, 0.8);
      this.picture(120, 320, 0x59c48a);
      this.picture(1160, 320, 0x4aa3ff);
    }

    private meetingTable() {
      const { x, y } = MEETING_TABLE;
      const g = this.add.graphics().setDepth(3);
      g.fillStyle(0x000000, 0.28); g.fillEllipse(x + 3, y + 6, 210, 118);
      g.fillStyle(0x5a4630, 1); g.fillEllipse(x, y, 210, 118);
      g.fillStyle(0x6d5533, 1); g.fillEllipse(x, y, 188, 102);
      g.lineStyle(3, 0x40311f, 1); g.strokeEllipse(x, y, 210, 118);
      g.fillStyle(0x7d6440, 0.5); g.fillEllipse(x - 6, y - 8, 120, 52); // highlight
      Object.values(MEETING_SEATS).forEach((s) => this.officeChair(s.x, s.y, 0x394a63));
    }

    private drawGate() {
      const g = this.add.graphics().setDepth(4);
      const { x } = MAIN_GATE;
      const y = BUILDING.y + BUILDING.h; // bottom exterior wall
      g.fillStyle(0x33405a, 1); g.fillRect(x - 38, y - 6, 76, 12); // opening in exterior wall
      g.fillStyle(0x14324a, 1); g.fillRoundedRect(x - 42, y - 2, 84, 34, 6);
      g.fillStyle(0x1c455f, 1); g.fillRoundedRect(x - 36, y + 2, 72, 26, 5);
      g.lineStyle(3, 0x4f8fb0, 1); g.strokeRoundedRect(x - 42, y - 2, 84, 34, 6);
      g.lineStyle(2, 0x63b0d6, 0.9); g.lineBetween(x, y + 2, x, y + 28);
      this.add.text(x, y + 40, "MAIN GATE", { fontFamily: "system-ui, sans-serif", fontSize: "10px", color: "#8aa0b3" })
        .setOrigin(0.5).setDepth(7);
    }

    // ---- dynamic layers ----------------------------------------------------
    private createDeskLamps() {
      DESK_SPRITES.forEach((d) => {
        const glow = this.add.graphics().setDepth(3);
        glow.fillStyle(0xffd27a, 0.16); glow.fillCircle(d.x, d.y + 4, 48);
        glow.fillStyle(0xffe6a8, 0.24); glow.fillCircle(d.x, d.y + 4, 26);
        glow.setVisible(false);
        this.deskLamps[d.owner] = glow;
        if (d.label) this.add.text(d.x, d.y + 62, d.label, { fontFamily: "system-ui, sans-serif", fontSize: "10px", color: "#6b7488" }).setOrigin(0.5).setDepth(5);
      });
    }

    private createDeskScreens() {
      Object.keys(MON).forEach((id) => {
        const p = MON[id];
        const glow = this.add.rectangle(p.x, p.y - 8, 40, 28, 0x2bd0d9, 0).setDepth(5);
        const screen = this.add.rectangle(p.x, p.y - 8, 26, 16, 0x27303f, 1).setDepth(6);
        this.deskScreens[id] = { screen, glow };
      });
    }

    private createDeskClickZones() {
      DESK_SPRITES.forEach((d) => {
        const z = this.add.zone(d.x, d.y, 104, 96).setInteractive({ useHandCursor: true }).setDepth(20);
        z.on("pointerdown", () => this.emitClick(d.owner));
      });
    }

    // ---- dynamic agent reconciliation -------------------------------------
    // Create sprites for new agents, remove sprites for deleted agents, and
    // update names on rename — all driven by the backend agent list.
    private reconcileAgents(agents: Record<string, LiveAgentLike>) {
      // Remove agents that no longer exist.
      for (const id of Object.keys(this.characters)) {
        if (!agents[id]) this.removeAgent(id);
      }
      // Add/update.
      for (const id of Object.keys(agents)) {
        const a = agents[id];
        if (!this.characters[id]) this.ensureAgent(a);
        else if (this.agentName[id] !== a.name) {
          this.characters[id].setName(a.name);
          this.agentName[id] = a.name;
        }
      }
    }

    private ensureAgent(a: LiveAgentLike) {
      const meta = ROLE_META[a.role_key] || ROLE_META.custom;
      const isKnownDefault = a.is_default && !!HOME_DESKS[a.id as keyof typeof HOME_DESKS];

      if (isKnownDefault) {
        this.agentHome[a.id] = HOME_DESKS[a.id as keyof typeof HOME_DESKS];
        this.agentSeat[a.id] = MEETING_SEATS[a.id as keyof typeof MEETING_SEATS];
      } else {
        // CEO-added custom agent: allocate an extra desk slot and draw it.
        const slotIdx = this.allocateSlot(a.id);
        const slot = EXTRA_DESK_SLOTS[slotIdx] || EXTRA_DESK_SLOTS[EXTRA_DESK_SLOTS.length - 1];
        this.agentHome[a.id] = slot;
        this.agentSeat[a.id] = slot; // custom agents stay at their desk during meetings
        this.drawCustomDesk(a.id, slot);
      }

      this.agentName[a.id] = a.name;
      this.characters[a.id] = new CharacterSprite(
        this,
        { id: a.id, name: a.name, role: a.role_key, color: meta.color, accessory: meta.accessory },
        MAIN_GATE,
        (cid) => this.emitClick(cid)
      );
    }

    private removeAgent(id: string) {
      this.characters[id]?.destroy();
      delete this.characters[id];
      (this.customDeskObjs[id] || []).forEach((o) => o.destroy());
      delete this.customDeskObjs[id];
      delete this.deskLamps[id];
      delete this.deskScreens[id];
      delete this.agentHome[id];
      delete this.agentSeat[id];
      delete this.agentName[id];
      if (this.customSlotByAgent[id] !== undefined) delete this.customSlotByAgent[id];
    }

    private allocateSlot(id: string): number {
      const used = new Set(Object.values(this.customSlotByAgent));
      let i = 0;
      while (used.has(i) && i < EXTRA_DESK_SLOTS.length) i++;
      this.customSlotByAgent[id] = i;
      return i;
    }

    // Draw a desk + monitor + lamp + status screen + click zone for a custom agent.
    private drawCustomDesk(id: string, slot: Point) {
      const objs: any[] = [];
      const desk = this.add.graphics().setDepth(4);
      desk.fillStyle(0x000000, 0.28); desk.fillRoundedRect(slot.x - 48, slot.y + 20, 96, 32, 6);
      desk.fillStyle(0x33405a, 1); desk.fillRoundedRect(slot.x - 50, slot.y + 18, 100, 30, 6);
      objs.push(desk);
      const bez = this.add.graphics().setDepth(5);
      bez.fillStyle(0x11161f, 1); bez.fillRoundedRect(slot.x - 18, slot.y + 20, 36, 22, 3);
      objs.push(bez);

      const glow = this.add.graphics().setDepth(3);
      glow.fillStyle(0xffd27a, 0.16); glow.fillCircle(slot.x, slot.y + 4, 46);
      glow.fillStyle(0xffe6a8, 0.24); glow.fillCircle(slot.x, slot.y + 4, 24);
      glow.setVisible(false);
      this.deskLamps[id] = glow;
      objs.push(glow);

      const sGlow = this.add.rectangle(slot.x, slot.y + 30, 40, 26, 0x2bd0d9, 0).setDepth(5);
      const screen = this.add.rectangle(slot.x, slot.y + 30, 26, 15, 0x27303f, 1).setDepth(6);
      this.deskScreens[id] = { screen, glow: sGlow };
      objs.push(sGlow, screen);

      const label = this.add.text(slot.x, slot.y - 26, "new desk", { fontFamily: "system-ui, sans-serif", fontSize: "9px", color: "#6b7488" }).setOrigin(0.5).setDepth(5);
      objs.push(label);

      const zone = this.add.zone(slot.x, slot.y, 100, 90).setInteractive({ useHandCursor: true }).setDepth(20);
      zone.on("pointerdown", () => this.emitClick(id));
      objs.push(zone);

      this.customDeskObjs[id] = objs;
    }

    private createCeo() {
      this.ceo = new CharacterSprite(this, { id: "ceo", name: CEO_META.name, role: CEO_META.role, color: CEO_META.color, accessory: CEO_META.accessory }, CEO_SEAT, null);
      this.ceo.setTag("You", "#26c6da");
      // CEO attention lamp.
      this.ceoLamp = this.add.graphics().setDepth(3);
      this.ceoLamp.fillStyle(0xffd27a, 0.16); this.ceoLamp.fillCircle(CEO_DESK.x, CEO_DESK.y, 60);
      this.ceoLamp.fillStyle(0xffe6a8, 0.22); this.ceoLamp.fillCircle(CEO_DESK.x, CEO_DESK.y, 34);
      this.ceoLamp.setVisible(false);
    }

    private createLighting() {
      // Warm ambient glow when open (additive).
      this.warmOverlay = this.add.graphics().setDepth(28);
      this.warmOverlay.fillStyle(0xffcf8a, 1);
      this.warmOverlay.fillRect(BUILDING.x, BUILDING.y, BUILDING.w, BUILDING.h);
      this.warmOverlay.setBlendMode(Phaser.BlendModes.ADD);
      // Per-room darkness when closed.
      ROOMS.forEach((r) => {
        const o = this.add.graphics().setDepth(30);
        o.fillStyle(0x03040a, 1); o.fillRect(r.x, r.y, r.width, r.height);
        this.roomOverlays.push(o);
      });
    }

    private emitClick(id: string) {
      if (typeof window !== "undefined") window.dispatchEvent(new CustomEvent(CHARACTER_CLICK_EVENT, { detail: id }));
    }

    // ---- pathing (routes through doorways) ---------------------------------
    private findRoom(p: Point): RoomDef | undefined {
      return ROOMS.find((r) => p.x >= r.x && p.x <= r.x + r.width && p.y >= r.y && p.y <= r.y + r.height);
    }

    private buildPath(from: Point, to: Point): Point[] {
      const rFrom = this.findRoom(from);
      const rTo = this.findRoom(to);
      if (rFrom && rTo && rFrom.id === rTo.id) return [to];
      const pts: Point[] = [];
      if (rFrom?.door) pts.push({ x: rFrom.door.x, y: rFrom.door.y });
      pts.push({ x: rFrom?.door ? rFrom.door.x : from.x, y: CORRIDOR_Y });
      pts.push({ x: rTo?.door ? rTo.door.x : to.x, y: CORRIDOR_Y });
      if (rTo?.door) pts.push({ x: rTo.door.x, y: rTo.door.y });
      pts.push(to);
      // Dedupe near-equal consecutive points.
      return pts.filter((p, i) => i === 0 || Math.hypot(p.x - pts[i - 1].x, p.y - pts[i - 1].y) > 2);
    }

    private targetFor(id: string, status: LiveStatusLike): Point {
      const st = status.agents[id].status;
      const home = this.agentHome[id] || MAIN_GATE;
      if (st === "in_ceo_office") return CEO_VISITOR_CHAIR;
      if (st === "in_meeting" || status.meeting_in_progress) return this.agentSeat[id] || home;
      return home;
    }
    private samePoint(a: Point | null, b: Point | null) { return !!a && !!b && a.x === b.x && a.y === b.y; }

    private fadeLights(on: boolean, instant = false) {
      const overlayAlpha = on ? 0 : 0.85;
      const warmAlpha = on ? 0.06 : 0;
      this.roomOverlays.forEach((o) => {
        this.tweens.killTweensOf(o);
        instant ? o.setAlpha(overlayAlpha) : this.tweens.add({ targets: o, alpha: overlayAlpha, duration: 1000, ease: "Sine.easeInOut" });
      });
      this.tweens.killTweensOf(this.warmOverlay);
      instant ? this.warmOverlay.setAlpha(warmAlpha) : this.tweens.add({ targets: this.warmOverlay, alpha: warmAlpha, duration: 1000, ease: "Sine.easeInOut" });
    }

    private setMonitor(id: string, st: AnyStatus, active: boolean) {
      const ds = this.deskScreens[id]; if (!ds) return;
      if (!active) { ds.screen.setFillStyle(0x27303f, 1); ds.glow.setAlpha(0); return; }
      const { color, on } = screenColor(st);
      ds.screen.setFillStyle(color, on ? 0.95 : 1);
      ds.glow.setFillStyle(color, 1).setAlpha(on ? 0.28 : 0);
    }

    // ---- the one entry point React calls -----------------------------------
    syncStatus = (status: LiveStatusLike) => {
      // Create/remove/rename sprites to match the backend agent list first.
      this.reconcileAgents(status.agents);

      const prevOpen = this.officeOpen;
      this.officeOpen = status.office_open;
      if (status.office_open) this.fadeLights(true);

      // CEO is always in residence when the office is open (never walks in).
      if (status.office_open) {
        this.ceo.teleportTo(CEO_SEAT);
        this.ceo.show();
        if (!this.ceoIdleStarted) { this.ceo.startIdle(); this.ceoIdleStarted = true; }
        this.ceoLamp.setVisible(true);
      } else {
        this.ceo.hide();
        this.ceoLamp.setVisible(false);
      }

      const appearing: { id: string; target: Point }[] = [];
      Object.keys(status.agents).forEach((id) => {
        const st = status.agents[id].status as AnyStatus;
        const meta = STATUS_META[st] || STATUS_META.offline;
        const char = this.characters[id];
        if (!char) return;
        char.setTag(meta.label, meta.color);

        // Alert badge for trouble states (IT warning/risk, or any agent error).
        char.setAlert(status.office_open && (st === "warning" || st === "risk" || st === "error") ? meta.color : null);

        const active = status.office_open && st !== "offline";
        this.deskLamps[id]?.setVisible(active);
        this.setMonitor(id, st, active);
        if (st === "working") char.startWork(); else char.stopWork();

        const target = this.targetFor(id, status);
        if (active && !char.present) {
          char.present = true; appearing.push({ id, target });
        } else if (!active && char.present) {
          char.present = false;
          char.walkTo(this.buildPath({ x: char.container.x, y: char.container.y }, MAIN_GATE), () => char.hide());
        } else if (active && char.present && !this.samePoint(char.currentTarget, target)) {
          char.currentTarget = target;
          char.walkTo(this.buildPath({ x: char.container.x, y: char.container.y }, target));
        }
      });

      appearing.forEach((item, i) => {
        const char = this.characters[item.id];
        char.currentTarget = item.target;
        if (this.firstSync) {
          // Scene was just (re)built on an already-open office: seat them directly.
          char.teleportTo(item.target);
          char.show();
        } else {
          char.teleportTo(MAIN_GATE);
          char.show();
          this.time.delayedCall(i * 450, () => char.walkTo(this.buildPath(MAIN_GATE, item.target)));
        }
      });

      this.firstSync = false;

      if (!status.office_open && prevOpen) this.time.delayedCall(1600, () => this.fadeLights(false));
      else if (!status.office_open && !prevOpen) this.fadeLights(false, true);
    };
  };
}
