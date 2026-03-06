"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchHealth } from "@/entities/system/api";
import { fetchRuns } from "@/entities/run/api";
import { fetchAnnouncements, fetchAnnouncementStats } from "@/entities/announcement/api";
import { fetchLatestReport } from "@/entities/report/api";
import { fetchSentimentDigestLatest } from "@/entities/sentiment/api";
import { fetchPatternSummary } from "@/entities/pattern/api";
import { fetchLatestArchive } from "@/entities/archive/api";
import { useTriggerAgent } from "@/features/trigger-agent/useTriggerAgent";
import { useDebouncedValue } from "@/features/filters/useDebouncedValue";
import { Panel } from "@/shared/ui/Panel";
import { Badge } from "@/shared/ui/Badge";
import { Button } from "@/shared/ui/Button";
import { Input } from "@/shared/ui/Input";
import { Select } from "@/shared/ui/Select";
import { Modal } from "@/shared/ui/Modal";
import { StatCard } from "@/shared/ui/StatCard";
import { Tabs, type TabItem } from "@/shared/ui/Tabs";
import { fmtDateTime, fmtNumber } from "@/shared/lib/format";
import { normalizeStatus } from "@/shared/lib/status";
import { ChainHealthWidget } from "@/widgets/chain-health/ChainHealthWidget";

type ConsoleTab = "overview" | "agents" | "insights" | "logs";
type AgentName = "briefing" | "announcements" | "sentiment" | "analyst" | "archivist" | "narrator";

const TAB_ITEMS: TabItem[] = [
  { key: "overview", label: "Overview" },
  { key: "agents", label: "Agents" },
  { key: "insights", label: "Market Insights" },
  { key: "logs", label: "Execution Logs" },
];

const AGENT_LABELS: Record<AgentName, string> = {
  briefing: "Agent A · Collector",
  announcements: "Agent B · Cleaner",
  sentiment: "Agent C · Processor",
  analyst: "Agent D · Orchestrator",
  archivist: "Agent E · Publisher",
  narrator: "Agent F · Narrator",
};

function humanize(value: string | null | undefined): string {
  if (!value) return "-";
  return value
    .replace(/_/g, " ")
    .replace(/\s+/g, " ")
    .trim();
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

function safeList<T>(value: T[] | undefined | null): T[] {
  return Array.isArray(value) ? value : [];
}

function summaryText(
  summaryV2: { headline?: string | null; plain_summary?: string | null; key_drivers?: string[] } | null | undefined,
  legacy: { headline?: string | null; plain_summary?: string | null; bullets?: string[] } | null | undefined,
) {
  return {
    headline: summaryV2?.headline || legacy?.headline || null,
    plain: summaryV2?.plain_summary || legacy?.plain_summary || null,
    drivers: (summaryV2?.key_drivers && summaryV2.key_drivers.length > 0) ? summaryV2.key_drivers : (legacy?.bullets || []),
  };
}

function truncateText(value: string | null | undefined, max = 220): string | null {
  if (!value) return null;
  const clean = value.replace(/\s+/g, " ").trim();
  if (clean.length <= max) return clean;
  return `${clean.slice(0, max - 1).trimEnd()}…`;
}

function toneFromStatus(status: string | null | undefined): "neutral" | "success" | "warning" | "danger" {
  const normalized = normalizeStatus(status);
  if (normalized === "success") return "success";
  if (normalized === "partial" || normalized === "pending_data" || normalized === "running") return "warning";
  if (normalized === "fail") return "danger";
  return "neutral";
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

function freshnessMeta(value: string | null | undefined): { label: string; detail: string; className: string } {
  const mins = ageMinutes(value);
  if (mins === null) {
    return {
      label: "Unknown",
      detail: "no timestamp",
      className: "border-line bg-elevated text-ink-soft",
    };
  }
  if (mins <= 15) {
    return {
      label: "Fresh",
      detail: `${mins}m old`,
      className: "border-emerald-700/70 bg-emerald-900/20 text-emerald-300",
    };
  }
  if (mins <= 60) {
    return {
      label: "Recent",
      detail: `${mins}m old`,
      className: "border-cyan-700/70 bg-cyan-900/20 text-cyan-300",
    };
  }
  if (mins <= 240) {
    return {
      label: "Aging",
      detail: `${mins}m old`,
      className: "border-amber-700/70 bg-amber-900/20 text-amber-300",
    };
  }
  return {
    label: "Stale",
    detail: `${mins}m old`,
    className: "border-red-700/70 bg-red-900/20 text-red-300",
  };
}

export function OpsConsole({ initialTab = "overview" }: { initialTab?: ConsoleTab }) {
  const [tab, setTab] = useState<ConsoleTab>(initialTab);
  const [agentFilter, setAgentFilter] = useState<string>("all");
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [runModalOpen, setRunModalOpen] = useState(false);
  const [runAgent, setRunAgent] = useState<AgentName>("briefing");
  const [runCadence, setRunCadence] = useState<"daily" | "weekly" | "monthly">("daily");
  const debouncedSearch = useDebouncedValue(search, 300);
  const trigger = useTriggerAgent();

  const health = useQuery({
    queryKey: ["health", "ops-console"],
    queryFn: fetchHealth,
    refetchInterval: 15000,
    staleTime: 15000,
  });
  const runsAll = useQuery({
    queryKey: ["runs", "ops-console", "all"],
    queryFn: () => fetchRuns({ limit: 200 }),
    refetchInterval: 5000,
    staleTime: 5000,
  });
  const runsFiltered = useQuery({
    queryKey: ["runs", "ops-console", "filtered", agentFilter, statusFilter],
    queryFn: () =>
      fetchRuns({
        limit: 200,
        agent_name: agentFilter === "all" ? undefined : agentFilter,
        status: statusFilter === "all" ? undefined : statusFilter,
      }),
    refetchInterval: 5000,
    staleTime: 5000,
  });
  const announcementStats = useQuery({
    queryKey: ["announcement-stats", "ops-console"],
    queryFn: fetchAnnouncementStats,
    refetchInterval: 30000,
    staleTime: 30000,
  });
  const announcementFeed = useQuery({
    queryKey: ["announcements", "ops-console"],
    queryFn: () => fetchAnnouncements({ limit: 250, scope: "all" }),
    refetchInterval: 30000,
    staleTime: 30000,
  });
  const latestDailyReport = useQuery({
    queryKey: ["report", "daily", "ops-console"],
    queryFn: () => fetchLatestReport("daily"),
    refetchInterval: 30000,
    staleTime: 30000,
  });
  const latestWeeklyReport = useQuery({
    queryKey: ["report", "weekly", "ops-console"],
    queryFn: () => fetchLatestReport("weekly"),
    refetchInterval: 30000,
    staleTime: 30000,
  });
  const sentimentDigest = useQuery({
    queryKey: ["sentiment-digest-latest", "ops-console"],
    queryFn: fetchSentimentDigestLatest,
    refetchInterval: 30000,
    staleTime: 30000,
  });
  const patternSummary = useQuery({
    queryKey: ["pattern-summary", "ops-console"],
    queryFn: fetchPatternSummary,
    refetchInterval: 30000,
    staleTime: 30000,
  });
  const archive = useQuery({
    queryKey: ["archive-weekly", "ops-console"],
    queryFn: () => fetchLatestArchive("weekly"),
    refetchInterval: 30000,
    staleTime: 30000,
  });

  const runRowsAll = safeList(runsAll.data?.items);
  const runRowsFiltered = safeList(runsFiltered.data?.items);
  const searchedRuns = useMemo(() => {
    const q = debouncedSearch.trim().toLowerCase();
    if (!q) return runRowsFiltered;
    return runRowsFiltered.filter((row) => {
      const hay = [
        row.run_id,
        row.agent_name,
        row.status,
        row.status_reason,
        row.error_message,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return hay.includes(q);
    });
  }, [debouncedSearch, runRowsFiltered]);

  const pageSize = 12;
  const pageCount = Math.max(1, Math.ceil(searchedRuns.length / pageSize));
  const safePage = Math.min(page, pageCount);
  const pageRows = searchedRuns.slice((safePage - 1) * pageSize, safePage * pageSize);

  const activeRuns = runRowsAll.filter((r) => {
    const s = normalizeStatus(r.status);
    return s === "queued" || s === "running";
  }).length;

  const latestActivity = runRowsAll
    .map((r) => r.finished_at || r.started_at || null)
    .find((v) => !!v) || null;
  const freshnessMins = ageMinutes(latestActivity);
  const fallbackAlerted = safeList(announcementFeed.data?.items).filter((item) => !!item.alerted).length;
  const fallbackTotal = announcementFeed.data?.total ?? safeList(announcementFeed.data?.items).length;
  const alertedEvents = announcementStats.data?.alerted ?? fallbackAlerted;
  const totalTracked = announcementStats.data?.total ?? fallbackTotal;

  const dependencies = Object.entries(health.data?.dependencies || {});
  const healthyDeps = dependencies.filter(([, raw]) => {
    const item = raw as { status?: string };
    const status = normalizeStatus(item?.status);
    return status === "success";
  }).length;
  const healthStatus = normalizeStatus(health.data?.status);
  const healthLabel =
    healthStatus === "success" ? "HEALTHY" :
      healthStatus === "partial" ? "DEGRADED" :
        healthStatus === "fail" ? "ERROR" :
          healthStatus.toUpperCase();
  const healthTone = healthStatus === "success" ? "success" : healthStatus === "partial" ? "warning" : "danger";

  const agentLatest: Array<{ key: AgentName; row: (typeof runRowsAll)[number] | undefined }> = (
    ["briefing", "announcements", "sentiment", "analyst", "archivist", "narrator"] as AgentName[]
  ).map((key) => ({
    key,
    row: runRowsAll.find((r) => (r.agent_name || "").toLowerCase() === key),
  }));

  async function submitRun() {
    const params: Record<string, string | boolean | undefined> = {};
    if (runAgent === "analyst") params.report_type = runCadence === "weekly" ? "weekly" : "daily";
    if (runAgent === "archivist") params.run_type = runCadence === "monthly" ? "monthly" : "weekly";
    await trigger.mutateAsync({ agent: runAgent, params });
    setRunModalOpen(false);
  }

  function renderOverview() {
    return (
      <div className="grid gap-4">
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <StatCard
            label="System Health"
            value={healthLabel}
            hint={`${healthyDeps}/${dependencies.length} dependencies healthy`}
            tone={healthTone}
          />
          <StatCard label="Active Runs" value={activeRuns} hint="queued + running" tone={activeRuns > 0 ? "brand" : "neutral"} />
          <StatCard
            label="Data Freshness"
            value={freshnessMins === null ? "-" : `${freshnessMins}m`}
            hint={latestActivity ? `latest ${fmtDateTime(latestActivity)}` : "no run activity"}
            tone={freshnessMins !== null && freshnessMins <= 60 ? "success" : "warning"}
          />
          <StatCard
            label="Alerted Events"
            value={fmtNumber(alertedEvents)}
            hint={`Total tracked ${fmtNumber(totalTracked)}`}
            tone="warning"
          />
        </div>

        <div className="grid gap-4 xl:grid-cols-2">
          <div className="min-w-0"><ChainHealthWidget /></div>
          <Panel className="min-w-0" title="Execution Snapshot">
            {runsAll.isLoading ? "Loading..." : runsAll.isError ? "Failed to load runs." : (
              <div className="space-y-2 text-sm">
                {safeList(runsAll.data?.items).slice(0, 6).map((r) => (
                  <div key={r.run_id} className="grid grid-cols-[1fr_auto] items-center rounded-lg border border-line bg-panel-soft px-3 py-2">
                    <div>
                      <div className="text-ink">{humanize(resolveAgentName(r))}</div>
                      <div className="text-xs text-ink-faint">{fmtDateTime(r.finished_at || r.started_at)}</div>
                    </div>
                    <Badge value={normalizeStatus(r.status)} />
                  </div>
                ))}
              </div>
            )}
          </Panel>
        </div>
      </div>
    );
  }

  function renderAgents() {
    return (
      <div className="grid gap-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-ink-soft">Agent Performance</h3>
          <Button variant="secondary" onClick={() => setRunModalOpen(true)}>Trigger Run</Button>
        </div>
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {agentLatest.map(({ key, row }) => (
            <Panel key={key} title={AGENT_LABELS[key]}>
              {row ? (
                <div className="space-y-2 text-sm">
                  <div className="flex items-center justify-between">
                    <span className="text-muted">Status</span>
                    <Badge value={normalizeStatus(row.status)} />
                  </div>
                  <div className="flex items-center justify-between text-ink-soft">
                    <span>Processed</span>
                    <span>{row.records_processed ?? 0}</span>
                  </div>
                  <div className="flex items-center justify-between text-ink-soft">
                    <span>New</span>
                    <span>{row.records_new ?? 0}</span>
                  </div>
                  <div className="flex items-center justify-between text-ink-soft">
                    <span>Errors</span>
                    <span>{row.errors_count ?? 0}</span>
                  </div>
                  <div className="text-xs text-ink-faint">{fmtDateTime(row.finished_at || row.started_at)}</div>
                </div>
              ) : (
                <div className="text-sm text-ink-faint">No runs yet.</div>
              )}
            </Panel>
          ))}
        </div>
      </div>
    );
  }

  function renderInsights() {
    const dailySummary = summaryText(
      latestDailyReport.data?.item?.human_summary_v2,
      latestDailyReport.data?.item?.human_summary,
    );
    const weeklySummary = summaryText(
      latestWeeklyReport.data?.item?.human_summary_v2,
      latestWeeklyReport.data?.item?.human_summary,
    );
    const sentimentSummary = summaryText(
      sentimentDigest.data?.item?.human_summary_v2,
      sentimentDigest.data?.item?.human_summary,
    );
    const archiveLegacy =
      archive.data?.item?.human_summary ||
      (archive.data?.item?.summary && typeof archive.data.item.summary === "object"
        ? (archive.data.item.summary.human_summary as { headline?: string; plain_summary?: string } | undefined)
        : undefined);
    const archiveSummary = summaryText(archive.data?.item?.human_summary_v2, archiveLegacy);

    const insightCards = [
      {
        key: "daily",
        title: "Daily Market Insight",
        status: latestDailyReport.data?.item?.status,
        generatedAt: latestDailyReport.data?.item?.generated_at,
        headline: dailySummary.headline,
        summary: dailySummary.plain,
        drivers: dailySummary.drivers,
      },
      {
        key: "sentiment",
        title: "Sentiment Insight",
        status: sentimentDigest.data?.item?.status,
        generatedAt: sentimentDigest.data?.item?.generated_at,
        headline: sentimentSummary.headline,
        summary: sentimentSummary.plain,
        drivers: sentimentSummary.drivers,
      },
      {
        key: "weekly",
        title: "Weekly Analyst Insight",
        status: latestWeeklyReport.data?.item?.status,
        generatedAt: latestWeeklyReport.data?.item?.generated_at,
        headline: weeklySummary.headline,
        summary: weeklySummary.plain,
        drivers: weeklySummary.drivers,
      },
      {
        key: "archive",
        title: "Archive Insight",
        status: archive.data?.item?.status,
        generatedAt: archive.data?.item?.updated_at || archive.data?.item?.created_at,
        headline: archiveSummary.headline,
        summary: archiveSummary.plain,
        drivers: archiveSummary.drivers,
      },
    ] as const;

    return (
      <div className="grid gap-4">
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          <StatCard
            label="Daily Report"
            value={latestDailyReport.data?.item?.period_key || "-"}
            hint={humanize(normalizeStatus(latestDailyReport.data?.item?.status))}
            tone={toneFromStatus(latestDailyReport.data?.item?.status)}
          />
          <StatCard
            label="Weekly Sentiment"
            value={sentimentDigest.data?.item?.week_start || "-"}
            hint={humanize(normalizeStatus(sentimentDigest.data?.item?.status))}
            tone={toneFromStatus(sentimentDigest.data?.item?.status)}
          />
          <StatCard
            label="Active Patterns"
            value={fmtNumber(patternSummary.data?.active_count)}
            hint={`Confirmed ${fmtNumber(patternSummary.data?.confirmed_count)}`}
            tone="warning"
          />
          <StatCard
            label="Archive"
            value={archive.data?.item?.period_key || "-"}
            hint={humanize(normalizeStatus(archive.data?.item?.status))}
            tone={toneFromStatus(archive.data?.item?.status)}
          />
        </div>

        <Panel className="min-w-0 overflow-hidden" title="Insight Briefs">
          {(latestDailyReport.isLoading || latestWeeklyReport.isLoading || sentimentDigest.isLoading || archive.isLoading) ? (
            <div className="text-sm text-muted">Loading latest insight summaries...</div>
          ) : (latestDailyReport.isError || latestWeeklyReport.isError || sentimentDigest.isError || archive.isError) ? (
            <div className="text-sm text-red-300">Some insight blocks could not be loaded. Retry shortly.</div>
          ) : (
            <div className="grid gap-3 lg:grid-cols-2">
              {insightCards.map((card) => {
                const status = normalizeStatus(card.status || "pending_data");
                const freshness = freshnessMeta(card.generatedAt || null);
                return (
                  <article key={card.key} className="rounded-xl border border-line bg-panel-soft p-4">
                    <div className="mb-3 flex items-start justify-between gap-2">
                      <div>
                        <h3 className="text-sm font-semibold text-ink">{card.title}</h3>
                        <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-ink-faint">
                          <span>As of: {fmtDateTime(card.generatedAt || null)}</span>
                          <span className={`inline-flex rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${freshness.className}`}>
                            {freshness.label}
                          </span>
                          <span>{freshness.detail}</span>
                        </div>
                      </div>
                      <Badge value={status} />
                    </div>
                    <p className="mb-2 text-sm font-medium text-ink">
                      {card.headline || "No headline available yet."}
                    </p>
                    <p className="text-sm text-muted">
                      {truncateText(card.summary, 190) || "Insight summary is still being prepared."}
                    </p>
                    <details className="mt-3 rounded-lg border border-line bg-hover px-3 py-2">
                      <summary className="cursor-pointer select-none text-xs font-semibold uppercase tracking-wide text-emerald-300">
                        View detail
                      </summary>
                      <div className="mt-2 space-y-2 text-sm text-ink-soft">
                        <p>{card.summary || "No expanded summary available for this block yet."}</p>
                        {card.drivers.length > 0 ? (
                          <ul className="list-disc space-y-1 pl-5 text-muted">
                            {card.drivers.slice(0, 4).map((driver) => (
                              <li key={driver}>{driver}</li>
                            ))}
                          </ul>
                        ) : (
                          <p className="text-ink-faint">No key drivers captured for this insight block.</p>
                        )}
                      </div>
                    </details>
                  </article>
                );
              })}
            </div>
          )}
        </Panel>
      </div>
    );
  }

  function renderLogs() {
    return (
      <div className="grid gap-4">
        <Panel className="min-w-0 overflow-hidden" title="Filters">
          <div className="grid gap-3 grid-cols-2 lg:grid-cols-[220px_220px_1fr_auto]">
            <div className="space-y-1">
              <label className="text-xs text-ink-faint">Agent</label>
              <Select
                value={agentFilter}
                onChange={(e) => {
                  setAgentFilter(e.target.value);
                  setPage(1);
                }}
              >
                <option value="all">All Agents</option>
                <option value="briefing">Agent A</option>
                <option value="announcements">Agent B</option>
                <option value="sentiment">Agent C</option>
                <option value="analyst">Agent D</option>
                <option value="archivist">Agent E</option>
                <option value="narrator">Agent F</option>
              </Select>
            </div>
            <div className="space-y-1">
              <label className="text-xs text-ink-faint">Status</label>
              <Select
                value={statusFilter}
                onChange={(e) => {
                  setStatusFilter(e.target.value);
                  setPage(1);
                }}
              >
                <option value="all">All Statuses</option>
                <option value="queued">queued</option>
                <option value="running">running</option>
                <option value="success">success</option>
                <option value="partial">partial</option>
                <option value="fail">fail</option>
                <option value="stale_timeout">stale timeout</option>
              </Select>
            </div>
            <div className="space-y-1">
              <label className="text-xs text-ink-faint">Search</label>
              <Input
                placeholder="Run ID, reason, or error"
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                  setPage(1);
                }}
              />
            </div>
            <div className="flex items-end justify-end gap-2">
              <Button variant="ghost" onClick={() => setPage((p) => Math.max(1, p - 1))} disabled={safePage <= 1}>
                Prev
              </Button>
              <span className="min-w-12 text-center text-xs text-ink-faint">{safePage}/{pageCount}</span>
              <Button variant="ghost" onClick={() => setPage((p) => Math.min(pageCount, p + 1))} disabled={safePage >= pageCount}>
                Next
              </Button>
            </div>
          </div>
        </Panel>
        <Panel className="min-w-0 overflow-hidden" title="Execution Logs">
          {runsFiltered.isLoading ? (
            "Loading..."
          ) : runsFiltered.isError ? (
            "Failed to load execution logs."
          ) : pageRows.length === 0 ? (
            <div className="text-sm text-ink-faint">No runs found for selected filters.</div>
          ) : (
            <div className="overflow-x-auto rounded-xl border border-line">
              <table className="w-full min-w-[640px] text-sm">
                <thead className="bg-inset">
                  <tr className="text-left text-xs uppercase tracking-wide text-ink-faint">
                    <th className="px-3 py-3">Agent</th>
                    <th className="px-2 py-3">Status</th>
                    <th className="px-2 py-3">Started</th>
                    <th className="px-2 py-3">Duration</th>
                    <th className="px-2 py-3">Processed</th>
                    <th className="px-2 py-3">New</th>
                    <th className="px-2 py-3">Errors</th>
                    <th className="px-3 py-3">Outcome</th>
                  </tr>
                </thead>
                <tbody>
                  {pageRows.map((row) => (
                    <tr key={row.run_id} className="border-t border-line hover:bg-hover">
                      <td className="px-3 py-3 text-ink">{humanize(row.agent_name)}</td>
                      <td className="px-2 py-3"><Badge value={normalizeStatus(row.status)} /></td>
                      <td className="px-2 py-3 text-muted">{fmtDateTime(row.started_at)}</td>
                      <td className="px-2 py-3 text-ink-soft">{durationLabel(row.started_at, row.finished_at)}</td>
                      <td className="px-2 py-3 text-ink-soft">{row.records_processed ?? 0}</td>
                      <td className="px-2 py-3 text-ink-soft">{row.records_new ?? 0}</td>
                      <td className="px-2 py-3 text-ink-soft">{row.errors_count ?? 0}</td>
                      <td className="max-w-[320px] px-3 py-3 text-muted" title={row.status_reason || row.error_message || "-"}>
                        <span className="truncate">{humanize(row.status_reason || row.error_message || "-")}</span>
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

  return (
    <div className="grid gap-4">
      <Panel title="Operations Console">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Tabs items={TAB_ITEMS} activeKey={tab} onChange={(key) => setTab(key as ConsoleTab)} />
          <div className="flex items-center gap-2">
            <Badge value={normalizeStatus(health.data?.status)} />
            <Button variant="secondary" onClick={() => setRunModalOpen(true)}>New Run</Button>
          </div>
        </div>
      </Panel>

      {tab === "overview" ? renderOverview() : null}
      {tab === "agents" ? renderAgents() : null}
      {tab === "insights" ? renderInsights() : null}
      {tab === "logs" ? renderLogs() : null}

      <Modal
        open={runModalOpen}
        title="Trigger Agent Run"
        onClose={() => setRunModalOpen(false)}
        footer={(
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setRunModalOpen(false)}>Cancel</Button>
            <Button variant="primary" loading={trigger.isPending} onClick={submitRun}>Run</Button>
          </div>
        )}
      >
        <div className="grid gap-3">
          <div>
            <label className="mb-1 block text-xs uppercase tracking-wide text-ink-faint">Agent</label>
            <Select value={runAgent} onChange={(e) => setRunAgent(e.target.value as AgentName)}>
              <option value="briefing">Agent A · Collector</option>
              <option value="announcements">Agent B · Cleaner</option>
              <option value="sentiment">Agent C · Processor</option>
              <option value="analyst">Agent D · Orchestrator</option>
              <option value="archivist">Agent E · Publisher</option>
              <option value="narrator">Agent F · Narrator</option>
            </Select>
          </div>
          {(runAgent === "analyst" || runAgent === "archivist") ? (
            <div>
              <label className="mb-1 block text-xs uppercase tracking-wide text-ink-faint">Cadence</label>
              <Select
                value={runCadence}
                onChange={(e) => setRunCadence(e.target.value as "daily" | "weekly" | "monthly")}
              >
                {runAgent === "analyst" ? (
                  <>
                    <option value="daily">daily</option>
                    <option value="weekly">weekly</option>
                  </>
                ) : (
                  <>
                    <option value="weekly">weekly</option>
                    <option value="monthly">monthly</option>
                  </>
                )}
              </Select>
            </div>
          ) : null}
          {trigger.isError ? (
            <div className="rounded-lg border border-red-800 bg-red-950/30 px-3 py-2 text-sm text-red-300">
              Run trigger failed. Please retry.
            </div>
          ) : null}
          {trigger.data?.run_id ? (
            <div className="rounded-lg border border-line bg-elevated px-3 py-2 text-xs text-muted">
              Last queued run: {trigger.data.run_id}
            </div>
          ) : null}
        </div>
      </Modal>
    </div>
  );
}
