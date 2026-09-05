"use client";

import { useEffect, useRef } from "react";
import type { LiveStatus } from "@/lib/api";
import { WORLD } from "./RoomDefinitions";
import { CHARACTER_CLICK_EVENT } from "./OfficeScene";

interface Props {
  status: LiveStatus | null;
  onCharacterClick: (id: string) => void;
  highlightId?: string | null;
}

// Mounts the Phaser game (client-side only) and is the ONLY bridge between
// React and Phaser: it pushes the high-level status object into the scene and
// forwards character clicks back out. All per-frame game logic stays inside
// Phaser's own update loop — never in React render.
export default function OfficeCanvas({ status, onCharacterClick, highlightId = null }: Props) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const gameRef = useRef<any>(null);
  const readyRef = useRef(false);
  const statusRef = useRef(status);
  statusRef.current = status;

  // Create the game once.
  useEffect(() => {
    let destroyed = false;

    (async () => {
      const PhaserModule = await import("phaser");
      const Phaser = (PhaserModule as any).default ?? PhaserModule;
      const { default: createOfficeScene } = await import("./OfficeScene");
      if (destroyed || !hostRef.current) return;

      const OfficeScene = createOfficeScene(Phaser);
      const game = new Phaser.Game({
        type: Phaser.AUTO,
        width: WORLD.width,
        height: WORLD.height,
        parent: hostRef.current,
        backgroundColor: "#05070d",
        scene: [OfficeScene],
        scale: {
          mode: Phaser.Scale.FIT,
          autoCenter: Phaser.Scale.CENTER_HORIZONTALLY,
        },
      });
      gameRef.current = game;

      // Once the scene has built itself, push the current status in (if loaded).
      game.events.once("office:ready", () => {
        readyRef.current = true;
        if (statusRef.current) game.events.emit("office:sync", statusRef.current);
      });
    })();

    const handleClick = (e: Event) =>
      onCharacterClick((e as CustomEvent).detail as string);
    window.addEventListener(CHARACTER_CLICK_EVENT, handleClick);

    return () => {
      destroyed = true;
      window.removeEventListener(CHARACTER_CLICK_EVENT, handleClick);
      readyRef.current = false;
      if (gameRef.current) {
        gameRef.current.destroy(true);
        gameRef.current = null;
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Whenever the status object changes, sync it into the running scene.
  useEffect(() => {
    if (readyRef.current && gameRef.current && status) {
      gameRef.current.events.emit("office:sync", status);
    }
  }, [status]);

  // Push the highlighted agent (from the Team Activity sidebar) into the scene.
  useEffect(() => {
    if (readyRef.current && gameRef.current) {
      gameRef.current.events.emit("office:highlight", highlightId);
    }
  }, [highlightId]);

  return (
    <div
      ref={hostRef}
      style={{ width: "100%", aspectRatio: `${WORLD.width} / ${WORLD.height}` }}
    />
  );
}
