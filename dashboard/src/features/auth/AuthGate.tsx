"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";

export function AuthGate({ children }: { children: React.ReactNode }) {
  const [ready, setReady] = useState(false);
  const router = useRouter();

  useEffect(() => {
    let mounted = true;
    async function check() {
      const res = await fetch("/api/auth/me", { credentials: "include", cache: "no-store" });
      if (!mounted) return;
      if (!res.ok) {
        router.replace("/auth/login");
        return;
      }
      setReady(true);
    }
    void check();
    return () => {
      mounted = false;
    };
  }, [router]);

  if (!ready) {
    return <div className="p-6 text-sm text-muted">Checking session...</div>;
  }

  return <>{children}</>;
}
