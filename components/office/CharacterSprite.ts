import type { Accessory } from "./RoomDefinitions";
import type { Point } from "./RoomDefinitions";

// A reusable top-down character drawn with vector graphics (no image assets).
// Phase 1.5: now reads as a little person — distinct head, simple face/eyes,
// arms, animated legs (walk cycle), a grounding drop shadow, and a per-role
// accessory. The CEO uses a suit + crown variant and never walks (seated).
//
// Framework-agnostic: takes a Phaser.Scene, never touches React. `Phaser` types
// are loose (any) because the concrete object is injected at runtime.

const WALK_SPEED = 150; // logical px per second
const LEG_BASE = 22;

export interface CharacterConfig {
  id: string;
  name: string;
  role: string;
  color: number;
  accessory: Accessory;
}

export class CharacterSprite {
  private scene: any;
  readonly id: string;
  readonly name: string;
  readonly role: string;
  private color: number;
  private accessory: Accessory;

  container: any; // position = feet anchor
  private body: any; // bobs while walking/working
  private legL: any;
  private legR: any;
  private tagBg: any;
  private tagName: any;
  private tagStatus: any;
  private workIcon: any;
  private alertIcon: any;
  private alertTween: any = null;

  private bobTween: any = null;
  private workTween: any = null;
  private gearTween: any = null;
  private legTweens: any[] = [];
  private idleTween: any = null;

  present = false;
  currentTarget: Point | null = null;

  constructor(scene: any, cfg: CharacterConfig, spawn: Point, onClick: ((id: string) => void) | null) {
    this.scene = scene;
    this.id = cfg.id;
    this.name = cfg.name;
    this.role = cfg.role;
    this.color = cfg.color;
    this.accessory = cfg.accessory;

    this.container = scene.add.container(spawn.x, spawn.y);
    this.container.setDepth(40);

    const shadow = scene.add.graphics();
    shadow.fillStyle(0x000000, 0.3);
    shadow.fillEllipse(0, 30, 34, 11);

    this.body = scene.add.container(0, 0);

    // Legs (animated during walking).
    this.legL = scene.add.graphics();
    this.legR = scene.add.graphics();
    this.drawLeg(this.legL, -7);
    this.drawLeg(this.legR, 3);
    this.legL.y = LEG_BASE;
    this.legR.y = LEG_BASE;

    const torso = scene.add.graphics();
    this.drawTorso(torso);

    this.body.add([this.legL, this.legR, torso]);

    // Floating tag (name + status).
    this.tagBg = scene.add.graphics();
    this.tagName = scene.add
      .text(0, -52, cfg.name, {
        fontFamily: "system-ui, sans-serif",
        fontSize: "11px",
        color: "#eef1f7",
      })
      .setOrigin(0.5);
    this.tagStatus = scene.add
      .text(0, -38, "● Offline", {
        fontFamily: "system-ui, sans-serif",
        fontSize: "10px",
        color: "#9aa0a6",
      })
      .setOrigin(0.5);

    this.workIcon = scene.add
      .text(0, -70, "⚙", {
        fontFamily: "system-ui, sans-serif",
        fontSize: "16px",
        color: "#42a5f5",
      })
      .setOrigin(0.5)
      .setVisible(false);

    // Alert badge (IT Technician warning/risk, or any agent in error).
    this.alertIcon = scene.add
      .text(0, -74, "⚠", { fontFamily: "system-ui, sans-serif", fontSize: "18px", color: "#ffca28" })
      .setOrigin(0.5)
      .setVisible(false);

    this.container.add([shadow, this.body, this.tagBg, this.tagName, this.tagStatus, this.workIcon, this.alertIcon]);

    if (onClick) {
      const hit = scene.add.zone(0, -6, 46, 70).setInteractive({ useHandCursor: true });
      hit.on("pointerdown", () => onClick(this.id));
      this.container.add(hit);
    }

    this.redrawTagBg();
    this.container.setVisible(false);
  }

  // ---- drawing -------------------------------------------------------------
  private drawLeg(g: any, x: number) {
    g.clear();
    g.fillStyle(darken(this.color, 0.5), 1);
    g.fillRoundedRect(x, 0, 8, 12, 3);
    g.fillStyle(0x20252f, 1); // shoe
    g.fillRoundedRect(x, 8, 8, 5, 2);
  }

  private drawTorso(g: any) {
    const c = this.color;
    // Arms.
    g.fillStyle(darken(c, 0.82), 1);
    g.fillRoundedRect(-19, -2, 8, 20, 4);
    g.fillRoundedRect(11, -2, 8, 20, 4);
    g.fillStyle(lighten(c, 0.08), 1); // hands
    g.fillCircle(-15, 18, 4);
    g.fillCircle(15, 18, 4);

    // Torso.
    g.fillStyle(c, 1);
    g.fillRoundedRect(-14, -4, 28, 28, 10);
    g.fillStyle(darken(c, 0.85), 1);
    g.fillRoundedRect(7, -2, 7, 24, 6); // shading
    g.lineStyle(2, darken(c, 0.5), 1);
    g.strokeRoundedRect(-14, -4, 28, 28, 10);

    // Head.
    g.fillStyle(lighten(c, 0.06), 1);
    g.fillCircle(0, -16, 12);
    g.lineStyle(2, darken(c, 0.5), 1);
    g.strokeCircle(0, -16, 12);

    // Visor + eyes (face).
    g.fillStyle(0x9fd8ef, 1);
    g.fillRoundedRect(-9, -20, 18, 10, 5);
    g.fillStyle(0xcdeefb, 0.9);
    g.fillRoundedRect(-6, -19, 6, 3, 2);
    g.fillStyle(0x1c2530, 1); // eyes
    g.fillCircle(-3, -15, 1.7);
    g.fillCircle(4, -15, 1.7);

    this.drawAccessory(g);
  }

  private drawAccessory(g: any) {
    switch (this.accessory) {
      case "supervisor": {
        g.fillStyle(0xffffff, 0.95); // collar
        g.fillTriangle(-6, -4, 0, 0, 0, -6);
        g.fillTriangle(6, -4, 0, 0, 0, -6);
        g.fillStyle(0x8a1f2a, 1); // tie
        g.fillTriangle(0, -2, -3, 12, 3, 12);
        g.fillStyle(0xf1c40f, 1); // name badge
        g.fillRoundedRect(-12, 2, 6, 8, 1);
        break;
      }
      case "researcher": {
        g.lineStyle(2, 0xdfe7f2, 1); // magnifier
        g.strokeCircle(19, 12, 5);
        g.lineBetween(23, 16, 28, 21);
        g.fillStyle(0x9fd8ef, 0.5);
        g.fillCircle(19, 12, 4);
        break;
      }
      case "verifier": {
        g.fillStyle(0xe9edf4, 1); // clipboard
        g.fillRoundedRect(-8, 2, 16, 18, 2);
        g.fillStyle(0x9aa6ba, 1);
        g.fillRoundedRect(-3, 0, 6, 4, 1);
        g.lineStyle(1, 0x59c48a, 1);
        g.lineBetween(-5, 8, 5, 8);
        g.lineBetween(-5, 12, 5, 12);
        g.lineBetween(-5, 16, 2, 16);
        break;
      }
      case "outreach": {
        g.lineStyle(3, 0x2a3242, 1); // headset band
        g.beginPath();
        g.arc(0, -16, 14, Math.PI * 1.15, Math.PI * 1.85, false);
        g.strokePath();
        g.fillStyle(0x2a3242, 1);
        g.fillCircle(-13, -14, 3);
        g.fillCircle(13, -14, 3);
        g.lineStyle(2, 0x2a3242, 1); // mic
        g.lineBetween(13, -12, 8, -6);
        break;
      }
      case "it": {
        g.fillStyle(0xf7b733, 1); // hard hat
        g.slice(0, -18, 13, Math.PI, Math.PI * 2, true);
        g.fillPath();
        g.fillStyle(0xe0a01f, 1);
        g.fillRoundedRect(-15, -19, 30, 4, 2);
        g.fillStyle(0xf7b733, 1);
        g.fillRect(-3, -30, 6, 6);
        g.lineStyle(2, 0x9aa6ba, 1); // wrench on belt
        g.lineBetween(14, 12, 20, 18);
        g.fillStyle(0x9aa6ba, 1);
        g.fillCircle(20, 18, 3);
        break;
      }
      case "custom": {
        g.fillStyle(0x1c2431, 1); // briefcase body
        g.fillRoundedRect(-9, 3, 18, 13, 2);
        g.fillStyle(0x3a465c, 1);
        g.fillRect(-4, 1, 8, 3); // handle
        g.fillStyle(0x9fd8ef, 1);
        g.fillRect(-1, 7, 2, 5);
        break;
      }
      case "ceo": {
        g.fillStyle(0xffffff, 1); // dress shirt
        g.fillTriangle(0, -4, -7, 16, 7, 16);
        g.fillStyle(0x8a1f2a, 1); // tie
        g.fillTriangle(0, -2, -3, 14, 3, 14);
        g.fillStyle(0x151b26, 1); // suit lapels
        g.fillTriangle(-4, -4, -10, 16, -2, 0);
        g.fillTriangle(4, -4, 10, 16, 2, 0);
        g.fillStyle(0xf1c40f, 1); // crown
        g.fillTriangle(-10, -26, -10, -34, -5, -28);
        g.fillTriangle(0, -26, 0, -37, 5, -28);
        g.fillTriangle(10, -26, 10, -34, 5, -28);
        g.fillRect(-10, -27, 20, 3);
        break;
      }
    }
  }

  private redrawTagBg() {
    const w = Math.max(this.tagName.width, this.tagStatus.width) + 16;
    this.tagBg.clear();
    this.tagBg.fillStyle(0x0d1017, 0.8);
    this.tagBg.fillRoundedRect(-w / 2, -60, w, 30, 6);
    this.tagBg.lineStyle(1, 0x2a3242, 1);
    this.tagBg.strokeRoundedRect(-w / 2, -60, w, 30, 6);
  }

  // ---- public API ----------------------------------------------------------
  setTag(statusLabel: string, colorHex: string) {
    this.tagStatus.setText(`● ${statusLabel}`);
    this.tagStatus.setColor(colorHex);
    this.redrawTagBg();
  }

  // Show/hide a pulsing alert badge (color = warning yellow / risk-error red).
  setAlert(colorHex: string | null) {
    if (colorHex) {
      this.alertIcon.setColor(colorHex).setVisible(true);
      if (!this.alertTween) {
        this.alertTween = this.scene.tweens.add({
          targets: this.alertIcon, scale: 1.35, duration: 550, yoyo: true, repeat: -1, ease: "Sine.easeInOut",
        });
      }
    } else {
      if (this.alertTween) { this.alertTween.stop(); this.alertTween = null; }
      this.alertIcon.setScale(1).setVisible(false);
    }
  }

  // Update the displayed name (used when the CEO renames an agent).
  setName(name: string) {
    this.tagName.setText(name);
    this.redrawTagBg();
  }

  // Tear down this sprite entirely (used when a custom agent is deleted).
  destroy() {
    this.scene.tweens.killTweensOf(this.container);
    this.scene.tweens.killTweensOf(this.body);
    this.container.destroy(true);
  }

  show() {
    this.container.setVisible(true);
  }
  hide() {
    this.container.setVisible(false);
  }

  teleportTo(p: Point) {
    this.scene.tweens.killTweensOf(this.container);
    this.container.setPosition(p.x, p.y);
  }

  walkTo(points: Point[], onDone?: () => void) {
    this.scene.tweens.killTweensOf(this.container);
    this.startBob();
    this.startWalkCycle();
    const step = (i: number) => {
      if (i >= points.length) {
        this.stopBob();
        this.stopWalkCycle();
        onDone?.();
        return;
      }
      const p = points[i];
      const dx = p.x - this.container.x;
      const dy = p.y - this.container.y;
      const dist = Math.hypot(dx, dy);
      if (dist < 1) return step(i + 1);
      this.scene.tweens.add({
        targets: this.container,
        x: p.x,
        y: p.y,
        duration: Math.max(120, (dist / WALK_SPEED) * 1000),
        ease: "Linear",
        onComplete: () => step(i + 1),
      });
    };
    step(0);
  }

  private startBob() {
    this.stopBob();
    this.bobTween = this.scene.tweens.add({
      targets: this.body, y: -3, duration: 180, yoyo: true, repeat: -1, ease: "Sine.easeInOut",
    });
  }
  private stopBob() {
    if (this.bobTween) { this.bobTween.stop(); this.bobTween = null; }
    this.body.y = 0;
  }

  private startWalkCycle() {
    this.stopWalkCycle();
    this.legTweens = [
      this.scene.tweens.add({ targets: this.legL, y: LEG_BASE - 5, duration: 150, yoyo: true, repeat: -1, ease: "Sine.easeInOut" }),
      this.scene.tweens.add({ targets: this.legR, y: LEG_BASE - 5, duration: 150, yoyo: true, repeat: -1, delay: 150, ease: "Sine.easeInOut" }),
    ];
  }
  private stopWalkCycle() {
    this.legTweens.forEach((t) => t && t.stop());
    this.legTweens = [];
    this.legL.y = LEG_BASE;
    this.legR.y = LEG_BASE;
  }

  // "Working" micro-animation.
  startWork() {
    if (this.workTween) return;
    this.workIcon.setVisible(true);
    this.workTween = this.scene.tweens.add({
      targets: this.body, y: -2, duration: 320, yoyo: true, repeat: -1, ease: "Sine.easeInOut",
    });
    this.gearTween = this.scene.tweens.add({
      targets: this.workIcon, angle: 360, duration: 1600, repeat: -1, ease: "Linear",
    });
  }
  stopWork() {
    if (this.workTween) { this.workTween.stop(); this.workTween = null; }
    if (this.gearTween) { this.gearTween.stop(); this.gearTween = null; }
    this.workIcon.setVisible(false);
    this.workIcon.setAngle(0);
    if (!this.bobTween) this.body.y = 0;
  }

  // Gentle idle "attention" bob for the seated CEO.
  startIdle() {
    if (this.idleTween) return;
    this.idleTween = this.scene.tweens.add({
      targets: this.body, y: -1.5, duration: 1400, yoyo: true, repeat: -1, ease: "Sine.easeInOut",
    });
  }
}

// ---- color helpers ---------------------------------------------------------
function clamp(n: number) {
  return Math.max(0, Math.min(255, Math.round(n)));
}
function darken(hex: number, f: number): number {
  const r = clamp(((hex >> 16) & 0xff) * f);
  const g = clamp(((hex >> 8) & 0xff) * f);
  const b = clamp((hex & 0xff) * f);
  return (r << 16) | (g << 8) | b;
}
function lighten(hex: number, amt: number): number {
  const r = clamp(((hex >> 16) & 0xff) + 255 * amt);
  const g = clamp(((hex >> 8) & 0xff) + 255 * amt);
  const b = clamp((hex & 0xff) + 255 * amt);
  return (r << 16) | (g << 8) | b;
}
