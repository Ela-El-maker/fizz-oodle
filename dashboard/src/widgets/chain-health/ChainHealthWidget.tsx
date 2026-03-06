"use client";

import { useQuery } from "@tanstack/react-query";
import { fetchRuns } from "@/entities/run/api";
import { fetchLatestReport } from "@/entities/report/api";
import { fetchLatestArchive } from "@/entities/archive/api";
import { Panel } from "@/shared/ui/Panel";
import { Badge } from "@/shared/ui/Badge";
import { fmtDateTime } from "@/shared/lib/format";
import { normalizeStatus } from "@/shared/lib/status";

const GOOD_TERMINAL = new Set(["success", "partial"]);

function isFresh(value: string | null | undefined, maxAgeHours: number): boolean {
  if (!value) return false;
  const ts = Date.parse(value);
  if (Number.isNaN(ts)) return false;
  return Date.now() - ts <= maxAgeHours * 60 * 60 * 1000;
}

export function ChainHealthWidget() {
  const aRuns = useQuery({
    queryKey: ["runs", "chain", "briefing"],
    queryFn: () => fetchRuns({ agent_name: "briefing", limit: 1 }),
    refetchInterval: 15000,
  });
  const bRuns = useQuery({
    queryKey: ["runs", "chain", "announcements"],
    queryFn: () => fetchRuns({ agent_name: "announcements", limit: 1 }),
    refetchInterval: 15000,
  });
  const cRuns = useQuery({
    queryKey: ["runs", "chain", "sentiment"],
    queryFn: () => fetchRuns({ agent_name: "sentiment", limit: 1 }),
    refetchInterval: 15000,
  });
  const dRuns = useQuery({
    queryKey: ["runs", "chain", "analyst"],
    queryFn: () => fetchRuns({ agent_name: "analyst", limit: 1 }),
    refetchInterval: 15000,
  });
  const eRuns = useQuery({
    queryKey: ["runs", "chain", "archivist"],
    queryFn: () => fetchRuns({ agent_name: "archivist", limit: 1 }),
    refetchInterval: 15000,
  });
  const fRuns = useQuery({
    queryKey: ["runs", "chain", "narrator"],
    queryFn: () => fetchRuns({ agent_name: "narrator", limit: 1 }),
    refetchInterval: 15000,
  });
  const latestDaily = useQuery({
    queryKey: ["report", "daily", "chain-health"],
    queryFn: () => fetchLatestReport("daily"),
    refetchInterval: 30000,
  });
  const latestArchive = useQuery({
    queryKey: ["archive", "weekly", "chain-health"],
    queryFn: () => fetchLatestArchive("weekly"),
    refetchInterval: 30000,
  });

  if (aRuns.isLoading || bRuns.isLoading || cRuns.isLoading || dRuns.isLoading || eRuns.isLoading || fRuns.isLoading) {
    return <Panel title="A→B→C→D→E→F Chain Health">Loading...</Panel>;
  }
  if (aRuns.isError || bRuns.isError || cRuns.isError || dRuns.isError || eRuns.isError || fRuns.isError) {
    return <Panel title="A→B→C→D→E→F Chain Health">Failed to load chain status.</Panel>;
  }

  const a = aRuns.data?.items?.[0];
  const b = bRuns.data?.items?.[0];
  const c = cRuns.data?.items?.[0];
  const d = dRuns.data?.items?.[0];
  const e = eRuns.data?.items?.[0];
  const f = fRuns.data?.items?.[0];

  const aStatus = normalizeStatus(a?.status);
  const bStatus = normalizeStatus(b?.status);
  const cStatus = normalizeStatus(c?.status);
  const dStatus = normalizeStatus(d?.status);
  const eStatus = normalizeStatus(e?.status);
  const fStatus = normalizeStatus(f?.status);

  const aReady =
    GOOD_TERMINAL.has(aStatus) &&
    (isFresh(a?.finished_at, 24) || isFresh(a?.started_at, 24));

  const bcReady =
    GOOD_TERMINAL.has(bStatus) &&
    GOOD_TERMINAL.has(cStatus) &&
    (isFresh(b?.finished_at, 24) || isFresh(b?.started_at, 24)) &&
    (isFresh(c?.finished_at, 24) || isFresh(c?.started_at, 24));

  const dInputChain = typeof d?.metrics?.input_chain === "string" ? d.metrics.input_chain : null;
  const dUsesABC = dInputChain === "A+B+C";
  const dReady = GOOD_TERMINAL.has(dStatus) && dUsesABC;

  const archiveMetricsRaw = latestArchive.data?.item?.summary?.metrics;
  const archiveMetrics =
    archiveMetricsRaw && typeof archiveMetricsRaw === "object" ? (archiveMetricsRaw as Record<string, unknown>) : {};
  const eInputMode =
    typeof e?.metrics?.input_mode === "string"
      ? e.metrics.input_mode
      : typeof archiveMetrics.input_mode === "string"
        ? archiveMetrics.input_mode
        : null;
  const eReportsConsideredRaw =
    typeof e?.metrics?.reports_considered === "number"
      ? e.metrics.reports_considered
      : typeof archiveMetrics.reports_considered === "number"
        ? archiveMetrics.reports_considered
        : 0;
  const eReportsConsidered = Number(eReportsConsideredRaw || 0);
  const eUsesD = (eInputMode === "analyst_only" || eInputMode === "hybrid") && eReportsConsidered > 0;
  const eReady = GOOD_TERMINAL.has(eStatus) && eUsesD;

  const fInputChain = typeof f?.metrics?.input_chain === "string" ? f.metrics.input_chain : "A+B+C+D+E";
  const fReady =
    GOOD_TERMINAL.has(fStatus) &&
    (isFresh(f?.finished_at, 24) || isFresh(f?.started_at, 24));

  const overall = aReady && bcReady && dReady && eReady && fReady ? "success" : "partial";
  const latestReportId = latestDaily.data?.item?.report_id || "-";

  return (
    <Panel title="A→B→C→D→E→F Chain Health">
      <div className="mb-3 flex flex-wrap items-center gap-3 text-sm">
        <span className="text-muted">Overall:</span>
        <Badge value={overall} />
        <span className="text-ink-faint">Latest D report: {latestReportId}</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-ink-faint">
              <th className="py-2">Step</th>
              <th>Status</th>
              <th>Contract</th>
              <th>Latest Time</th>
            </tr>
          </thead>
          <tbody>
            <tr className="border-t border-line">
              <td className="py-2 text-ink">A Collect</td>
              <td><Badge value={aStatus} /></td>
              <td className="text-ink-soft">{a?.status_reason || "-"}</td>
              <td className="text-ink-faint">{fmtDateTime(a?.finished_at || a?.started_at)}</td>
            </tr>
            <tr className="border-t border-line">
              <td className="py-2 text-ink">B Collect</td>
              <td><Badge value={bStatus} /></td>
              <td className="text-ink-soft">{b?.status_reason || "-"}</td>
              <td className="text-ink-faint">{fmtDateTime(b?.finished_at || b?.started_at)}</td>
            </tr>
            <tr className="border-t border-line">
              <td className="py-2 text-ink">C Collect</td>
              <td><Badge value={cStatus} /></td>
              <td className="text-ink-soft">{c?.status_reason || "-"}</td>
              <td className="text-ink-faint">{fmtDateTime(c?.finished_at || c?.started_at)}</td>
            </tr>
            <tr className="border-t border-line">
              <td className="py-2 text-ink">D Synthesize from ABC</td>
              <td><Badge value={dStatus} /></td>
              <td className="text-ink-soft">{dInputChain || "missing input_chain metric"}</td>
              <td className="text-ink-faint">{fmtDateTime(d?.finished_at || d?.started_at)}</td>
            </tr>
            <tr className="border-t border-line">
              <td className="py-2 text-ink">E Consume D</td>
              <td><Badge value={eStatus} /></td>
              <td className="text-ink-soft">{`mode=${eInputMode || "-"}, reports=${eReportsConsidered}`}</td>
              <td className="text-ink-faint">{fmtDateTime(e?.finished_at || e?.started_at)}</td>
            </tr>
            <tr className="border-t border-line">
              <td className="py-2 text-ink">F Narrate from A-E</td>
              <td><Badge value={fStatus} /></td>
              <td className="text-ink-soft">{fInputChain}</td>
              <td className="text-ink-faint">{fmtDateTime(f?.finished_at || f?.started_at)}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </Panel>
  );
}
