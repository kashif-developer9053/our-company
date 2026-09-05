"use client";

import { STATUS_META, type AnyStatus } from "@/types/officeTypes";

// Small reusable status chip: a color-coded dot + the status label. Used by the
// debug panel and the chat popup header. (Inside the Phaser canvas the floating
// tags are drawn by CharacterSprite; this is the DOM-side equivalent.)
export default function CharacterInfoTag({ status }: { status: AnyStatus }) {
  const meta = STATUS_META[status];
  return (
    <span className="info-tag">
      <span className="dot" style={{ background: meta.color }} />
      {meta.label}
    </span>
  );
}
