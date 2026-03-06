"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchDailyPrices } from "@/entities/price/api";
import { fetchWeeklySentiment } from "@/entities/sentiment/api";
import { fetchPatternSummary } from "@/entities/pattern/api";
import { fetchAnnouncementStats } from "@/entities/announcement/api";
import { fetchLatestReport } from "@/entities/report/api";
import { fetchLatestStory } from "@/entities/story/api";
import { fetchUniverseSummary } from "@/entities/universe/api";
import { Panel } from "@/shared/ui/Panel";
import { StatCard } from "@/shared/ui/StatCard";
import { Input } from "@/shared/ui/Input";
import { Select } from "@/shared/ui/Select";
import { Badge } from "@/shared/ui/Badge";
import { fmtDateTime, fmtDecimal, fmtNumber } from "@/shared/lib/format";
import { buildMarketStory } from "@/features/market-story/buildMarketStory";

type SortMode = "ticker_asc" | "ticker_desc" | "change_desc" | "change_asc" | "volume_desc";
type ViewMode = "priced_only" | "all_tracked";

function todayIsoDate() {
  return new Date().toISOString().slice(0, 10);
}

function normalizeEvidenceLabel(value: string): string {
  const normalized = value.trim().toLowerCase();
  const map: Record<string, string> = {
    breadth_snapshot: "Breadth Snapshot",
    analyst_context: "Analyst Context",
    announcement_context: "Announcement Context",
    sentiment_context: "Sentiment Context",
    pattern_context: "Pattern Context",
  };
  if (map[normalized]) return map[normalized];
  return value.replace(/_/g, " ").replace(/\s+/g, " ").trim();
}

function toEvidenceChips(
  source: Array<string | Record<string, unknown>> | undefined,
): string[] {
  if (!source || source.length === 0) return [];
  const out: string[] = [];
  for (const item of source) {
    if (typeof item === "string") {
      out.push(normalizeEvidenceLabel(item));
      continue;
    }
    const type = typeof item.type === "string" ? normalizeEvidenceLabel(item.type) : "Evidence";
    const sourceId = typeof item.source_id === "string" ? item.source_id : undefined;
    const ticker = typeof item.ticker === "string" ? item.ticker : undefined;
    if (ticker && sourceId) {
      out.push(`${type}: ${ticker} · ${sourceId}`);
    } else if (ticker) {
      out.push(`${type}: ${ticker}`);
    } else if (sourceId) {
      out.push(`${type}: ${sourceId}`);
    } else {
      out.push(type);
    }
  }
  return Array.from(new Set(out)).slice(0, 8);
}

export default function PricesPage() {
  const [date, setDate] = useState(todayIsoDate());
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<SortMode>("change_desc");
  const [viewMode, setViewMode] = useState<ViewMode>("all_tracked");

  const prices = useQuery({
    queryKey: ["prices-daily", date],
    queryFn: () => fetchDailyPrices(date),
    refetchInterval: 30000,
    staleTime: 30000,
  });
  const sentiment = useQuery({
    queryKey: ["sentiment-weekly", "story", 100],
    queryFn: () => fetchWeeklySentiment({ limit: 100 }),
    refetchInterval: 60000,
    staleTime: 60000,
  });
  const patternSummary = useQuery({
    queryKey: ["pattern-summary", "story"],
    queryFn: fetchPatternSummary,
    refetchInterval: 60000,
    staleTime: 60000,
  });
  const announcementStats = useQuery({
    queryKey: ["announcement-stats", "story"],
    queryFn: fetchAnnouncementStats,
    refetchInterval: 60000,
    staleTime: 60000,
  });
  const latestDailyReport = useQuery({
    queryKey: ["report-latest", "story", "daily"],
    queryFn: () => fetchLatestReport("daily"),
    refetchInterval: 60000,
    staleTime: 60000,
  });
  const narratorStory = useQuery({
    queryKey: ["stories-latest", "market", "prices"],
    queryFn: () => fetchLatestStory({ scope: "market", context: "prices" }),
    refetchInterval: 30000,
    staleTime: 30000,
  });
  const universe = useQuery({
    queryKey: ["universe-summary", "prices"],
    queryFn: fetchUniverseSummary,
    refetchInterval: 60000,
    staleTime: 60000,
  });

  const pricedRows = useMemo(() => {
    const q = query.trim().toUpperCase();
    return (prices.data?.items || [])
      .map((row) => {
        const open = row.open ?? null;
        const close = row.close ?? null;
        const changePct =
          open !== null && close !== null && open > 0 ? ((close - open) / open) * 100 : null;
        return { ...row, changePct };
      })
      .filter((row) => {
        if (!q) return true;
        return row.ticker.toUpperCase().includes(q);
      });
  }, [prices.data?.items, query]);
  const enrichedRows = useMemo(() => {
    if (viewMode !== "all_tracked") return pricedRows;
    const trackedTickers = universe.data?.tickers || [];
    if (!trackedTickers.length) return pricedRows;

    const existing = new Set(pricedRows.map((row) => row.ticker.toUpperCase()));
    const missingRows = trackedTickers
      .filter((ticker) => !existing.has(ticker.toUpperCase()))
      .filter((ticker) => {
        const q = query.trim().toUpperCase();
        if (!q) return true;
        return ticker.toUpperCase().includes(q);
      })
      .map((ticker) => ({
        ticker,
        close: null,
        open: null,
        high: null,
        low: null,
        volume: null,
        currency: "KES",
        source_id: null,
        changePct: null,
      }));
    return [...pricedRows, ...missingRows];
  }, [pricedRows, query, universe.data?.tickers, viewMode]);

  const rows = useMemo(() => {
    const out = [...enrichedRows];
    out.sort((a, b) => {
      if (sort === "ticker_asc") return a.ticker.localeCompare(b.ticker);
      if (sort === "ticker_desc") return b.ticker.localeCompare(a.ticker);
      if (sort === "change_asc") return (a.changePct ?? -9999) - (b.changePct ?? -9999);
      if (sort === "change_desc") return (b.changePct ?? -9999) - (a.changePct ?? -9999);
      return (b.volume ?? 0) - (a.volume ?? 0);
    });
    return out;
  }, [enrichedRows, sort]);

  const stats = useMemo(() => {
    let advancers = 0;
    let decliners = 0;
    let totalVolume = 0;
    for (const item of pricedRows) {
      if ((item.open ?? 0) > 0 && (item.close ?? 0) > (item.open ?? 0)) advancers += 1;
      if ((item.open ?? 0) > 0 && (item.close ?? 0) < (item.open ?? 0)) decliners += 1;
      totalVolume += Number(item.volume ?? 0);
    }
    return {
      total: pricedRows.length,
      advancers,
      decliners,
      breadth: advancers - decliners,
      totalVolume,
    };
  }, [pricedRows]);
  const trackedNse = universe.data?.nse_tickers || 0;
  const coveragePct = trackedNse > 0 ? (stats.total / trackedNse) * 100 : null;

  const localStory = useMemo(() => {
    const analystContext =
      latestDailyReport.data?.item?.human_summary_v2?.plain_summary ||
      latestDailyReport.data?.item?.human_summary?.plain_summary ||
      null;
    return buildMarketStory({
      date,
      prices: prices.data?.items || [],
      sentiment: sentiment.data?.items || [],
      patterns: patternSummary.data || undefined,
      announcements: announcementStats.data || undefined,
      analystContext,
    });
  }, [
    announcementStats.data,
    date,
    latestDailyReport.data?.item?.human_summary?.plain_summary,
    latestDailyReport.data?.item?.human_summary_v2?.plain_summary,
    patternSummary.data,
    prices.data?.items,
    sentiment.data?.items,
  ]);

  const remoteStory = narratorStory.data?.item;
  const usingLocalFallback = narratorStory.isError || !remoteStory;
  const story = usingLocalFallback
    ? {
      headline: localStory.headline,
      paragraphs: localStory.paragraphs,
      evidence: localStory.evidence,
      globalDrivers: [] as Array<{
        headline?: string;
        theme?: string;
        kenya_impact_score?: number;
        source_id?: string | null;
        signal_class?: string | null;
        summary?: string;
        affected_sectors?: string[];
        transmission_channels?: string[];
      }>,
      generatedAt: null as string | null,
    }
    : {
      headline: remoteStory.headline || remoteStory.title || localStory.headline,
      paragraphs:
        remoteStory.paragraphs && remoteStory.paragraphs.length > 0
          ? remoteStory.paragraphs
          : localStory.paragraphs,
      evidence: toEvidenceChips(remoteStory.evidence_refs || []),
      globalDrivers: (remoteStory.global_drivers || []).slice(0, 3),
      generatedAt: remoteStory.generated_at || null,
    };

  return (
    <div className="space-y-4">
      <Panel>
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-base font-semibold text-ink">Prices · Company Data (Agent A)</h1>
            <p className="mt-1 text-xs text-muted">
              Live pricing monitor with market-story intelligence from Agent F.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            {usingLocalFallback ? (
              <span className="rounded border border-amber-700/80 px-2 py-1 text-amber-300">
                Fallback: Local Deterministic
              </span>
            ) : (
              <span className="rounded border border-emerald-700/80 px-2 py-1 text-emerald-300">
                Narrator Source: Agent F
              </span>
            )}
            <span className="text-ink-faint">
              {story.generatedAt ? `Generated ${fmtDateTime(story.generatedAt)}` : "Generated from current live stack"}
            </span>
          </div>
        </div>
      </Panel>

      <Panel>
        <div className="grid gap-3 grid-cols-2 md:grid-cols-4">
          <div>
            <label className="mb-1 block text-[11px] uppercase tracking-[0.12em] text-ink-faint">Date</label>
            <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
          </div>
          <div>
            <label className="mb-1 block text-[11px] uppercase tracking-[0.12em] text-ink-faint">Ticker Filter</label>
            <Input
              placeholder="e.g. SCOM, KCB, EABL"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
          <div>
            <label className="mb-1 block text-[11px] uppercase tracking-[0.12em] text-ink-faint">Sort</label>
            <Select value={sort} onChange={(e) => setSort(e.target.value as SortMode)}>
              <option value="change_desc">Change % (High to Low)</option>
              <option value="change_asc">Change % (Low to High)</option>
              <option value="volume_desc">Volume (High to Low)</option>
              <option value="ticker_asc">Ticker (A-Z)</option>
              <option value="ticker_desc">Ticker (Z-A)</option>
            </Select>
          </div>
          <div>
            <label className="mb-1 block text-[11px] uppercase tracking-[0.12em] text-ink-faint">View</label>
            <Select value={viewMode} onChange={(e) => setViewMode(e.target.value as ViewMode)}>
              <option value="all_tracked">All Tracked Tickers</option>
              <option value="priced_only">Priced Only</option>
            </Select>
          </div>
        </div>
      </Panel>

      <Panel title="Session Snapshot">
        <div className="grid gap-3 [grid-template-columns:repeat(auto-fit,minmax(170px,1fr))]">
          <StatCard label="Tickers Loaded" value={fmtNumber(stats.total)} tone="brand" />
          <StatCard label="Rows Visible" value={fmtNumber(rows.length)} tone="brand" />
          <StatCard label="Tracked NSE Tickers" value={fmtNumber(trackedNse)} tone="neutral" />
          <StatCard
            label="Coverage"
            value={coveragePct === null ? "-" : `${fmtDecimal(coveragePct, 1)}%`}
            hint="Loaded vs tracked NSE universe"
            tone={coveragePct !== null && coveragePct >= 60 ? "success" : "warning"}
          />
          <StatCard label="Advancers" value={fmtNumber(stats.advancers)} tone="success" />
          <StatCard label="Decliners" value={fmtNumber(stats.decliners)} tone="warning" />
          <StatCard
            label="Net Breadth"
            value={stats.breadth >= 0 ? `+${fmtNumber(stats.breadth)}` : fmtNumber(stats.breadth)}
            tone={stats.breadth >= 0 ? "success" : "warning"}
          />
          <StatCard label="Total Volume" value={fmtNumber(stats.totalVolume)} tone="neutral" />
        </div>
      </Panel>

      <Panel className="space-y-3 self-start">
        <div className="flex items-center justify-between border-b border-line pb-2">
          <h2 className="text-sm font-semibold text-ink">Market Story · Today&apos;s Session</h2>
          <Badge value={usingLocalFallback ? "partial" : "success"} />
        </div>
        {prices.isLoading ? (
          <div className="text-sm text-muted">Building market story from live feeds...</div>
        ) : prices.isError ? (
          <div className="text-sm text-red-300">Market story unavailable because price data failed to load.</div>
        ) : rows.length === 0 ? (
          <div className="text-sm text-muted">Market story appears when company rows are available for this date.</div>
        ) : (
          <div className="space-y-3">
            <p className="text-sm font-semibold leading-6 text-ink">{story.headline}</p>
            {story.paragraphs.map((paragraph, idx) => (
              <p key={`story-p-${idx}`} className="text-sm leading-6 text-ink-soft">
                {paragraph}
              </p>
            ))}
            {story.evidence.length > 0 ? (
              <div>
                <div className="mb-1 text-[11px] uppercase tracking-[0.12em] text-ink-faint">Evidence</div>
                <div className="flex flex-wrap gap-2">
                  {story.evidence.map((item) => (
                    <span
                      key={item}
                      className="inline-flex rounded-full border border-line bg-elevated px-2.5 py-1 text-xs text-ink-soft"
                    >
                      {item}
                    </span>
                  ))}
                </div>
              </div>
            ) : null}
            {story.globalDrivers.length > 0 ? (
              <div className="pt-1">
                <div className="mb-2 text-[11px] uppercase tracking-[0.12em] text-ink-faint">Global Drivers of Kenya Today</div>
                <div className="space-y-2">
                  {story.globalDrivers.map((driver, idx) => (
                    <div key={`${driver.theme || "theme"}-${idx}`} className="rounded-lg border border-line bg-panel-soft p-2.5">
                      <div className="flex flex-wrap items-center gap-2 text-xs">
                        <Badge value={(driver.theme || "global").replace(/_/g, " ")} />
                        <span className="text-cyan-300">
                          Kenya Impact {driver.kenya_impact_score ?? 0}
                        </span>
                        {driver.source_id ? (
                          <span className="rounded border border-line px-1.5 py-0.5 text-[10px] text-ink-soft">
                            {driver.source_id}
                          </span>
                        ) : null}
                      </div>
                      <p className="mt-1 text-sm text-ink">{driver.headline || driver.summary || "-"}</p>
                      {driver.transmission_channels && driver.transmission_channels.length > 0 ? (
                        <p className="mt-1 text-xs text-muted">
                          Channels: {driver.transmission_channels.slice(0, 3).join(", ")}
                        </p>
                      ) : null}
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
          </div>
        )}
      </Panel>

      <Panel className="space-y-3 self-start">
        <div className="flex items-center justify-between border-b border-line pb-2">
          <h2 className="text-sm font-semibold text-ink">Company Price Table</h2>
          <span className="text-xs text-ink-faint">{fmtNumber(rows.length)} rows</span>
        </div>

        {prices.isLoading ? (
          <div className="text-sm text-muted">Loading company prices...</div>
        ) : prices.isError ? (
          <div className="text-sm text-red-300">Failed to load prices. Check Agent A / gateway API.</div>
        ) : rows.length === 0 ? (
          <div className="text-sm text-muted">No company prices found for selected date/filter.</div>
        ) : (
          <div className="max-h-[calc(100vh-380px)] overflow-auto rounded-xl border border-line">
            <table className="w-full min-w-[900px] text-sm">
              <thead className="sticky top-0 z-10 bg-inset/95">
                <tr className="text-left text-[11px] uppercase tracking-[0.12em] text-ink-faint">
                  <th className="px-3 py-2">Ticker</th>
                  <th className="px-2 py-2">Close</th>
                  <th className="px-2 py-2">Open</th>
                  <th className="px-2 py-2">High</th>
                  <th className="px-2 py-2">Low</th>
                  <th className="px-2 py-2">Volume</th>
                  <th className="px-2 py-2">Change %</th>
                  <th className="px-3 py-2">Source</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr key={`${row.ticker}-${row.source_id || "source"}`} className="border-t border-line hover:bg-hover">
                    <td className="px-3 py-2 font-medium text-ink">{row.ticker}</td>
                    <td className="px-2 py-2 text-ink-soft">{fmtDecimal(row.close ?? null, 2)}</td>
                    <td className="px-2 py-2 text-ink-soft">{fmtDecimal(row.open ?? null, 2)}</td>
                    <td className="px-2 py-2 text-ink-soft">{fmtDecimal(row.high ?? null, 2)}</td>
                    <td className="px-2 py-2 text-ink-soft">{fmtDecimal(row.low ?? null, 2)}</td>
                    <td className="px-2 py-2 text-ink-soft">{fmtNumber(row.volume ?? null)}</td>
                    <td className={`px-2 py-2 ${row.changePct !== null && row.changePct >= 0 ? "text-green-300" : "text-amber-300"}`}>
                      {row.changePct === null ? "-" : `${fmtDecimal(row.changePct, 2)}%`}
                    </td>
                    <td className="px-3 py-2 text-muted">{row.source_id || "-"}</td>
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
