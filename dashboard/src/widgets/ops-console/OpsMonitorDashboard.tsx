"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchHealth } from "@/entities/system/api";
import { fetchRuns } from "@/entities/run/api";
import { fetchAnnouncements, fetchAnnouncementStats } from "@/entities/announcement/api";
import { Panel } from "@/shared/ui/Panel";
import { StatCard } from "@/shared/ui/StatCard";
import { Badge } from "@/shared/ui/Badge";
import { fmtDateTime, fmtNumber } from "@/shared/lib/format";
import { normalizeStatus } from "@/shared/lib/status";
import { ChainHealthWidget } from "@/widgets/chain-health/ChainHealthWidget";

function toDisplayStatus(value: string): string {
  switch (value) {
    case "success":
      return "healthy";
    case "partial":
      return "degraded";
    case "fail":
      return "error";
    case "running":
      return "processing";
    default:
      return value;
  }
}

function ageMinutes(value: string | null | undefined): number | null {
  if (!value) return null;
  const ts = Date.parse(value);
  if (Number.isNaN(ts)) return null;
  return Math.max(0, Math.round((Date.now() - ts) / 60000));
}

function durationLabel(startedAt: string | null | undefined, finishedAt: string | null | undefined): string {
  if (!startedAt || !finishedAt) return "-";
  const start = Date.parse(startedAt);
  const end = Date.parse(finishedAt);
  if (Number.isNaN(start) || Number.isNaN(end) || end < start) return "-";
  const totalSeconds = Math.round((end - start) / 1000);
  if (totalSeconds < 60) return `${totalSeconds}s`;
  const mins = Math.floor(totalSeconds / 60);
  const secs = totalSeconds % 60;
  return `${mins}m ${secs}s`;
}

function resolveAgentName(row: {
  agent_name?: string | null;
  status_reason?: string | null;
  error_message?: string | null;
  metrics?: Record<string, unknown> | null;
}): string {
  const name = (row.agent_name || "").trim().toLowerCase();
  if (name && name !== "unknown" && name !== "-") return name;

  const haystack = `${row.status_reason || ""} ${row.error_message || ""} ${JSON.stringify(row.metrics || {})}`.toLowerCase();
  if (haystack.includes("narrator")) return "narrator";
  if (haystack.includes("announcements")) return "announcements";
  if (haystack.includes("sentiment")) return "sentiment";
  if (haystack.includes("briefing")) return "briefing";
  if (haystack.includes("analyst")) return "analyst";
  if (haystack.includes("archivist") || haystack.includes("pattern")) return "archivist";
  return "unknown";
}

function agentLabel(agentName: string): string {
  const key = (agentName || "").toLowerCase();
  if (key === "briefing") return "Agent A";
  if (key === "announcements") return "Agent B";
  if (key === "sentiment") return "Agent C";
  if (key === "analyst") return "Agent D";
  if (key === "archivist") return "Agent E";
  if (key === "narrator") return "Agent F";
  return "unknown";
}

export function OpsMonitorDashboard() {
  const nowLabel = new Date().toLocaleString();

  const health = useQuery({
    queryKey: ["health", "overview-monitor"],
    queryFn: fetchHealth,
    refetchInterval: 15000,
    staleTime: 15000,
  });
  const runs = useQuery({
    queryKey: ["runs", "overview-monitor"],
    queryFn: () => fetchRuns({ limit: 200 }),
    refetchInterval: 5000,
    staleTime: 5000,
  });
  const announcementStats = useQuery({
    queryKey: ["announcement-stats", "overview-monitor"],
    queryFn: fetchAnnouncementStats,
    refetchInterval: 30000,
    staleTime: 30000,
  });
  const announcementFeed = useQuery({
    queryKey: ["announcements", "overview-monitor"],
    queryFn: () => fetchAnnouncements({ limit: 250, scope: "all" }),
    refetchInterval: 30000,
    staleTime: 30000,
  });

  const rows = runs.data?.items || [];
  const dependencies = Object.entries(health.data?.dependencies || {});
  const healthyDeps = dependencies.filter(([, raw]) => {
    const dep = raw as { status?: string };
    return normalizeStatus(dep.status) === "success";
  }).length;

  const activeRuns = rows.filter((r) => {
    const s = normalizeStatus(r.status);
    return s === "queued" || s === "running";
  }).length;

  const latestActivity = rows
    .map((r) => r.finished_at || r.started_at || null)
    .find((v) => !!v) || null;
  const freshnessMins = ageMinutes(latestActivity);

  const healthStatus = normalizeStatus(health.data?.status);
  const healthTone = healthStatus === "success" ? "success" : healthStatus === "partial" ? "warning" : "danger";
  const liveBadge = healthStatus === "success" ? "live" : "degraded";

  const executionRows = rows.slice(0, 8);
  const fallbackAlerted = (announcementFeed.data?.items || []).filter((item) => !!item.alerted).length;
  const fallbackTotal = announcementFeed.data?.total ?? (announcementFeed.data?.items || []).length;
  const alertedEvents = announcementStats.data?.alerted ?? fallbackAlerted;
  const totalTracked = announcementStats.data?.total ?? fallbackTotal;

  return (
    <div className="space-y-4">
      <Panel title="Operator Mission Control">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-lg font-semibold text-ink">Operations Console</h2>
            <p className="text-xs text-muted">Live system health, pipeline integrity, and execution telemetry.</p>
          </div>
          <div className="flex items-center gap-2 text-xs text-muted">
            <Badge value={liveBadge} />
            <span>{nowLabel}</span>
          </div>
        </div>
      </Panel>

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="System Health"
          value={toDisplayStatus(healthStatus).toUpperCase()}
          hint={`${healthyDeps}/${dependencies.length} dependencies healthy`}
          tone={healthTone}
        />
        <StatCard
          label="Active Runs"
          value={activeRuns}
          hint="queued + running"
          tone={activeRuns > 0 ? "brand" : "neutral"}
        />
        <StatCard
          label="Data Freshness"
          value={freshnessMins === null ? "-" : `${freshnessMins}m`}
          hint={latestActivity ? `latest ${fmtDateTime(latestActivity)}` : "no run activity"}
          tone={freshnessMins !== null && freshnessMins <= 15 ? "success" : "warning"}
        />
        <StatCard
          label="Alerted Events"
          value={fmtNumber(alertedEvents)}
          hint={`Total tracked ${fmtNumber(totalTracked)}`}
          tone="warning"
        />
      </div>

      <ChainHealthWidget />

      <Panel title="Execution Snapshot">
        {runs.isLoading ? (
          <div className="text-sm text-muted">Loading recent runs...</div>
        ) : runs.isError ? (
          <div className="text-sm text-red-300">Failed to load execution snapshot.</div>
        ) : executionRows.length === 0 ? (
          <div className="text-sm text-muted">No run data available yet.</div>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-line">
            <table className="w-full text-sm">
              <thead className="bg-inset">
                <tr className="text-left text-xs uppercase tracking-wide text-ink-faint">
                  <th className="px-3 py-3">Agent</th>
                  <th className="px-2 py-3">Last Update</th>
                  <th className="px-2 py-3">Duration</th>
                  <th className="px-2 py-3">Status</th>
                  <th className="px-3 py-3">Outcome</th>
                </tr>
              </thead>
              <tbody>
                {executionRows.map((row) => (
                  <tr key={row.run_id} className="border-t border-line hover:bg-hover">
                    <td className="px-3 py-3 text-ink">{agentLabel(resolveAgentName(row))}</td>
                    <td className="px-2 py-3 text-muted">{fmtDateTime(row.finished_at || row.started_at)}</td>
                    <td className="px-2 py-3 text-ink-soft">{durationLabel(row.started_at, row.finished_at)}</td>
                    <td className="px-2 py-3"><Badge value={normalizeStatus(row.status)} /></td>
                    <td className="max-w-[360px] px-3 py-3 text-muted">
                      {(row.status_reason || row.error_message || "-").toString().replace(/_/g, " ")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>
    </div>
  );
}
