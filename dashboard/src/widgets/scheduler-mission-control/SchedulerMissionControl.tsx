"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";

import {
  dispatchScheduleNow,
  fetchSchedulerImpact,
  rebuildNarrator,
  retryRun,
} from "@/entities/scheduler/monitor.api";
import { triggerAgent } from "@/entities/run/api";
import { useSchedulerMonitorLive } from "@/features/scheduler/useSchedulerMonitorLive";
import { Badge } from "@/shared/ui/Badge";
import { Button } from "@/shared/ui/Button";
import { Panel } from "@/shared/ui/Panel";
import { Skeleton } from "@/shared/ui/Skeleton";

function fmtEAT(value: string | null | undefined): string {
  if (!value) return "-";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return value;
  return new Intl.DateTimeFormat("en-GB", {
    timeZone: "Africa/Nairobi",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(d);
}

function fmtUtcTooltip(value: string | null | undefined): string {
  if (!value) return "UTC -";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return `UTC ${value}`;
  return `UTC ${d.toISOString().replace("T", " ").replace(".000", "")}`;
}

function fmtEta(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return "-";
  const safe = Math.max(0, seconds);
  if (safe < 60) return `${safe}s`;
  const mins = Math.floor(safe / 60);
  const secs = safe % 60;
  if (mins < 60) return `${mins}m ${secs}s`;
  const hrs = Math.floor(mins / 60);
  const rem = mins % 60;
  return `${hrs}h ${rem}m`;
}

function clip(value: string | null | undefined, max = 92): string {
  if (!value) return "-";
  const clean = value.replace(/\s+/g, " ").trim();
  if (clean.length <= max) return clean;
  return `${clean.slice(0, max - 1).trimEnd()}…`;
}

function statusTone(status: string | null | undefined): "neutral" | "success" | "warning" | "danger" | "brand" {
  const normalized = (status || "").toLowerCase();
  if (normalized.includes("success") || normalized === "ok") return "success";
  if (normalized.includes("running") || normalized.includes("active")) return "brand";
  if (normalized.includes("partial") || normalized.includes("warn") || normalized.includes("blocked") || normalized.includes("degraded")) return "warning";
  if (normalized.includes("fail") || normalized.includes("error")) return "danger";
  return "neutral";
}

function statusBadgeClass(status: string | null | undefined): string {
  const normalized = (status || "").toLowerCase();
  if (normalized.includes("brand")) {
    return "border-cyan-700/70 bg-cyan-500/10 text-cyan-300";
  }
  if (normalized.includes("success") || normalized === "ok" || normalized.includes("active")) {
    return "border-emerald-700/70 bg-emerald-500/10 text-emerald-300";
  }
  if (normalized.includes("partial") || normalized.includes("warn") || normalized.includes("blocked") || normalized.includes("degraded")) {
    return "border-amber-700/70 bg-amber-500/10 text-amber-300";
  }
  if (normalized.includes("fail") || normalized.includes("error")) {
    return "border-red-700/70 bg-red-500/10 text-red-300";
  }
  return "border-line bg-elevated text-ink-soft";
}

function laneIntensityClass(value: number): string {
  if (value >= 4) return "bg-cyan-400";
  if (value >= 2) return "bg-cyan-400/70";
  if (value >= 1) return "bg-cyan-400/35";
  return "bg-elevated";
}

function sparklinePath(values: number[], width = 320, height = 88): string {
  if (!values.length) return "";
  const max = Math.max(...values, 1);
  const min = Math.min(...values, 0);
  const span = Math.max(1, max - min);
  const step = values.length > 1 ? width / (values.length - 1) : width;

  return values
    .map((value, idx) => {
      const x = idx * step;
      const y = height - ((value - min) / span) * height;
      return `${idx === 0 ? "M" : "L"}${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(" ");
}

const PIPELINE_ORDER = ["A", "B", "C", "D", "E", "F", "EMAIL"];
const IMPACT_AGENTS = ["briefing", "announcements", "sentiment", "analyst", "archivist", "narrator"] as const;
const AGENT_ADMIN_ORDER = ["briefing", "announcements", "sentiment", "analyst", "archivist", "narrator"] as const;

const AGENT_ADMIN_LABELS: Record<(typeof AGENT_ADMIN_ORDER)[number], string> = {
  briefing: "Agent A",
  announcements: "Agent B",
  sentiment: "Agent C",
  analyst: "Agent D",
  archivist: "Agent E",
  narrator: "Agent F",
};

const AGENT_ADMIN_PARAMS: Record<(typeof AGENT_ADMIN_ORDER)[number], Record<string, string | boolean | undefined>> = {
  briefing: {},
  announcements: {},
  sentiment: {},
  analyst: { report_type: "daily" },
  archivist: { run_type: "weekly" },
  narrator: {},
};

const RUN_FULL_CHAIN_CONFIRM_TEXT = "RUN FULL CHAIN";

function getSuperAdminAllowList(): Set<string> {
  const raw = (process.env.NEXT_PUBLIC_SUPER_ADMIN_USERS || "operator").trim();
  const values = raw
    .split(",")
    .map((value) => value.trim().toLowerCase())
    .filter(Boolean);
  return new Set(values);
}

export function SchedulerMissionControl() {
  const live = useSchedulerMonitorLive();
  const snapshot = live.snapshot;

  const [impactAgent, setImpactAgent] = useState<(typeof IMPACT_AGENTS)[number]>("analyst");
  const [controlMessage, setControlMessage] = useState<string | null>(null);
  const [adminBusy, setAdminBusy] = useState(false);
  const [showRunAllModal, setShowRunAllModal] = useState(false);
  const [runAllConfirmInput, setRunAllConfirmInput] = useState("");

  const authMeQuery = useQuery({
    queryKey: ["auth-me"],
    queryFn: async () => {
      const response = await fetch("/api/auth/me", { credentials: "include", cache: "no-store" });
      if (!response.ok) throw new Error("auth_unavailable");
      return response.json() as Promise<{ user?: { username?: string } }>;
    },
    staleTime: 60_000,
    refetchInterval: 60_000,
    retry: 1,
  });

  const impactQuery = useQuery({
    queryKey: ["scheduler-impact", impactAgent],
    queryFn: () => fetchSchedulerImpact(impactAgent),
    enabled: Boolean(impactAgent),
    refetchInterval: 10000,
    staleTime: 5000,
  });

  const dispatchMutation = useMutation({
    mutationFn: async (scheduleKey: string) => dispatchScheduleNow(scheduleKey),
    onSuccess: (_, scheduleKey) => setControlMessage(`Dispatch accepted for ${scheduleKey}`),
    onError: (err) => setControlMessage(err instanceof Error ? err.message : "Dispatch failed"),
  });

  const retryMutation = useMutation({
    mutationFn: async (runId: string) => retryRun(runId),
    onSuccess: (_, runId) => setControlMessage(`Retry queued for ${runId.slice(0, 8)}…`),
    onError: (err) => setControlMessage(err instanceof Error ? err.message : "Retry failed"),
  });

  const narratorMutation = useMutation({
    mutationFn: async () => rebuildNarrator(true),
    onSuccess: () => setControlMessage("Narrator rebuild triggered"),
    onError: (err) => setControlMessage(err instanceof Error ? err.message : "Narrator rebuild failed"),
  });

  const runAgentMutation = useMutation({
    mutationFn: async (payload: { agent: (typeof AGENT_ADMIN_ORDER)[number] }) =>
      triggerAgent(payload.agent, AGENT_ADMIN_PARAMS[payload.agent]),
    onSuccess: (res, payload) => {
      setControlMessage(`${AGENT_ADMIN_LABELS[payload.agent]} execution queued (${res.run_id.slice(0, 8)}…)`);
    },
    onError: (err, payload) => {
      const prefix = payload ? `${AGENT_ADMIN_LABELS[payload.agent]} failed` : "Agent trigger failed";
      setControlMessage(err instanceof Error ? `${prefix}: ${err.message}` : prefix);
    },
  });

  const transportLabel = live.transport === "ws" ? "WS Live" : live.transport === "polling" ? "Polling Fallback" : "Connecting";
  const superAdminAllowList = useMemo(() => getSuperAdminAllowList(), []);
  const currentUsername = (authMeQuery.data?.user?.username || "").trim().toLowerCase();
  const isSuperAdmin = Boolean(currentUsername) && superAdminAllowList.has(currentUsername);

  const scheduleKeys = useMemo(() => {
    const keys = new Set<string>();
    (snapshot?.future.items || []).forEach((item) => {
      if (item.schedule_key) keys.add(item.schedule_key);
    });
    return Array.from(keys).slice(0, 8);
  }, [snapshot?.future.items]);

  const failedRuns = useMemo(() => {
    return (snapshot?.past.items || []).filter((item) => item.status === "fail" || item.status === "partial").slice(0, 6);
  }, [snapshot?.past.items]);

  const futureRuns = useMemo(() => (snapshot?.future.items || []).slice(0, 12), [snapshot?.future.items]);
  const recentRuns = useMemo(() => (snapshot?.past.items || []).slice(0, 10), [snapshot?.past.items]);

  const nodeById = useMemo(() => {
    const m = new Map<string, { id: string; label: string; status: string }>();
    (snapshot?.pipeline.nodes || []).forEach((node) => m.set(node.id, node));
    return m;
  }, [snapshot?.pipeline.nodes]);

  const agentNameToLabel = useMemo(() => {
    const m = new Map<string, string>();
    (snapshot?.pipeline.nodes || []).forEach((node) => m.set(node.agent_name, node.label));
    return m;
  }, [snapshot?.pipeline.nodes]);

  const linkByPair = useMemo(() => {
    const m = new Map<string, { from: string; to: string; state: string }>();
    (snapshot?.pipeline.links || []).forEach((link) => m.set(`${link.from}->${link.to}`, link));
    return m;
  }, [snapshot?.pipeline.links]);

  const impactRows = useMemo(() => {
    const items = impactQuery.data?.items || snapshot?.impact.items || [];
    return items.filter((row) => row.agent_name !== impactAgent).slice(0, 6);
  }, [impactAgent, impactQuery.data?.items, snapshot?.impact.items]);

  const timelineSpark = useMemo(() => {
    if (!snapshot?.heatmap.rows?.length) return "";
    const cols = snapshot.heatmap.rows[0]?.cells?.length || 0;
    if (!cols) return "";
    const totals = Array.from({ length: cols }, (_, idx) =>
      snapshot.heatmap.rows.reduce((sum, row) => sum + (row.cells[idx] || 0), 0),
    );
    return sparklinePath(totals, 360, 96);
  }, [snapshot?.heatmap.rows]);

  const commandPulse = useMemo(() => {
    if (!snapshot) return [];
    return [
      {
        label: "Scheduler",
        value: snapshot.status.scheduler_status.toUpperCase(),
        hint: `tick ${snapshot.status.loop_interval_seconds}s`,
        tone: statusTone(snapshot.status.scheduler_status),
      },
      {
        label: "Queue",
        value: `${snapshot.metrics.active_runs} active / ${snapshot.metrics.queued_jobs} queued`,
        hint: `${snapshot.metrics.blocked_jobs} blocked`,
        tone: snapshot.metrics.blocked_jobs > 0 ? "warning" : snapshot.metrics.active_runs > 0 ? "brand" : "success",
      },
      {
        label: "Next Orchestration",
        value: fmtEta(snapshot.metrics.next_run_eta_seconds),
        hint: `${snapshot.status.schedules_loaded} schedules loaded`,
        tone: "neutral",
      },
      {
        label: "Email Dispatch",
        value: fmtEta(snapshot.metrics.next_email_eta_seconds),
        hint: `${snapshot.email.sent_count_recent} sent · ${snapshot.email.failure_count_recent} failed`,
        tone: snapshot.email.failure_count_recent > 0 ? "warning" : "success",
      },
      {
        label: "LLM Interactions",
        value: `${snapshot.metrics.llm_active_jobs} running`,
        hint: "A/B/C/D/F capabilities",
        tone: snapshot.metrics.llm_active_jobs > 0 ? "brand" : "neutral",
      },
    ] as const;
  }, [snapshot]);

  const emailSendHistory = useMemo(() => {
    return (snapshot?.past.items || []).filter((item) => item.email_sent).slice(0, 12);
  }, [snapshot?.past.items]);

  const lastEmailSent = emailSendHistory[0] || null;
  const nextEmailByAgent = useMemo(() => (snapshot?.email.next_email_by_agent || []).slice(0, 8), [snapshot?.email.next_email_by_agent]);
  const nextEmailDispatches = useMemo(
    () =>
      [...(snapshot?.email.next_validation_dispatches || [])].sort((a, b) =>
        String(a.next_run_at_utc || "").localeCompare(String(b.next_run_at_utc || "")),
      ),
    [snapshot?.email.next_validation_dispatches],
  );
  const nextExactEmail = nextEmailByAgent[0] || null;

  const runAllAgentsChain = async () => {
    if (!isSuperAdmin) {
      setControlMessage("Super-admin role required for full-chain execution.");
      return;
    }
    if (runAllConfirmInput.trim() !== RUN_FULL_CHAIN_CONFIRM_TEXT) {
      setControlMessage("Type the confirmation phrase to execute full chain.");
      return;
    }
    try {
      setAdminBusy(true);
      for (const agent of AGENT_ADMIN_ORDER) {
        await runAgentMutation.mutateAsync({ agent });
      }
      setControlMessage("Full A→F admin execution chain queued.");
      setShowRunAllModal(false);
      setRunAllConfirmInput("");
    } catch (err) {
      setControlMessage(err instanceof Error ? err.message : "Failed to queue full A→F chain");
    } finally {
      setAdminBusy(false);
    }
  };

  return (
    <div className="space-y-4">
      <Panel>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h1 className="text-lg font-semibold text-ink">Scheduler Mission Control</h1>
            <p className="text-sm text-muted">Operational analytics + control deck across A-F orchestration, dependencies, retries, and email dispatch.</p>
          </div>
          <div className="flex items-center gap-2 text-xs">
            <span className={`rounded border px-2 py-1 ${live.transport === "ws" ? "border-emerald-700 text-emerald-300" : "border-amber-700 text-amber-300"}`}>
              {transportLabel}
            </span>
            <span className="text-ink-faint" title={fmtUtcTooltip(snapshot?.time.now_utc || snapshot?.generated_at || null)}>
              EAT {fmtEAT(snapshot?.time.now_eat || snapshot?.generated_at || null)}
            </span>
          </div>
        </div>
      </Panel>

      {live.isLoading ? (
        <Panel title="Loading Mission Telemetry">
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
            {Array.from({ length: 5 }).map((_, idx) => (
              <Skeleton key={idx} className="h-24 w-full bg-elevated" />
            ))}
          </div>
        </Panel>
      ) : !snapshot ? (
        <Panel title="Scheduler Mission Control">
          <p className="text-sm text-muted">No telemetry available yet.</p>
          {live.error ? <p className="mt-2 text-sm text-red-300">{live.error}</p> : null}
        </Panel>
      ) : (
        <>
          <div className="grid gap-3 grid-cols-2 md:grid-cols-3 xl:grid-cols-5">
            {commandPulse.map((item) => (
              <div key={item.label} className="rounded-xl border border-line bg-panel-soft p-3">
                <div className="text-[11px] uppercase tracking-[0.14em] text-ink-faint">{item.label}</div>
                <div className="mt-2 text-sm font-semibold text-ink">{item.value}</div>
                <div className="mt-1 text-xs text-ink-faint">{item.hint}</div>
                <div className="mt-2">
                  <span className={`inline-flex rounded-full border px-2 py-0.5 text-[10px] uppercase ${statusBadgeClass(item.tone)}`}>{item.tone}</span>
                </div>
              </div>
            ))}
          </div>

          <div className="flex flex-col gap-4 2xl:flex-row">
            <div className="min-w-0 2xl:flex-[1.45]">
              <Panel title="Runtime Analytics Radar">
                <div className="space-y-4">
                  <div className="rounded-xl border border-line bg-panel-soft p-3">
                    <div className="mb-2 flex items-center justify-between text-xs">
                      <span className="uppercase tracking-[0.14em] text-ink-faint">24h Throughput Curve</span>
                      <span className="text-ink-faint">all agents combined</span>
                    </div>
                    <svg viewBox="0 0 370 110" className="h-24 w-full">
                      <defs>
                        <linearGradient id="throughputGrad" x1="0" x2="0" y1="0" y2="1">
                          <stop offset="0%" stopColor="#22d3ee" stopOpacity="0.45" />
                          <stop offset="100%" stopColor="#22d3ee" stopOpacity="0" />
                        </linearGradient>
                      </defs>
                      <path d="M0,109 L0,109" fill="none" stroke="none" />
                      {timelineSpark ? (
                        <>
                          <path d={`${timelineSpark} L360,96 L0,96 Z`} fill="url(#throughputGrad)" />
                          <path d={timelineSpark} fill="none" stroke="#22d3ee" strokeWidth="2.3" />
                        </>
                      ) : null}
                    </svg>
                  </div>

                  <div className="space-y-2">
                    <div className="text-[11px] uppercase tracking-[0.14em] text-ink-faint">Execution Lanes</div>
                    {(snapshot.heatmap.rows || []).map((row) => (
                      <div key={row.agent_name} className="grid grid-cols-[100px_1fr] sm:grid-cols-[150px_1fr] items-center gap-3">
                        <div className="text-xs text-ink-soft">{row.label}</div>
                        <div className="grid grid-cols-12 gap-1 rounded-lg border border-line bg-panel-soft p-2">
                          {row.cells.slice(-12).map((count, idx) => (
                            <div
                              key={`${row.agent_name}-${idx}`}
                              className={`h-3 rounded ${laneIntensityClass(count)}`}
                              title={`${row.label}: ${count} runs`}
                            />
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>

                  <div className="grid gap-2 md:grid-cols-2">
                    <div className="rounded-xl border border-line bg-panel-soft p-3">
                      <div className="text-[11px] uppercase tracking-[0.14em] text-ink-faint">Connectivity</div>
                      <div className="mt-2 text-sm font-semibold text-ink">{snapshot.health.agent_connectivity.healthy_agents}/{snapshot.health.agent_connectivity.total_agents} healthy</div>
                      <div className="mt-1 text-xs text-muted">status: {snapshot.health.agent_connectivity.status}</div>
                    </div>
                    <div className="rounded-xl border border-line bg-panel-soft p-3">
                      <div className="text-[11px] uppercase tracking-[0.14em] text-ink-faint">Latency</div>
                      <div className="mt-2 text-sm font-semibold text-ink">p95 {snapshot.health.pipeline_latency.p95_seconds}s</div>
                      <div className="mt-1 text-xs text-muted">p50 {snapshot.health.pipeline_latency.p50_seconds}s</div>
                    </div>
                  </div>
                </div>
              </Panel>
            </div>

            <div className="min-w-0 2xl:flex-1">
              <Panel title="Control Deck">
                <div className="space-y-4">
                  <div>
                    <div className="mb-2 flex items-center justify-between gap-2">
                      <span className="text-[11px] uppercase tracking-[0.14em] text-ink-faint">Admin Execute (A-F)</span>
                      <span className={`rounded-full border px-2 py-0.5 text-[10px] uppercase ${isSuperAdmin ? "border-emerald-700/70 bg-emerald-500/10 text-emerald-300" : "border-line text-muted"}`}>
                        {isSuperAdmin ? "super-admin" : "read-only"}
                      </span>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {AGENT_ADMIN_ORDER.map((agent) => (
                        <button
                          key={agent}
                          type="button"
                          className="rounded-lg border border-line bg-panel-soft px-3 py-2 text-xs text-ink hover:border-cyan-600/70"
                          onClick={() => runAgentMutation.mutate({ agent })}
                          disabled={runAgentMutation.isPending || adminBusy}
                        >
                          {AGENT_ADMIN_LABELS[agent]}
                        </button>
                      ))}
                      <button
                        type="button"
                        className="rounded-lg border border-cyan-700 bg-cyan-500/10 px-3 py-2 text-xs text-cyan-200 hover:bg-cyan-500/20 disabled:cursor-not-allowed disabled:opacity-50"
                        onClick={() => {
                          if (!isSuperAdmin) {
                            setControlMessage("Super-admin role required for full-chain execution.");
                            return;
                          }
                          setShowRunAllModal(true);
                        }}
                        disabled={adminBusy || runAgentMutation.isPending}
                      >
                        Run Full Chain
                      </button>
                    </div>
                    {!isSuperAdmin ? (
                      <p className="mt-2 text-[11px] text-amber-300">
                        Logged in as {currentUsername || "unknown"}; full-chain control requires super-admin allow list.
                      </p>
                    ) : null}
                  </div>

                  <div>
                    <div className="mb-2 text-[11px] uppercase tracking-[0.14em] text-ink-faint">Quick Dispatch</div>
                    <div className="grid max-h-[170px] gap-2 overflow-auto pr-1">
                      {scheduleKeys.length ? scheduleKeys.map((key) => (
                        <button
                          key={key}
                          type="button"
                          className="flex items-center justify-between rounded-lg border border-line bg-panel-soft px-3 py-2 text-left text-xs hover:border-cyan-600/70"
                          onClick={() => dispatchMutation.mutate(key)}
                          disabled={dispatchMutation.isPending}
                        >
                          <span className="text-ink">{key}</span>
                          <span className="text-cyan-300">Dispatch</span>
                        </button>
                      )) : <p className="text-xs text-ink-faint">No schedule keys available.</p>}
                    </div>
                  </div>

                  <div>
                    <div className="mb-2 text-[11px] uppercase tracking-[0.14em] text-ink-faint">Retry Queue (failed/partial)</div>
                    <div className="grid max-h-[180px] gap-2 overflow-auto pr-1">
                      {failedRuns.length ? failedRuns.map((run) => (
                        <button
                          key={run.run_id}
                          type="button"
                          className="rounded-lg border border-amber-700/40 bg-amber-950/20 px-3 py-2 text-left hover:border-amber-600"
                          onClick={() => retryMutation.mutate(run.run_id)}
                          disabled={retryMutation.isPending}
                        >
                          <div className="flex items-center justify-between gap-2 text-xs">
                            <span className="font-medium text-amber-200">{run.agent_label}</span>
                            <Badge value={run.status} />
                          </div>
                          <div className="mt-1 text-[11px] text-amber-300" title={fmtUtcTooltip(run.finished_at || run.started_at || null)}>
                            {fmtEAT(run.finished_at || run.started_at || null)} · {clip(run.status_reason, 62)}
                          </div>
                        </button>
                      )) : <p className="text-xs text-ink-faint">No failed runs in recent history.</p>}
                    </div>
                  </div>

                  <div className="rounded-xl border border-line bg-panel-soft p-3">
                    <div className="text-[11px] uppercase tracking-[0.14em] text-ink-faint">Narrator Control</div>
                    <div className="mt-2 flex items-center justify-between gap-2">
                      <span className="text-xs text-ink-soft">Force Agent F rebuild cycle</span>
                      <Button variant="ghost" loading={narratorMutation.isPending} onClick={() => narratorMutation.mutate()}>
                        Rebuild
                      </Button>
                    </div>
                  </div>

                  {controlMessage ? (
                    <div className="rounded border border-line bg-elevated px-3 py-2 text-xs text-ink-soft">
                      {controlMessage}
                    </div>
                  ) : null}
                </div>
              </Panel>
            </div>
          </div>

          <div className="flex flex-col gap-4 2xl:flex-row">
            <div className="min-w-0 2xl:flex-1">
              <Panel title="Pipeline Flow Graph">
                <div className="space-y-4">
                  <div className="flex flex-wrap items-center gap-2 pb-1">
                    {PIPELINE_ORDER.map((nodeId, idx) => {
                      const node = nodeById.get(nodeId);
                      const nodeStatus = node?.status || "idle";
                      const nextNodeId = PIPELINE_ORDER[idx + 1];
                      const link = nextNodeId ? linkByPair.get(`${nodeId}->${nextNodeId}`) : null;
                      const linkClass = link?.state === "active" ? "bg-emerald-500 animate-pulse" : link?.state === "blocked" ? "bg-amber-500" : "bg-line";

                      return (
                        <div key={nodeId} className="flex items-center gap-2">
                          <div className={`rounded-lg border px-3 py-2 text-xs font-medium ${statusBadgeClass(nodeStatus)}`}>
                            {node?.label || nodeId}
                          </div>
                          {nextNodeId ? <div className={`h-[2px] w-10 rounded ${linkClass}`} /> : null}
                        </div>
                      );
                    })}
                  </div>
                  <div className="grid gap-2 md:grid-cols-3">
                    <div className="rounded-lg border border-line bg-panel-soft px-3 py-2 text-xs text-muted">Collect: A/B/C</div>
                    <div className="rounded-lg border border-line bg-panel-soft px-3 py-2 text-xs text-muted">Synthesize: D/E/F</div>
                    <div className="rounded-lg border border-line bg-panel-soft px-3 py-2 text-xs text-muted">Dispatch: Email Validation</div>
                  </div>
                </div>
              </Panel>
            </div>

            <div className="min-w-0 2xl:flex-1">
              <Panel title="Impact Simulator">
                <div className="space-y-3">
                  <div className="flex flex-wrap gap-2">
                    {IMPACT_AGENTS.map((agent) => (
                      <button
                        key={agent}
                        type="button"
                        className={`rounded-full border px-3 py-1 text-xs ${impactAgent === agent ? "border-cyan-500 bg-cyan-500/15 text-cyan-200" : "border-line text-ink-soft hover:border-line"}`}
                        onClick={() => setImpactAgent(agent)}
                      >
                        {agent}
                      </button>
                    ))}
                  </div>
                  <div className="rounded-lg border border-line bg-panel-soft px-3 py-2 text-xs text-muted">
                    If <span className="text-ink">{impactAgent}</span> fails, projected downstream slippage:
                  </div>
                  <div className="space-y-2">
                    {impactRows.length ? impactRows.map((row, idx) => {
                      const slip = row.estimated_slippage_seconds ?? 0;
                      const pct = Math.max(6, Math.min(100, Math.round((slip / 600) * 100)));
                      return (
                        <div key={`${row.agent_name}-${idx}`} className="rounded-lg border border-amber-700/40 bg-amber-950/20 p-2">
                          <div className="flex items-center justify-between gap-2 text-xs">
                            <span className="font-medium text-amber-200">{row.label}</span>
                            <span className="text-amber-300">+{slip}s</span>
                          </div>
                          <div className="mt-2 h-1.5 rounded bg-elevated">
                            <div className="h-full rounded bg-amber-400" style={{ width: `${pct}%` }} />
                          </div>
                          <div className="mt-1 text-[11px] text-amber-300" title={fmtUtcTooltip(row.next_run_at_utc || null)}>
                            next EAT {fmtEAT(row.next_run_at_eat || row.next_run_at_utc || null)}
                          </div>
                        </div>
                      );
                    }) : <p className="text-xs text-ink-faint">{impactQuery.isLoading ? "Loading impact simulation..." : "No impact rows available."}</p>}
                  </div>
                </div>
              </Panel>
            </div>
          </div>

          <div className="flex flex-col gap-4 2xl:flex-row">
            <div className="min-w-0 2xl:flex-[1.35]">
              <Panel title="Email Flow Intelligence">
                <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                  <div className="rounded-lg border border-line bg-panel-soft p-3">
                    <div className="text-[11px] uppercase tracking-[0.14em] text-ink-faint">Last Sent</div>
                    <div className="mt-2 text-sm font-semibold text-ink" title={fmtUtcTooltip(lastEmailSent?.finished_at || lastEmailSent?.started_at || null)}>
                      {fmtEAT(lastEmailSent?.finished_at || lastEmailSent?.started_at || null)}
                    </div>
                    <div className="mt-1 text-xs text-ink-faint">{lastEmailSent ? "from run metrics" : "no send in window"}</div>
                  </div>
                  <div className="rounded-lg border border-line bg-panel-soft p-3">
                    <div className="text-[11px] uppercase tracking-[0.14em] text-ink-faint">Sender Agent</div>
                    <div className="mt-2 text-sm font-semibold text-ink">
                      {lastEmailSent ? (agentNameToLabel.get(lastEmailSent.agent_name) || lastEmailSent.agent_name) : "-"}
                    </div>
                    <div className="mt-1 text-xs text-ink-faint">{lastEmailSent?.status_reason ? clip(lastEmailSent.status_reason, 36) : "latest sender"}</div>
                  </div>
                  <div className="rounded-lg border border-line bg-panel-soft p-3">
                    <div className="text-[11px] uppercase tracking-[0.14em] text-ink-faint">Next Email ETA</div>
                    <div className="mt-2 text-sm font-semibold text-ink">{fmtEta(snapshot.metrics.next_email_eta_seconds)}</div>
                    <div className="mt-1 text-xs text-ink-faint">scheduler forecast</div>
                  </div>
                  <div className="rounded-lg border border-line bg-panel-soft p-3">
                    <div className="text-[11px] uppercase tracking-[0.14em] text-ink-faint">Next Likely Sender</div>
                    <div className="mt-2 text-sm font-semibold text-ink">
                      {nextExactEmail?.agent_label || (nextExactEmail?.agent_name ? (agentNameToLabel.get(nextExactEmail.agent_name) || nextExactEmail.agent_name) : "-")}
                    </div>
                    <div className="mt-1 text-xs text-ink-faint" title={fmtUtcTooltip(nextExactEmail?.next_run_at_utc || null)}>
                      {fmtEAT(nextExactEmail?.next_run_at_eat || nextExactEmail?.next_run_at_utc || null)}
                    </div>
                  </div>
                </div>

                <div className="mt-3 grid gap-2 md:grid-cols-2">
                  {(nextEmailByAgent || []).slice(0, 6).map((item) => (
                    <div key={`${item.agent_name}-${item.next_run_at_utc || "na"}`} className="rounded-lg border border-cyan-700/30 bg-cyan-950/10 p-2">
                      <div className="flex items-center justify-between gap-2 text-xs">
                        <span className="font-medium text-cyan-200">{item.agent_label || item.agent_name}</span>
                        <span className="rounded-full border border-cyan-700/70 px-2 py-0.5 text-[10px] uppercase text-cyan-300">{item.window || "window"}</span>
                      </div>
                      <div className="mt-1 text-[11px] text-cyan-300" title={fmtUtcTooltip(item.next_run_at_utc || null)}>
                        {fmtEAT(item.next_run_at_eat || item.next_run_at_utc || null)}
                      </div>
                    </div>
                  ))}
                  {(nextEmailByAgent || []).length === 0 ? <p className="text-xs text-ink-faint">No exact per-agent email schedule available.</p> : null}
                </div>

                <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-3">
                  {emailSendHistory.slice(0, 6).map((row) => (
                    <div key={row.run_id} className="rounded-lg border border-emerald-700/30 bg-emerald-950/10 p-2">
                      <div className="flex items-center justify-between gap-2 text-xs">
                        <span className="font-medium text-emerald-200">{agentNameToLabel.get(row.agent_name) || row.agent_name}</span>
                        <Badge value={row.status} />
                      </div>
                      <div className="mt-1 text-[11px] text-emerald-300" title={fmtUtcTooltip(row.finished_at || row.started_at || null)}>
                        {fmtEAT(row.finished_at || row.started_at || null)}
                      </div>
                    </div>
                  ))}
                  {emailSendHistory.length === 0 ? <p className="text-xs text-ink-faint">No recent email sends captured from run metrics.</p> : null}
                </div>

                <div className="mt-3 rounded-lg border border-line bg-panel-soft p-3 text-xs text-ink-soft">
                  Validation window: <span className="text-ink">{snapshot.email.latest_validation_window || "-"}</span> ·
                  status <span className="text-ink">{snapshot.email.latest_validation_status || "-"}</span> ·
                  at <span title={fmtUtcTooltip(snapshot.email.latest_validation_at || null)} className="text-ink">{fmtEAT(snapshot.email.latest_validation_at || null)}</span>
                </div>
              </Panel>
            </div>

            <div className="min-w-0 2xl:flex-1">
              <Panel title="Upcoming Email-Capable Runs">
                <div className="max-h-[360px] space-y-2 overflow-auto pr-1">
                  {nextEmailDispatches.slice(0, 10).map((item, idx) => (
                    <div key={`${item.schedule_key || "dispatch"}-${idx}`} className="rounded-lg border border-line bg-panel-soft p-2">
                      <div className="flex items-center justify-between gap-2 text-xs">
                        <span className="font-medium text-ink">{item.window || "window"} validation</span>
                        <Badge value="scheduled" />
                      </div>
                      <div className="mt-1 text-[11px] text-muted" title={fmtUtcTooltip(item.next_run_at_utc || null)}>
                        EAT {fmtEAT(item.next_run_at_eat || item.next_run_at_utc || null)}
                      </div>
                      <div className="mt-1 text-[11px] text-ink-faint">{clip(item.schedule_key || "-", 64)}</div>
                      <div className="mt-1 text-[11px] text-ink-faint">
                        Agents: {(item.agents || []).map((agent) => agentNameToLabel.get(agent) || agent).join(", ") || "-"}
                      </div>
                    </div>
                  ))}
                  {nextEmailDispatches.length === 0 ? (
                    <p className="text-xs text-ink-faint">No scheduler email validation dispatches in current 24h forecast.</p>
                  ) : null}
                </div>
              </Panel>
            </div>
          </div>

          <Panel title={`Daily Agent Streaks (EAT ${snapshot.daily_streak.date_eat || "-"})`}>
            <div className="overflow-x-auto">
              <table className="w-full min-w-[980px] text-xs">
                <thead className="text-ink-faint">
                  <tr className="border-b border-line">
                    <th className="px-2 py-2 text-left">Agent</th>
                    <th className="px-2 py-2 text-right">Runs Today</th>
                    <th className="px-2 py-2 text-right">Success</th>
                    <th className="px-2 py-2 text-right">Partial</th>
                    <th className="px-2 py-2 text-right">Fail</th>
                    <th className="px-2 py-2 text-right">Running</th>
                    <th className="px-2 py-2 text-right">Emails Sent</th>
                    <th className="px-2 py-2 text-left">Last Run (EAT)</th>
                    <th className="px-2 py-2 text-left">Top Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {(snapshot.daily_streak.items || []).map((row) => (
                    <tr key={row.agent_name} className="border-b border-line">
                      <td className="px-2 py-2 text-ink">{row.agent_label}</td>
                      <td className="px-2 py-2 text-right text-ink-soft">{row.runs_today}</td>
                      <td className="px-2 py-2 text-right text-emerald-300">{row.success_today}</td>
                      <td className="px-2 py-2 text-right text-amber-300">{row.partial_today}</td>
                      <td className="px-2 py-2 text-right text-red-300">{row.fail_today}</td>
                      <td className="px-2 py-2 text-right text-cyan-300">{row.running_now}</td>
                      <td className="px-2 py-2 text-right text-violet-300">{row.email_sent_today}</td>
                      <td className="px-2 py-2 text-muted" title={fmtUtcTooltip(row.last_run_at_utc || null)}>
                        {fmtEAT(row.last_run_at_eat || row.last_run_at_utc || null)}
                      </td>
                      <td className="px-2 py-2 text-muted">
                        {(row.actions_today || []).length
                          ? row.actions_today.map((a) => `${a.event_type} (${a.count})`).join(" · ")
                          : "-"}
                      </td>
                    </tr>
                  ))}
                  {(snapshot.daily_streak.items || []).length === 0 ? (
                    <tr>
                      <td className="px-2 py-3 text-ink-faint" colSpan={9}>No daily streak data available yet.</td>
                    </tr>
                  ) : null}
                </tbody>
              </table>
            </div>
          </Panel>

          <div className="grid gap-4 xl:grid-cols-[1.05fr_1.25fr_1fr]">
            <Panel title="Past (What happened)">
              <div className="max-h-[430px] space-y-2 overflow-auto pr-1">
                {recentRuns.map((item) => (
                  <div key={item.run_id} className="rounded-lg border border-line bg-panel-soft p-2">
                    <div className="flex items-center justify-between gap-2 text-xs">
                      <span className="font-medium text-ink">{item.agent_label}</span>
                      <Badge value={item.status} />
                    </div>
                    <div className="mt-1 text-[11px] text-ink-faint" title={fmtUtcTooltip(item.finished_at || item.started_at || null)}>
                      {fmtEAT(item.finished_at || item.started_at || null)} · {item.duration_seconds ?? 0}s
                    </div>
                    <div className="mt-1 text-[11px] text-muted">{clip(item.status_reason)}</div>
                  </div>
                ))}
              </div>
            </Panel>

            <Panel title="Present (What is running)">
              <div className="grid gap-3 md:grid-cols-3">
                <div className="rounded-xl border border-cyan-700/30 bg-cyan-950/15 p-3">
                  <div className="text-[11px] uppercase tracking-[0.14em] text-cyan-300">Running</div>
                  <div className="mt-2 text-2xl font-semibold text-cyan-200">{snapshot.present.running.length}</div>
                </div>
                <div className="rounded-xl border border-line bg-panel-soft p-3">
                  <div className="text-[11px] uppercase tracking-[0.14em] text-muted">Queued</div>
                  <div className="mt-2 text-2xl font-semibold text-ink">{snapshot.present.queued.length}</div>
                </div>
                <div className="rounded-xl border border-amber-700/30 bg-amber-950/15 p-3">
                  <div className="text-[11px] uppercase tracking-[0.14em] text-amber-300">Blocked</div>
                  <div className="mt-2 text-2xl font-semibold text-amber-200">{snapshot.present.blocked.length}</div>
                </div>
              </div>

              <div className="mt-3 max-h-[300px] space-y-2 overflow-auto pr-1">
                {(snapshot.present.running || []).map((item) => (
                  <div key={item.run_id} className="rounded-lg border border-cyan-700/30 bg-cyan-950/15 p-2 text-xs">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-medium text-cyan-200">{item.agent_label}</span>
                      <Badge value={item.status} />
                    </div>
                    <div className="mt-1 text-[11px] text-cyan-300" title={fmtUtcTooltip(item.started_at || null)}>
                      started {fmtEAT(item.started_at || null)}
                    </div>
                  </div>
                ))}

                {(snapshot.present.blocked || []).map((item) => (
                  <div key={item.run_id} className="rounded-lg border border-amber-700/30 bg-amber-950/20 p-2 text-xs">
                    <div className="font-medium text-amber-200">{item.agent_label}</div>
                    <div className="mt-1 text-[11px] text-amber-300">waiting for: {item.waiting_for.join(", ")}</div>
                  </div>
                ))}

                {snapshot.present.running.length === 0 && snapshot.present.blocked.length === 0 ? (
                  <p className="text-xs text-ink-faint">No active or blocked workloads right now.</p>
                ) : null}
              </div>
            </Panel>

            <Panel title="Future (What runs next)">
              <div className="max-h-[430px] space-y-2 overflow-auto pr-1">
                {futureRuns.map((item, idx) => (
                  <div key={`${item.schedule_key || item.task_name || "job"}-${idx}`} className="rounded-lg border border-line bg-panel-soft p-2">
                    <div className="flex items-center justify-between gap-2 text-xs">
                      <span className="font-medium text-ink">{item.agent_name || "job"}</span>
                      <span className={`rounded-full border px-2 py-0.5 text-[10px] uppercase ${item.llm_interaction ? "border-violet-600/70 bg-violet-500/10 text-violet-300" : "border-line text-muted"}`}>
                        {item.llm_interaction ? "LLM" : "deterministic"}
                      </span>
                    </div>
                    <div className="mt-1 text-[11px] text-muted" title={fmtUtcTooltip(item.next_run_at_utc || null)}>
                      {fmtEAT(item.next_run_at_eat || item.next_run_at_utc || null)}
                    </div>
                    <div className="mt-1 text-[11px] text-ink-faint">p50 {item.predicted_duration_p50_seconds ?? "-"}s · p95 {item.predicted_duration_p95_seconds ?? "-"}s</div>
                  </div>
                ))}
              </div>
            </Panel>
          </div>

          <Panel title="Event Radar (Newest First)">
            <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
              {(snapshot.events.items || []).slice(0, 18).map((event, idx) => (
                <div key={`${event.event_time || "na"}-${idx}`} className="rounded-lg border border-line bg-panel-soft p-2">
                  <div className="flex items-center justify-between gap-2 text-xs">
                    <span className="text-muted" title={fmtUtcTooltip(event.event_time || null)}>{fmtEAT(event.event_time || null)}</span>
                    <Badge value={event.severity} />
                  </div>
                  <div className="mt-1 text-sm text-ink">{clip(event.message, 74)}</div>
                  <div className="mt-1 text-[11px] text-ink-faint">{event.source}{event.agent_name ? ` · ${event.agent_name}` : ""}</div>
                </div>
              ))}
            </div>
          </Panel>

          {live.error ? (
            <Panel title="Transport Notice">
              <p className="text-sm text-amber-300">{live.error}</p>
            </Panel>
          ) : null}

          {showRunAllModal ? (
            <div className="fixed inset-0 z-50 flex items-center justify-center bg-panel-soft p-4">
              <div className="w-full max-w-lg rounded-2xl border border-line bg-elevated p-5 shadow-2xl">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <h3 className="text-sm font-semibold text-ink">Super-Admin Confirmation</h3>
                    <p className="mt-1 text-xs text-muted">
                      This action queues A→F immediately. Type <span className="font-semibold text-amber-300">{RUN_FULL_CHAIN_CONFIRM_TEXT}</span> to continue.
                    </p>
                  </div>
                  <button
                    type="button"
                    className="rounded border border-line px-2 py-1 text-xs text-ink-soft hover:border-line"
                    onClick={() => {
                      setShowRunAllModal(false);
                      setRunAllConfirmInput("");
                    }}
                    disabled={adminBusy}
                  >
                    Close
                  </button>
                </div>

                <div className="mt-4 rounded-lg border border-line bg-panel-soft px-3 py-2 text-xs text-ink-soft">
                  Logged in as: <span className="font-medium text-ink">{currentUsername || "unknown"}</span>
                </div>

                <input
                  value={runAllConfirmInput}
                  onChange={(e) => setRunAllConfirmInput(e.target.value)}
                  placeholder={RUN_FULL_CHAIN_CONFIRM_TEXT}
                  className="mt-3 w-full rounded-lg border border-line bg-inset px-3 py-2 text-sm text-ink outline-none ring-brand/40 placeholder:text-ink-faint focus:border-brand focus:ring-2"
                />

                <div className="mt-4 flex items-center justify-end gap-2">
                  <Button
                    variant="secondary"
                    onClick={() => {
                      setShowRunAllModal(false);
                      setRunAllConfirmInput("");
                    }}
                    disabled={adminBusy}
                  >
                    Cancel
                  </Button>
                  <Button
                    variant="danger"
                    loading={adminBusy}
                    disabled={!isSuperAdmin || runAllConfirmInput.trim() !== RUN_FULL_CHAIN_CONFIRM_TEXT}
                    onClick={runAllAgentsChain}
                  >
                    Confirm Run Full Chain
                  </Button>
                </div>
              </div>
            </div>
          ) : null}
        </>
      )}
    </div>
  );
}
