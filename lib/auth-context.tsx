"use client";

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import * as api from "./api";
import type { User } from "./api";

interface AuthCtx {
  user: User | null;
  loading: boolean;
  needsSetup: boolean;
  login: (email: string, password: string) => Promise<void>;
  doSetup: (name: string, email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  refreshMe: () => Promise<void>;
}

const Ctx = createContext<AuthCtx | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const [needsSetup, setNeedsSetup] = useState(false);

  const bootstrap = useCallback(async () => {
    setLoading(true);
    try {
      if (api.getToken()) {
        setUser(await api.getMe());
      } else {
        const r = await api.needsSetup();
        setNeedsSetup(r.needs_setup);
        setUser(null);
      }
    } catch {
      api.clearToken();
      setUser(null);
      // Re-check setup state so first-run still works if the token was stale.
      try {
        setNeedsSetup((await api.needsSetup()).needs_setup);
      } catch {
        /* backend down */
      }
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    bootstrap();
    const onUnauth = () => setUser(null);
    window.addEventListener("auth:unauthorized", onUnauth);
    return () => window.removeEventListener("auth:unauthorized", onUnauth);
  }, [bootstrap]);

  const login = async (email: string, password: string) => {
    const r = await api.login(email, password);
    api.setToken(r.token);
    setUser(r.user);
  };
  const doSetup = async (name: string, email: string, password: string) => {
    const r = await api.setupAdmin(name, email, password);
    api.setToken(r.token);
    setUser(r.user);
    setNeedsSetup(false);
  };
  const logout = async () => {
    try { await api.logout(); } catch { /* ignore */ }
    api.clearToken();
    setUser(null);
  };
  const refreshMe = async () => {
    try { setUser(await api.getMe()); } catch { /* ignore */ }
  };

  return (
    <Ctx.Provider value={{ user, loading, needsSetup, login, doSetup, logout, refreshMe }}>
      {children}
    </Ctx.Provider>
  );
}

export function useAuth() {
  const c = useContext(Ctx);
  if (!c) throw new Error("useAuth must be used within AuthProvider");
  return c;
}
