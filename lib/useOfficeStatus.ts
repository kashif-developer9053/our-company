"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getStatus, type LiveStatus } from "./api";

// Polls the backend status board for live updates (spec allows polling instead
// of WebSockets). Returns the current status, a loading flag, an error, and a
// manual refresh (call after a mutation for an immediate update).
export function useOfficeStatus(intervalMs = 1500) {
  const [status, setStatus] = useState<LiveStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);

  const refresh = useCallback(async () => {
    try {
      const s = await getStatus();
      if (mounted.current) {
        setStatus(s);
        setError(null);
      }
    } catch (e) {
      if (mounted.current) setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    refresh();
    const t = setInterval(refresh, intervalMs);
    return () => {
      mounted.current = false;
      clearInterval(t);
    };
  }, [refresh, intervalMs]);

  return { status, error, refresh };
}
