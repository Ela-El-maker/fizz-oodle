"use client";

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  fetchAnnouncements,
  fetchAnnouncementInsight,
  fetchAnnouncementStats,
  refreshAnnouncementContext,
} from "@/entities/announcement/api";
import { fetchUniverseSummary } from "@/entities/universe/api";
import { Panel } from "@/shared/ui/Panel";
import { StatCard } from "@/shared/ui/StatCard";
import { Input } from "@/shared/ui/Input";
import { Select } from "@/shared/ui/Select";
import { Badge } from "@/shared/ui/Badge";
import { fmtDateTime, fmtDecimal, fmtNumber } from "@/shared/lib/format";

type SortKey =
  | "announcement_date"
  | "ticker"
  | "announcement_type"
  | "severity"
  | "headline"
  | "source_id"
  | "status";

const DEDUPE_STOP_WORDS = new Set([
  "a",
  "an",
  "the",
  "and",
  "or",
  "for",
  "in",
  "on",
  "to",
  "of",
  "by",
  "with",
  "at",
  "from",
]);

function normalizeText(value: string | null | undefined): string {
  return (value || "-").replace(/_/g, " ").replace(/\s+/g, " ").trim();
}

function toStatus(item: {
  alerted?: boolean | null;
  ticker?: string | null;
}): "alerted" | "unalerted" | "unmapped" {
  if (!item.ticker) return "unmapped";
  return item.alerted ? "alerted" : "unalerted";
}

function announcementDedupeKey(item: {
  ticker?: string | null;
  announcement_type?: string | null;
  headline?: string | null;
  canonical_url?: string | null;
  url?: string | null;
}) {
  const ticker = (item.ticker || "unmapped").toUpperCase();
  const annType = (item.announcement_type || "other").toLowerCase();
  const canonical = (item.canonical_url || item.url || "").trim().toLowerCase();
  const normalizedHeadline = (item.headline || "")
    .toLowerCase()
    .replace(/[^a-z0-9\s]/g, " ")
    .split(/\s+/)
    .filter((token) => token && !DEDUPE_STOP_WORDS.has(token))
    .join(" ")
    .slice(0, 180);
  return {
    canonicalKey: canonical ? `${ticker}|${annType}|url:${canonical}` : null,
    headlineKey: `${ticker}|${annType}|headline:${normalizedHeadline}`,
  };
}

function compareStrings(a: string, b: string, dir: "asc" | "desc"): number {
  const base = a.localeCompare(b);
  return dir === "asc" ? base : -base;
}

function compareNumbers(a: number, b: number, dir: "asc" | "desc"): number {
  const base = a - b;
  return dir === "asc" ? base : -base;
}

function severityTone(value: string | null | undefined): string {
  const v = (value || "").toLowerCase();
  if (v === "high") return "fail";
  if (v === "medium") return "partial";
  return "success";
}

function DetailBlock({ title, value }: { title: string; value: string }) {
  return (
    <div className="rounded-lg border border-line bg-panel-soft p-3">
      <div className="mb-1 text-[11px] uppercase tracking-[0.12em] text-ink-faint">{title}</div>
      <p className="text-sm leading-6 text-ink">{value || "-"}</p>
    </div>
  );
}

export default function AnnouncementsPage() {
  const queryClient = useQueryClient();

  const [ticker, setTicker] = useState("all");
  const [type, setType] = useState("all");
  const [laneFilter, setLaneFilter] = useState<"kenya_core" | "global_outside" | "all">("kenya_core");
  const [statusFilter, setStatusFilter] = useState("mapped");
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("announcement_date");
  const [sortDir, setSortDir] = useState<"asc" | "desc">("desc");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [insightExpanded, setInsightExpanded] = useState(false);

  useEffect(() => {
    if (laneFilter === "global_outside" && statusFilter === "mapped") {
      setStatusFilter("all");
    }
  }, [laneFilter, statusFilter]);

  const stats = useQuery({
    queryKey: ["announcement-stats", "page"],
    queryFn: fetchAnnouncementStats,
    refetchInterval: 30000,
    staleTime: 30000,
  });

  const list = useQuery({
    queryKey: ["announcements", "page", 250, laneFilter],
    queryFn: () =>
      fetchAnnouncements({
        limit: 250,
        scope: laneFilter === "kenya_core" ? undefined : laneFilter,
      }),
    refetchInterval: 15000,
    staleTime: 15000,
  });
  const universe = useQuery({
    queryKey: ["universe-summary", "announcements"],
    queryFn: fetchUniverseSummary,
    refetchInterval: 60000,
    staleTime: 60000,
  });

  const items = useMemo(() => list.data?.items ?? [], [list.data?.items]);

  const tickerOptions = useMemo(() => {
    const set = new Set<string>();
    for (const item of items) {
      if (item.ticker) set.add(item.ticker);
    }
    return Array.from(set).sort();
  }, [items]);

  const typeOptions = useMemo(() => {
    const set = new Set<string>();
    for (const item of items) {
      if (item.announcement_type) set.add(item.announcement_type);
    }
    return Array.from(set).sort();
  }, [items]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    const matches = items.filter((item) => {
      if (ticker !== "all" && item.ticker !== ticker) return false;
      if (type !== "all" && item.announcement_type !== type) return false;
      if (laneFilter === "kenya_core" && item.scope === "global_outside") return false;
      if (laneFilter === "global_outside" && item.scope !== "global_outside") return false;
      if (statusFilter === "mapped" && !item.ticker) return false;
      if (statusFilter !== "all" && statusFilter !== "mapped" && toStatus(item) !== statusFilter) return false;
      if (!q) return true;
      const haystack = [
        item.headline,
        item.ticker,
        item.company,
        item.source_id,
        item.announcement_type,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      return haystack.includes(q);
    });

    const seenCanonical = new Set<string>();
    const seenHeadline = new Set<string>();
    const deduped: typeof matches = [];
    for (const item of matches) {
      const { canonicalKey, headlineKey } = announcementDedupeKey(item);
      if ((canonicalKey && seenCanonical.has(canonicalKey)) || seenHeadline.has(headlineKey)) continue;
      if (canonicalKey) seenCanonical.add(canonicalKey);
      seenHeadline.add(headlineKey);
      deduped.push(item);
    }
    return deduped;
  }, [items, laneFilter, search, ticker, type, statusFilter]);

  const sorted = useMemo(() => {
    const rows = [...filtered];
    rows.sort((a, b) => {
      if (sortKey === "announcement_date") {
        return compareNumbers(
          Date.parse(a.announcement_date || "1970-01-01T00:00:00Z"),
          Date.parse(b.announcement_date || "1970-01-01T00:00:00Z"),
          sortDir,
        );
      }
      if (sortKey === "status") {
        return compareStrings(toStatus(a), toStatus(b), sortDir);
      }
      if (sortKey === "ticker") {
        return compareStrings((a.ticker || "UNMAPPED").toUpperCase(), (b.ticker || "UNMAPPED").toUpperCase(), sortDir);
      }
      if (sortKey === "announcement_type") {
        return compareStrings(a.announcement_type || "other", b.announcement_type || "other", sortDir);
      }
      if (sortKey === "severity") {
        return compareStrings(a.severity || "low", b.severity || "low", sortDir);
      }
      if (sortKey === "headline") {
        return compareStrings(a.headline || "", b.headline || "", sortDir);
      }
      return compareStrings(a.source_id || "", b.source_id || "", sortDir);
    });
    return rows;
  }, [filtered, sortDir, sortKey]);

  useEffect(() => {
    if (!sorted.length) {
      setSelectedId(null);
      return;
    }
    if (!selectedId || !sorted.some((item) => item.announcement_id === selectedId)) {
      setSelectedId(sorted[0].announcement_id);
    }
  }, [selectedId, sorted]);

  const selected = useMemo(
    () => sorted.find((item) => item.announcement_id === selectedId) || null,
    [selectedId, sorted],
  );

  const insight = useQuery({
    queryKey: ["announcement-insight", selected?.announcement_id || ""],
    queryFn: () =>
      fetchAnnouncementInsight(selected?.announcement_id || "", {
        refresh_context_if_needed: true,
      }),
    enabled: !!selected?.announcement_id,
    staleTime: 5 * 60 * 1000,
  });

  const refreshContext = useMutation({
    mutationFn: () => refreshAnnouncementContext(selected?.announcement_id || ""),
    onSuccess: async () => {
      if (!selected?.announcement_id) return;
      await queryClient.invalidateQueries({
        queryKey: ["announcement-insight", selected.announcement_id],
      });
      await insight.refetch();
    },
  });

  function toggleSort(next: SortKey) {
    if (sortKey === next) {
      setSortDir((prev) => (prev === "asc" ? "desc" : "asc"));
      return;
    }
    setSortKey(next);
    setSortDir(next === "announcement_date" ? "desc" : "asc");
  }

  const insightItem = insight.data?.item;
  const insightSection = insightItem?.insight;
  const insightQuality = insightItem?.quality;
  const insightLinks = (insightItem?.research_links || []).filter((link) => !!link.url);
  const unmappedCount = items.filter((item) => !item.ticker).length;
  const mappedRowsCount = items.length - unmappedCount;
  const mappedTickerCount = useMemo(() => {
    const set = new Set<string>();
    for (const row of items) {
      if (row.ticker) set.add(row.ticker.toUpperCase());
    }
    return set.size;
  }, [items]);
  const fallbackGlobalThreshold = 60;
  const resolvedGlobalThreshold = stats.data?.global_impact_threshold ?? fallbackGlobalThreshold;
  const resolvedTotal = stats.data?.total ?? items.length;
  const resolvedAlerted = stats.data?.alerted ?? items.filter((item) => !!item.alerted).length;
  const resolvedUnalerted = stats.data?.unalerted ?? items.filter((item) => !item.alerted).length;
  const resolvedGlobalOutsideTotal =
    stats.data?.global_outside_total ?? items.filter((item) => item.scope === "global_outside").length;
  const resolvedHighImpactGlobal =
    stats.data?.high_impact_global_total ??
    items.filter(
      (item) =>
        item.scope === "global_outside" &&
        Number(item.kenya_impact_score ?? 0) >= Number(resolvedGlobalThreshold),
    ).length;
  const trackedNse = universe.data?.nse_tickers || 0;
  const mappedCoveragePct = trackedNse > 0 ? (mappedTickerCount / trackedNse) * 100 : null;

  return (
    <div className="space-y-4">
      <Panel>
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-base font-semibold text-ink">Announcements · Company Signals (Agent B)</h1>
            <p className="mt-1 text-xs text-muted">
              Institutional announcement monitor with structured intelligence synthesis.
            </p>
          </div>
          <div className="text-xs text-ink-faint">Auto-refresh: 15s feed • 30s summary</div>
        </div>
      </Panel>

      <div className="grid gap-3 grid-cols-2 md:grid-cols-3 xl:grid-cols-6">
        <StatCard
          label="Total Announcements"
          value={fmtNumber(resolvedTotal)}
          hint="Classified in current view window"
          tone="neutral"
        />
        <StatCard
          label="Alerted"
          value={fmtNumber(resolvedAlerted)}
          hint="Market-relevant alerts dispatched"
          tone="success"
        />
        <StatCard
          label="Unalerted"
          value={fmtNumber(resolvedUnalerted)}
          hint="Tracked but not escalated"
          tone="warning"
        />
        <StatCard
          label="Rows Visible"
          value={fmtNumber(sorted.length)}
          hint="Filtered and de-duplicated feed"
          tone="brand"
        />
        <StatCard
          label="Tracked NSE Tickers"
          value={fmtNumber(trackedNse)}
          hint={
            mappedCoveragePct === null
              ? "Universe summary unavailable"
              : `${fmtDecimal(mappedCoveragePct, 1)}% mapped ticker coverage`
          }
          tone="neutral"
        />
        <StatCard
          label="Global Outside (High Impact)"
          value={`${fmtNumber(resolvedHighImpactGlobal)}/${fmtNumber(resolvedGlobalOutsideTotal)}`}
          hint={`Threshold >= ${fmtNumber(resolvedGlobalThreshold)}`}
          tone="warning"
        />
      </div>

      <Panel>
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted">
          <div>
            Mapping Quality: <span className="text-ink">{fmtNumber(mappedTickerCount)}/{fmtNumber(trackedNse)}</span> mapped tickers
            {" "}· Rows mapped: <span className="text-ink">{fmtNumber(mappedRowsCount)}/{fmtNumber(items.length)}</span>
            {" "}· Unmapped rows: <span className="text-amber-300">{fmtNumber(unmappedCount)}</span>
          </div>
          <div>
            {stats.isError
              ? "Stats API unavailable; using live feed-derived counts."
              : "Tip: default view is "}
            {!stats.isError ? <span className="text-ink">Mapped Only</span> : null}
          </div>
        </div>
      </Panel>

      <div
        className={`grid items-start gap-4 ${insightExpanded
          ? "xl:grid-cols-[minmax(0,1.45fr)_minmax(0,1fr)]"
          : "xl:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]"
          }`}
      >
        <Panel className="min-w-0 space-y-4 self-start overflow-hidden">
          <div className="grid gap-3 grid-cols-2 md:grid-cols-3 lg:grid-cols-5">
            <div>
              <label className="mb-1 block text-[11px] uppercase tracking-[0.12em] text-ink-faint">Ticker</label>
              <Select value={ticker} onChange={(e) => setTicker(e.target.value)}>
                <option value="all">All</option>
                {tickerOptions.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </Select>
            </div>
            <div>
              <label className="mb-1 block text-[11px] uppercase tracking-[0.12em] text-ink-faint">Category</label>
              <Select value={type} onChange={(e) => setType(e.target.value)}>
                <option value="all">All</option>
                {typeOptions.map((value) => (
                  <option key={value} value={value}>
                    {normalizeText(value)}
                  </option>
                ))}
              </Select>
            </div>
            <div>
              <label className="mb-1 block text-[11px] uppercase tracking-[0.12em] text-ink-faint">Status</label>
              <Select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
                <option value="all">All</option>
                <option value="mapped">Mapped only</option>
                <option value="alerted">Alerted</option>
                <option value="unalerted">Unalerted</option>
                <option value="unmapped">Unmapped</option>
              </Select>
            </div>
            <div>
              <label className="mb-1 block text-[11px] uppercase tracking-[0.12em] text-ink-faint">Lane</label>
              <Select value={laneFilter} onChange={(e) => setLaneFilter(e.target.value as "kenya_core" | "global_outside" | "all")}>
                <option value="kenya_core">Kenya Core</option>
                <option value="global_outside">Global Outside</option>
                <option value="all">All Lanes</option>
              </Select>
            </div>
            <div>
              <label className="mb-1 block text-[11px] uppercase tracking-[0.12em] text-ink-faint">Search</label>
              <Input
                placeholder="Headline, ticker, source..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
          </div>

          <div className="rounded-xl border border-line">
            <div className="border-b border-line px-3 py-2 text-xs uppercase tracking-[0.12em] text-ink-faint">
              Announcement Feed
            </div>
            {list.isLoading ? (
              <div className="p-4 text-sm text-muted">Loading announcements...</div>
            ) : list.isError ? (
              <div className="p-4 text-sm text-red-300">Failed to load announcement feed.</div>
            ) : sorted.length === 0 ? (
              <div className="p-4 text-sm text-muted">No announcements match your filters.</div>
            ) : (
              <div className="max-h-[60vh] overflow-auto xl:max-h-[calc(100vh-360px)]">
                <table className="w-full min-w-[700px] text-sm">
                  <thead className="sticky top-0 z-10 bg-inset/95">
                    <tr className="text-left text-[11px] uppercase tracking-[0.12em] text-ink-faint">
                      <th className="px-3 py-2">
                        <button type="button" className="hover:text-ink-soft" onClick={() => toggleSort("announcement_date")}>
                          Time
                        </button>
                      </th>
                      <th className="px-2 py-2">
                        <button type="button" className="hover:text-ink-soft" onClick={() => toggleSort("ticker")}>
                          Ticker
                        </button>
                      </th>
                      <th className="px-2 py-2">
                        <button type="button" className="hover:text-ink-soft" onClick={() => toggleSort("announcement_type")}>
                          Category
                        </button>
                      </th>
                      <th className="px-2 py-2">
                        <button type="button" className="hover:text-ink-soft" onClick={() => toggleSort("severity")}>
                          Severity
                        </button>
                      </th>
                      <th className="px-2 py-2">
                        <button type="button" className="hover:text-ink-soft" onClick={() => toggleSort("headline")}>
                          Headline
                        </button>
                      </th>
                      <th className="px-2 py-2">
                        <button type="button" className="hover:text-ink-soft" onClick={() => toggleSort("source_id")}>
                          Source
                        </button>
                      </th>
                      <th className="px-3 py-2">
                        <button type="button" className="hover:text-ink-soft" onClick={() => toggleSort("status")}>
                          Status
                        </button>
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {sorted.map((row) => {
                      const isSelected = row.announcement_id === selected?.announcement_id;
                      const status = toStatus(row);
                      return (
                        <tr
                          key={row.announcement_id}
                          className={`cursor-pointer border-t border-line ${isSelected ? "bg-blue-500/10" : "hover:bg-hover"
                            }`}
                          onClick={() => setSelectedId(row.announcement_id)}
                        >
                          <td className="px-3 py-2 text-ink-soft">{fmtDateTime(row.announcement_date)}</td>
                          <td className="px-2 py-2 text-ink">
                            <span className={`rounded-md border px-2 py-0.5 text-xs ${row.ticker
                              ? "border-line bg-elevated"
                              : "border-amber-700/60 bg-amber-900/20 text-amber-200"
                              }`}>
                              {(row.ticker || "MACRO").toUpperCase()}
                            </span>
                          </td>
                          <td className="px-2 py-2 text-ink-soft">
                            <div className="flex flex-wrap items-center gap-1.5">
                              <span>{normalizeText(row.announcement_type)}</span>
                              {row.theme ? (
                                <span className="rounded border border-line bg-elevated/50 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-ink-soft">
                                  {normalizeText(row.theme)}
                                </span>
                              ) : null}
                              {row.scope === "global_outside" ? (
                                <span className="rounded border border-cyan-700/70 bg-cyan-900/20 px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-cyan-200">
                                  {row.source_scope_label || "GLOBAL OUTSIDE"}
                                </span>
                              ) : null}
                            </div>
                          </td>
                          <td className="px-2 py-2">
                            <div className="flex items-center gap-1.5">
                              <Badge value={severityTone(row.severity)} />
                              {row.scope === "global_outside" ? (
                                <span className="rounded border border-line px-1.5 py-0.5 text-[10px] text-ink-soft">
                                  K-Impact {fmtNumber(row.kenya_impact_score)}
                                </span>
                              ) : null}
                            </div>
                          </td>
                          <td className="max-w-[260px] px-2 py-2 text-ink xl:max-w-[420px]">
                            <div className="truncate">{row.headline || "(no headline)"}</div>
                          </td>
                          <td className="px-2 py-2 text-muted">{normalizeText(row.source_id)}</td>
                          <td className="px-3 py-2">
                            <Badge value={status} />
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </Panel>

        <Panel className="min-w-0 space-y-3 self-start">
          <div className="flex items-start justify-between gap-2 border-b border-line pb-3">
            <div>
              <h2 className="text-sm font-semibold text-ink">Selected Announcement Intelligence</h2>
              <p className="mt-1 text-xs text-ink-faint">Agent F evidence-backed interpretation panel</p>
            </div>
            <div className="flex items-center gap-2">
              {selected ? <Badge value={toStatus(selected)} /> : null}
              <button
                type="button"
                className="rounded-md border border-line px-2.5 py-1 text-xs text-ink hover:bg-elevated"
                onClick={() => setInsightExpanded((prev) => !prev)}
              >
                {insightExpanded ? "Compact Panel" : "Expand Panel"}
              </button>
            </div>
          </div>

          <div className="max-h-[70vh] space-y-3 overflow-y-auto pr-1 xl:max-h-[calc(100vh-300px)]">
            {!selected ? (
              <div className="text-sm text-muted">Select a table row to open structured analysis.</div>
            ) : (
              <>
                <div className="rounded-lg border border-line bg-panel-soft p-3">
                  <div className="mb-1 text-[11px] uppercase tracking-[0.12em] text-ink-faint">Headline</div>
                  <p className="text-sm font-medium leading-6 text-ink">{selected.headline || "(no headline)"}</p>
                  <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-ink-faint">
                    <Badge value={(selected.ticker || "unmapped").toLowerCase()} />
                    <span>{normalizeText(selected.source_id)}</span>
                    <span>•</span>
                    <span>{fmtDateTime(selected.announcement_date)}</span>
                  </div>
                </div>

                {insight.isLoading ? (
                  <div className="space-y-2 rounded-lg border border-line bg-panel-soft p-3">
                    <div className="h-4 w-1/2 animate-pulse rounded bg-line" />
                    <div className="h-3 w-full animate-pulse rounded bg-elevated" />
                    <div className="h-3 w-5/6 animate-pulse rounded bg-elevated" />
                  </div>
                ) : insight.isError ? (
                  <div className="rounded-lg border border-red-900/60 bg-red-950/20 p-3 text-sm text-red-300">
                    Failed to load intelligence for this announcement.
                  </div>
                ) : !insightSection ? (
                  <div className="rounded-lg border border-line bg-panel-soft p-3 text-sm text-muted">
                    No intelligence payload is available for this announcement yet.
                  </div>
                ) : (
                  <div className="space-y-3">
                    <DetailBlock title="What Happened" value={insightSection.what_happened || "-"} />
                    <DetailBlock title="Why It Matters" value={insightSection.why_it_matters || "-"} />
                    <DetailBlock title="Market Impact" value={insightSection.market_impact || "-"} />
                    <DetailBlock title="Sector Impact" value={insightSection.sector_impact || "-"} />
                    <DetailBlock title="Competitor Watch" value={insightSection.competitor_watch || "-"} />

                    <div className="rounded-lg border border-line bg-panel-soft p-3">
                      <div className="mb-1 text-[11px] uppercase tracking-[0.12em] text-ink-faint">What To Watch Next</div>
                      {(insightSection.what_to_watch_next || []).length === 0 ? (
                        <p className="text-sm text-ink-soft">-</p>
                      ) : (
                        <ul className="list-disc space-y-1 pl-5 text-sm text-ink">
                          {(insightSection.what_to_watch_next || []).slice(0, 5).map((line) => (
                            <li key={line}>{line}</li>
                          ))}
                        </ul>
                      )}
                    </div>

                    <div className="rounded-lg border border-line bg-panel-soft p-3">
                      <div className="mb-2 text-[11px] uppercase tracking-[0.12em] text-ink-faint">Research Links</div>
                      <div className="flex flex-wrap gap-2">
                        {insightLinks.length > 0 ? (
                          insightLinks.map((link) => (
                            <a
                              key={`${selected.announcement_id}-${link.label}-${link.url}`}
                              href={link.url || "#"}
                              target="_blank"
                              rel="noreferrer"
                              className="rounded border border-line px-2.5 py-1 text-xs text-ink hover:bg-elevated"
                            >
                              {link.label || "Open"}
                            </a>
                          ))
                        ) : (
                          <>
                            {selected.url ? (
                              <a
                                href={selected.url}
                                target="_blank"
                                rel="noreferrer"
                                className="rounded border border-line px-2.5 py-1 text-xs text-ink hover:bg-elevated"
                              >
                                Source
                              </a>
                            ) : null}
                            {selected.canonical_url && selected.canonical_url !== selected.url ? (
                              <a
                                href={selected.canonical_url}
                                target="_blank"
                                rel="noreferrer"
                                className="rounded border border-line px-2.5 py-1 text-xs text-ink hover:bg-elevated"
                              >
                                Canonical
                              </a>
                            ) : null}
                          </>
                        )}
                      </div>
                    </div>
                  </div>
                )}

                <div className="rounded-lg border border-line bg-panel-soft p-3">
                  <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted">
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge value={insightItem?.status || "pending_data"} />
                      <span>
                        AI analysis: {insightQuality?.llm_used ? "enabled" : insightQuality?.fallback_mode || "fallback"}
                      </span>
                      <span>•</span>
                      <span>Generated: {fmtDateTime(insightItem?.generated_at)}</span>
                    </div>
                    <button
                      type="button"
                      className="rounded-md border border-line px-2.5 py-1 text-xs text-ink hover:bg-elevated disabled:cursor-not-allowed disabled:opacity-50"
                      onClick={() => refreshContext.mutate()}
                      disabled={refreshContext.isPending || !selected?.announcement_id}
                    >
                      {refreshContext.isPending ? "Refreshing..." : "Get More Context"}
                    </button>
                  </div>
                  {refreshContext.isError ? (
                    <div className="mt-2 text-xs text-red-300">Context refresh failed. Source may be unavailable.</div>
                  ) : null}
                </div>
              </>
            )}
          </div>
        </Panel>
      </div>
    </div>
  );
}
