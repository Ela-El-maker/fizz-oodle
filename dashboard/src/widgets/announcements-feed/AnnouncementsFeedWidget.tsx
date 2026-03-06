"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchAnnouncements, fetchAnnouncementStats } from "@/entities/announcement/api";
import { Panel } from "@/shared/ui/Panel";
import { StatCard } from "@/shared/ui/StatCard";
import { Badge } from "@/shared/ui/Badge";
import { fmtDateTime, fmtNumber } from "@/shared/lib/format";

export function AnnouncementsFeedWidget() {
  const stats = useQuery({ queryKey: ["announcement-stats"], queryFn: fetchAnnouncementStats, refetchInterval: 30000 });
  const list = useQuery({ queryKey: ["announcements", "latest"], queryFn: () => fetchAnnouncements({ limit: 10 }), refetchInterval: 30000 });

  if (stats.isLoading || list.isLoading) return <Panel title="Announcements">Loading...</Panel>;
  if (stats.isError || list.isError) return <Panel title="Announcements">Failed to load announcements.</Panel>;

  const items = list.data?.items || [];
  const alphaCount = items.filter((item) => item.alpha_context && Object.keys(item.alpha_context).length > 0).length;

  return (
    <Panel title="Announcements Snapshot">
      <div className="mb-3 grid gap-2 sm:grid-cols-3">
        <StatCard label="Total" value={fmtNumber(stats.data?.total)} tone="brand" />
        <StatCard label="Alerted" value={fmtNumber(stats.data?.alerted)} tone="success" />
        <StatCard label="Unalerted" value={fmtNumber(stats.data?.unalerted)} tone="warning" />
      </div>
      {stats.data?.human_summary?.headline ? (
        <div className="mb-3 rounded-lg border border-line bg-panel-soft px-3 py-2 text-sm text-ink">
          {stats.data.human_summary.headline}
        </div>
      ) : null}
      <div className="mb-3 text-xs text-muted">
        Alpha-enriched records in view: <span className="font-semibold text-ink">{alphaCount}/{items.length}</span>
      </div>
      <ul className="space-y-2 text-sm">
        {items.map((item) => (
          <li key={item.announcement_id} className="rounded-lg border border-line bg-panel-soft px-3 py-2">
            <div className="mb-1 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Badge value={item.ticker || "NSE"} />
                <Badge value={item.announcement_type || "other"} />
                {item.alpha_context && Object.keys(item.alpha_context).length > 0 ? <Badge value="alpha_ctx" /> : null}
              </div>
              <span className="text-xs text-ink-faint">{fmtDateTime(item.announcement_date)}</span>
            </div>
            <div className="font-medium text-ink">{item.headline || "(no headline)"}</div>
          </li>
        ))}
      </ul>
    </Panel>
  );
}
