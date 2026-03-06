"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { useTheme } from "next-themes";
import { Bell, Menu, Moon, Sun } from "lucide-react";
import { fetchHealth } from "@/entities/system/api";
import { fetchRuns } from "@/entities/run/api";
import { normalizeStatus } from "@/shared/lib/status";
import { Button } from "@/shared/ui/Button";
import { Badge } from "@/shared/ui/Badge";
import { Input } from "@/shared/ui/Input";

export function Topbar({ onMenuClick }: { onMenuClick?: () => void }) {
  const router = useRouter();
  const [now, setNow] = useState(() => new Date());
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const health = useQuery({
    queryKey: ["health", "topbar"],
    queryFn: fetchHealth,
    refetchInterval: 15000,
    staleTime: 15000,
  });
  const runs = useQuery({
    queryKey: ["runs", "topbar"],
    queryFn: () => fetchRuns({ limit: 200 }),
    refetchInterval: 10000,
    staleTime: 10000,
  });

  useEffect(() => {
    const id = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(id);
  }, []);

  const nowLabel = now.toLocaleString();
  const healthBadge = normalizeStatus(health.data?.status);
  const activeAgents = useMemo(() => {
    const map: Record<string, string> = {
      briefing: "A",
      announcements: "B",
      sentiment: "C",
      analyst: "D",
      archivist: "E",
      narrator: "F",
    };
    const values = new Set<string>();
    for (const row of runs.data?.items || []) {
      const status = normalizeStatus(row.status);
      if (status !== "running" && status !== "queued") continue;
      const code = map[(row.agent_name || "").toLowerCase()];
      if (code) values.add(code);
    }
    return Array.from(values).sort().join(" ") || "-";
  }, [runs.data?.items]);

  async function logout() {
    await fetch("/api/auth/logout", { method: "POST", credentials: "include" });
    router.replace("/auth/login");
  }

  return (
    <header className="sticky top-0 z-10 border-b border-line bg-[var(--topbar-bg)] px-3 py-3 backdrop-blur sm:px-4 lg:pl-80">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={onMenuClick}
            className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-line bg-elevated text-muted hover:bg-hover lg:hidden"
            aria-label="Open menu"
          >
            <Menu size={18} />
          </button>
          <div>
            <div className="text-sm font-semibold text-ink">Market Intelligence Dashboard</div>
            <div className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-ink-faint">
              <span className="tracking-[0.12em]">LIVE OPS • {nowLabel}</span>
              <Badge value={healthBadge} />
              <span>Agents Active: {activeAgents}</span>
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <div className="hidden w-72 lg:block">
            <Input placeholder="Search tickers, events, reports..." />
          </div>
          <button
            type="button"
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-line bg-elevated text-muted hover:bg-hover"
            aria-label="Toggle theme"
          >
            {mounted ? (theme === "dark" ? <Sun size={16} /> : <Moon size={16} />) : <Sun size={16} />}
          </button>
          <button
            type="button"
            className="inline-flex h-9 w-9 items-center justify-center rounded-lg border border-line bg-elevated text-muted hover:bg-hover"
            aria-label="Notifications"
          >
            <Bell size={16} />
          </button>
          <div className="hidden rounded-lg border border-line bg-elevated px-2.5 py-1 text-xs font-semibold text-ink-soft sm:block">
            OP
          </div>
          <Button variant="secondary" onClick={logout}>Logout</Button>
        </div>
      </div>
    </header>
  );
}
