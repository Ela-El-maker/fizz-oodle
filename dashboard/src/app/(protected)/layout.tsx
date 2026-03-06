import type { ReactNode } from "react";
import { AppShell } from "@/shared/layout/AppShell";
import { AuthGate } from "@/features/auth/AuthGate";

export default function ProtectedLayout({ children }: { children: ReactNode }) {
  return (
    <AuthGate>
      <AppShell>{children}</AppShell>
    </AuthGate>
  );
}
