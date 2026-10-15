"use client";

import { useAuth } from "@/lib/auth-context";
import CallDesk from "@/components/calls/CallDesk";

export default function CallsPage() {
  const { user } = useAuth();
  return <CallDesk callerName={user?.name || ""} />;
}
