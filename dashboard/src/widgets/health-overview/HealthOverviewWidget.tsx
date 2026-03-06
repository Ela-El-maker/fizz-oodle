"use client";

import { useHealth } from "@/features/health/useHealth";
import { Panel } from "@/shared/ui/Panel";
import { Badge } from "@/shared/ui/Badge";
import { StatCard } from "@/shared/ui/StatCard";
import { normalizeStatus } from "@/shared/lib/status";

export function HealthOverviewWidget() {
  const health = useHealth();
  if (health.isLoading) return <Panel title="System Health">Loading...</Panel>;
  if (health.isError) return <Panel title="System Health">Failed to load health.</Panel>;

  const dependencies = Object.entries(health.data?.dependencies || {});
  const okCount = dependencies.filter(([, raw]) => {
    const value = normalizeStatus((raw as { status?: string } | undefined)?.status);
    return value === "success";
  }).length;
  const failCount = dependencies.length - okCount;
  const systemStatus = normalizeStatus(health.data?.status);
  const systemTone = systemStatus === "success" ? "success" : systemStatus === "partial" ? "warning" : "danger";
  const systemLabel =
    systemStatus === "success" ? "HEALTHY" :
    systemStatus === "partial" ? "DEGRADED" :
    systemStatus === "fail" ? "ERROR" :
    systemStatus.toUpperCase();

  return (
    <div className="grid gap-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <StatCard label="System" value={systemLabel} tone={systemTone} />
        <StatCard label="Healthy Services" value={okCount} tone="brand" />
        <StatCard label="Issues" value={failCount} tone={failCount > 0 ? "warning" : "success"} />
      </div>
      <Panel title="Dependencies">
        <div className="grid gap-2">
          {dependencies.map(([name, raw]) => {
            const item = raw as Record<string, unknown>;
            const service = typeof item.service === "string" ? item.service : (typeof item.service_agent === "string" ? item.service_agent : "-");
            const detail = typeof item.message === "string" ? item.message : (typeof item.error === "string" ? item.error : "");
            const status = normalizeStatus(item.status);
            return (
              <div key={name} className="grid grid-cols-[1fr_auto] items-center gap-3 rounded-lg border border-line bg-panel-soft px-3 py-2">
                <div>
                  <div className="text-sm font-medium text-ink">{name.replaceAll("_", " ")}</div>
                  <div className="text-xs text-ink-faint">{service}{detail ? ` · ${detail}` : ""}</div>
                </div>
                <Badge value={status} />
              </div>
            );
          })}
        </div>
      </Panel>
    </div>
  );
}
