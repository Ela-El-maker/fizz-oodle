"use client";

import { useMemo, useState } from "react";

import { useStoryMonitorLive } from "@/features/monitor/useStoryMonitorLive";
import { Panel } from "@/shared/ui/Panel";
import { Select } from "@/shared/ui/Select";
import { Skeleton } from "@/shared/ui/Skeleton";
import { Badge } from "@/shared/ui/Badge";
import { StatCard } from "@/shared/ui/StatCard";
import { fmtDateTime } from "@/shared/lib/format";

export default function StoriesPage() {
  const [requestLimit, setRequestLimit] = useState("10");
  const live = useStoryMonitorLive();
  const snapshot = live.snapshot;

  const nodeById = useMemo(() => {
    const mapping = new Map<string, { id: string; label: string; status: string }>();
    (snapshot?.pipeline.nodes || []).forEach((node) => mapping.set(node.id, node));
    return mapping;
  }, [snapshot?.pipeline.nodes]);

  const linkByPair = useMemo(() => {
    const mapping = new Map<string, { from: string; to: string; state: string }>();
    (snapshot?.pipeline.links || []).forEach((link) => mapping.set(`${link.from}->${link.to}`, link));
    return mapping;
  }, [snapshot?.pipeline.links]);

  const requestRows = useMemo(
    () => (snapshot?.requests.items || []).slice(0, Math.max(1, Number(requestLimit))),
    [snapshot?.requests.items, requestLimit],
  );

  const pipelineOrder = ["A", "B", "C", "D", "E", "F", "OUT"];

  const transportLabel = live.transport === "ws" ? "WS Live" : live.transport === "polling" ? "Polling Fallback" : "Connecting";

  return (
    <div className="space-y-4">
      <Panel>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-lg font-semibold text-ink">Agent F - Narrative Engine Monitor</h1>
            <p className="text-sm text-muted">Live operational telemetry and agent interaction pipeline</p>
          </div>
          <div className="flex items-center gap-2 text-xs">
            <span className={`rounded border px-2 py-1 ${live.transport === "ws" ? "border-emerald-700 text-emerald-300" : "border-amber-700 text-amber-300"}`}>
              {transportLabel}
            </span>
            <span className="text-ink-faint">
              Updated: {fmtDateTime(snapshot?.generated_at || null)}
            </span>
          </div>
        </div>
      </Panel>

      {live.isLoading ? (
        <Panel title="Loading Monitor">
          <div className="grid gap-3 md:grid-cols-2">
            <Skeleton className="h-24 w-full bg-elevated" />
            <Skeleton className="h-24 w-full bg-elevated" />
          </div>
        </Panel>
      ) : !snapshot ? (
        <Panel title="Agent F Monitor">
          <p className="text-sm text-muted">No telemetry available yet.</p>
          {live.error ? <p className="mt-2 text-sm text-red-300">{live.error}</p> : null}
        </Panel>
      ) : (
        <>
          <div className="grid gap-4 lg:grid-cols-2">
            <Panel title="Agent Status">
              <div className="space-y-3">
                <div className="flex items-center justify-between">
                  <div className="text-sm text-ink-soft">Agent Status</div>
                  <Badge value={snapshot.status.agent_status.toLowerCase()} />
                </div>
                <div className="text-sm text-ink-soft">
                  <span className="text-ink-faint">Current Task:</span> {snapshot.status.current_task}
                </div>
                <div>
                  <div className="mb-1 flex items-center justify-between text-xs text-ink-faint">
                    <span>{snapshot.status.progress_label}</span>
                    <span>{snapshot.status.progress_pct}%</span>
                  </div>
                  <div className="h-2 rounded-full bg-elevated">
                    <div
                      className="h-2 rounded-full bg-emerald-500 transition-all duration-300"
                      style={{ width: `${Math.max(0, Math.min(100, snapshot.status.progress_pct))}%` }}
                    />
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-2 text-xs text-muted">
                  <div>Start: {fmtDateTime(snapshot.status.started_at || null)}</div>
                  <div>ETA: {fmtDateTime(snapshot.status.estimated_completion_at || null)}</div>
                </div>
              </div>
            </Panel>

            <Panel title="System Health Indicators">
              <div className="grid gap-2 md:grid-cols-2">
                <StatCard
                  label="Data Freshness"
                  value={snapshot.health.data_freshness.status.toUpperCase()}
                  hint={`${snapshot.health.data_freshness.minutes_since_last_success ?? "-"}m since success`}
                  tone={snapshot.health.data_freshness.status === "ok" ? "success" : "warning"}
                />
                <StatCard
                  label="Agent Connectivity"
                  value={snapshot.health.agent_connectivity.status.toUpperCase()}
                  hint={`${snapshot.health.agent_connectivity.healthy_agents}/${snapshot.health.agent_connectivity.total_agents} healthy`}
                  tone={snapshot.health.agent_connectivity.status === "ok" ? "success" : "warning"}
                />
                <StatCard
                  label="Pipeline Latency"
                  value={`${snapshot.health.pipeline_latency.p95_seconds}s`}
                  hint={`p50 ${snapshot.health.pipeline_latency.p50_seconds}s`}
                  tone={snapshot.health.pipeline_latency.status === "ok" ? "success" : "warning"}
                />
                <StatCard
                  label="Scraper Health"
                  value={snapshot.health.scraper_health.status.toUpperCase()}
                  hint={`${snapshot.health.scraper_health.active_jobs} active, ${snapshot.health.scraper_health.recent_failures} failures`}
                  tone={snapshot.health.scraper_health.status === "ok" ? "success" : "warning"}
                />
              </div>
            </Panel>
          </div>

          <Panel title="Live Pipeline Visualization">
            <div className="overflow-x-auto">
              <div className="flex min-w-max items-center gap-2 py-2">
                {pipelineOrder.map((nodeId, index) => {
                  const node = nodeById.get(nodeId);
                  const nodeStatus = node?.status || "idle";
                  const nodeClass = nodeStatus === "active"
                    ? "border-emerald-700 bg-emerald-500/10 text-emerald-300"
                    : nodeStatus === "error"
                      ? "border-red-700 bg-red-500/10 text-red-300"
                      : "border-line bg-elevated text-ink-soft";
                  const nextNodeId = pipelineOrder[index + 1];
                  const link = nextNodeId ? linkByPair.get(`${nodeId}->${nextNodeId}`) : null;
                  const linkClass = link?.state === "active" ? "bg-emerald-500 animate-pulse" : "bg-line";
                  return (
                    <div key={nodeId} className="flex items-center gap-2">
                      <div className={`rounded border px-3 py-2 text-xs font-medium ${nodeClass}`}>
                        {node?.label || nodeId}
                      </div>
                      {nextNodeId ? <div className={`h-[2px] w-8 rounded ${linkClass}`} /> : null}
                    </div>
                  );
                })}
              </div>
            </div>
          </Panel>

          <div className="grid gap-4 xl:grid-cols-2">
            <Panel title="Live Agent Requests">
              <div className="mb-3 flex items-center justify-between">
                <div className="text-xs text-ink-faint">Inferred from existing telemetry</div>
                <div className="w-32">
                  <Select value={requestLimit} onChange={(e) => setRequestLimit(e.target.value)}>
                    <option value="10">Show 10</option>
                    <option value="20">Show 20</option>
                  </Select>
                </div>
              </div>
              {requestRows.length === 0 ? (
                <p className="text-sm text-muted">No recent requests.</p>
              ) : (
                <div className="space-y-2">
                  {requestRows.map((item, idx) => (
                    <div key={`${item.time || "na"}-${idx}`} className="grid grid-cols-[auto_auto_1fr_auto] items-center gap-2 rounded border border-line bg-panel-soft px-2 py-2 text-xs">
                      <div className="text-ink-faint">{fmtDateTime(item.time || null)}</div>
                      <div className="font-medium text-ink-soft">{item.source_agent}</div>
                      <div className="text-ink-soft">{item.request}</div>
                      <div><Badge value={item.status} /></div>
                    </div>
                  ))}
                </div>
              )}
            </Panel>

            <Panel title="Internet Scraping Activity">
              <div className="space-y-3">
                {snapshot.scrapers.items.map((item) => (
                  <div key={item.name} className="rounded border border-line bg-panel-soft p-3">
                    <div className="mb-2 flex items-center justify-between">
                      <div className="text-sm font-medium text-ink">{item.name}</div>
                      <Badge value={item.status} />
                    </div>
                    <div className="mb-2 h-2 rounded-full bg-elevated">
                      <div
                        className={`h-2 rounded-full ${item.status === "running" ? "bg-emerald-500 animate-pulse" : item.status === "degraded" ? "bg-amber-500" : "bg-line"}`}
                        style={{ width: `${Math.max(0, Math.min(100, item.progress_pct))}%` }}
                      />
                    </div>
                    <div className="text-xs text-ink-faint">
                      Progress {item.progress_pct}% • Last update {fmtDateTime(item.last_update_at || null)}
                    </div>
                  </div>
                ))}
              </div>
            </Panel>
          </div>

          <div className="grid gap-4 xl:grid-cols-2">
            <Panel title="Live Event Stream">
              {(snapshot.events.items || []).length === 0 ? (
                <p className="text-sm text-muted">No recent events.</p>
              ) : (
                <div className="space-y-2">
                  {(snapshot.events.items || []).slice(0, 20).map((event, idx) => (
                    <div key={`${event.time || "na"}-${idx}`} className="rounded border border-line bg-panel-soft px-3 py-2 text-xs">
                      <div className="flex items-center justify-between">
                        <span className="text-ink-faint">{fmtDateTime(event.time || null)}</span>
                        <Badge value={event.level} />
                      </div>
                      <div className="mt-1 text-ink">{event.message}</div>
                      <div className="mt-1 text-ink-faint">{event.source}</div>
                    </div>
                  ))}
                </div>
              )}
            </Panel>

            <Panel title="Last 5 Agent Cycles">
              {(snapshot.cycles.items || []).length === 0 ? (
                <p className="text-sm text-muted">No recent cycles.</p>
              ) : (
                <div className="space-y-2">
                  {(snapshot.cycles.items || []).slice(0, 5).map((cycle) => (
                    <div key={cycle.run_id || cycle.cycle_id} className="grid grid-cols-[auto_1fr_auto_auto] items-center gap-2 rounded border border-line bg-panel-soft px-3 py-2 text-xs">
                      <div className="font-medium text-ink">{cycle.cycle_id}</div>
                      <div className="text-ink-faint">{fmtDateTime(cycle.start || null)}</div>
                      <div className="text-ink-soft">{cycle.duration_seconds ?? "-"}s</div>
                      <div><Badge value={cycle.result} /></div>
                    </div>
                  ))}
                </div>
              )}
            </Panel>
          </div>

          {live.error ? (
            <Panel title="Transport Notice">
              <p className="text-sm text-amber-300">{live.error}</p>
            </Panel>
          ) : null}
        </>
      )}
    </div>
  );
}
