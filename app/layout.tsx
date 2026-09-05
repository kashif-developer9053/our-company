import "./globals.css";
import type { ReactNode } from "react";
import { AuthProvider } from "@/lib/auth-context";
import AppFrame from "@/components/app/AppFrame";

export const metadata = {
  title: "AI Agency — Virtual Office",
  description: "Phase 3 — real Claude reasoning + auth (backend-connected)",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <AuthProvider>
          <AppFrame>{children}</AppFrame>
        </AuthProvider>
      </body>
    </html>
  );
}
