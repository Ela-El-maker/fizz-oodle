"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchPatternSummary } from "@/entities/pattern/api";
import { fetchLatestArchive } from "@/entities/archive/api";
import { Panel } from "@/shared/ui/Panel";
import { Badge } from "@/shared/ui/Badge";
import { StatCard } from "@/shared/ui/StatCard";
import { fmtNumber } from "@/shared/lib/format";
import { normalizeStatus } from "@/shared/lib/status";

export function PatternSummaryWidget() {
  const summary = useQuery({ queryKey: ["pattern-summary"], queryFn: fetchPatternSummary, refetchInterval: 60000 });
  const archive = useQuery({ queryKey: ["archive-latest", "weekly"], queryFn: () => fetchLatestArchive("weekly"), refetchInterval: 60000 });

  if (summary.isLoading || archive.isLoading) return <Panel title="Patterns & Archive">Loading...</Panel>;
  if (summary.isError || archive.isError) return <Panel title="Patterns & Archive">Failed to load patterns.</Panel>;

  return (
    <Panel title="Patterns & Archive">
      <div className="grid gap-2 sm:grid-cols-3">
        <StatCard label="Total" value={fmtNumber(summary.data?.total_count)} tone="brand" />
        <StatCard label="Active" value={fmtNumber(summary.data?.active_count)} tone="success" />
        <StatCard label="Confirmed" value={fmtNumber(summary.data?.confirmed_count)} tone="warning" />
      </div>
      <div className="mt-3 flex items-center gap-2 text-sm">
        <Badge value={normalizeStatus(archive.data?.item?.status)} />
        <span className="text-muted">Archive period: {archive.data?.item?.period_key || "-"}</span>
      </div>
    </Panel>
  );
}
