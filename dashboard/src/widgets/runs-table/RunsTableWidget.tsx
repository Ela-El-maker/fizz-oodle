"use client";

import { useRunsPolling } from "@/features/run-monitor/useRunsPolling";
import { Panel } from "@/shared/ui/Panel";
import { Badge } from "@/shared/ui/Badge";
import { fmtDateTime } from "@/shared/lib/format";

export function RunsTableWidget({ limit = 15 }: { limit?: number }) {
  const runs = useRunsPolling(limit);
  if (runs.isLoading) return <Panel title="Latest Runs">Loading...</Panel>;
  if (runs.isError) return <Panel title="Latest Runs">Failed to load runs.</Panel>;

  return (
    <Panel title="Latest Runs">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-ink-faint">
              <th className="py-2">Agent</th>
              <th>Status</th>
              <th>Started</th>
              <th>Finished</th>
              <th>Processed</th>
              <th>New</th>
              <th>Errors</th>
              <th>Reason</th>
            </tr>
          </thead>
          <tbody>
            {(runs.data?.items || []).map((r) => (
              <tr key={r.run_id} className="border-t border-line">
                <td className="py-2 text-ink">{r.agent_name}</td>
                <td><Badge value={r.status} /></td>
                <td className="text-muted">{fmtDateTime(r.started_at)}</td>
                <td className="text-muted">{fmtDateTime(r.finished_at)}</td>
                <td className="text-ink-soft">{r.records_processed ?? 0}</td>
                <td className="text-ink-soft">{r.records_new ?? 0}</td>
                <td className="text-ink-soft">{r.errors_count ?? 0}</td>
                <td className="max-w-[240px] truncate text-ink-faint">
                  {r.status_reason || r.error_message || (r.is_stale_reconciled ? "stale reconciled" : "-")}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}
