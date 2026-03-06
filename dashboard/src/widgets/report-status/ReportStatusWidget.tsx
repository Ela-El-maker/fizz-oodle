"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchLatestReport } from "@/entities/report/api";
import { Panel } from "@/shared/ui/Panel";
import { Badge } from "@/shared/ui/Badge";
import { fmtDateTime } from "@/shared/lib/format";
import { normalizeStatus } from "@/shared/lib/status";

export function ReportStatusWidget() {
  const daily = useQuery({ queryKey: ["report", "daily"], queryFn: () => fetchLatestReport("daily"), refetchInterval: 30000 });
  const weekly = useQuery({ queryKey: ["report", "weekly"], queryFn: () => fetchLatestReport("weekly"), refetchInterval: 30000 });

  if (daily.isLoading || weekly.isLoading) return <Panel title="Analyst Reports">Loading...</Panel>;
  if (daily.isError || weekly.isError) return <Panel title="Analyst Reports">Failed to load reports.</Panel>;

  return (
    <Panel title="Analyst Reports">
      <div className="space-y-2 text-sm">
        <div className="flex items-center justify-between rounded-lg border border-line bg-panel-soft px-3 py-2">
          <div>
            <div className="text-xs uppercase tracking-wide text-ink-faint">Daily</div>
            <div className="text-ink-soft">{daily.data?.item?.period_key || "-"}</div>
          </div>
          <div className="text-right">
            <Badge value={normalizeStatus(daily.data?.item?.status)} />
            <div className="mt-1 text-xs text-ink-faint">{fmtDateTime(daily.data?.item?.generated_at)}</div>
          </div>
        </div>
        <div className="flex items-center justify-between rounded-lg border border-line bg-panel-soft px-3 py-2">
          <div>
            <div className="text-xs uppercase tracking-wide text-ink-faint">Weekly</div>
            <div className="text-ink-soft">{weekly.data?.item?.period_key || "-"}</div>
          </div>
          <div className="text-right">
            <Badge value={normalizeStatus(weekly.data?.item?.status)} />
            <div className="mt-1 text-xs text-ink-faint">{fmtDateTime(weekly.data?.item?.generated_at)}</div>
          </div>
        </div>
      </div>
    </Panel>
  );
}
