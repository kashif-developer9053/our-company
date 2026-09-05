"use client";

import { useEffect, useState } from "react";
import * as api from "@/lib/api";
import type { PipelineRun } from "@/lib/api";

// Shows the latest lead-generation run: a live "running" indicator while the
// scrape/verify pipeline works, then the completion/error summary to the CEO.
export default function PipelineBanner() {
  const [run, setRun] = useState<PipelineRun | null>(null);
  const [dismissed, setDismissed] = useState<string | null>(null);

  useEffect(() => {
    let on = true;
    const load = async () => {
      try {
        const runs = await api.getPipelineRuns();
        if (on) setRun(runs[0] ?? null);
      } catch { /* ignore */ }
    };
    load();
    const t = setInterval(load, 2500);
    return () => { on = false; clearInterval(t); };
  }, []);

  if (!run) return null;
  if (run.status !== "running" && dismissed === run.id) return null;

  const cls = run.status === "error" ? "pipe-err" : run.status === "running" ? "pipe-run" : "pipe-ok";
  return (
    <div className={`pipeline-banner ${cls}`}>
      <div className="pipe-body">
        {run.status === "running" && (
          <><span className="pipe-spin" /> Lead generation running for <strong>{run.niche_name}</strong> in {run.city || run.country}…</>
        )}
        {run.status === "complete" && <>✓ {run.message}</>}
        {run.status === "error" && <>⚠ {run.message}</>}
      </div>
      {run.status !== "running" && (
        <button className="pipe-x" onClick={() => setDismissed(run.id)}>×</button>
      )}
    </div>
  );
}
