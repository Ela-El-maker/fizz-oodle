"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchAnnouncements } from "@/entities/announcement/api";
import { fetchLatestStory } from "@/entities/story/api";
import { Panel } from "@/shared/ui/Panel";
import { Input } from "@/shared/ui/Input";
import { Select } from "@/shared/ui/Select";
import { Badge } from "@/shared/ui/Badge";
import { fmtDateTime, fmtNumber } from "@/shared/lib/format";

type LaneFilter = "all" | "kenya_core" | "global_outside";

const FEED_PAGE_SIZE = 20;

function cleanLabel(value: string | null | undefined): string {
  return (value || "-").replace(/_/g, " ").replace(/\s+/g, " ").trim();
}

function laneLabel(scope: string | null | undefined): string {
  const value = (scope || "kenya_core").toLowerCase();
  if (value === "global_outside") return "GLOBAL OUTSIDE";
  if (value === "kenya_extended") return "KENYA EXTENDED";
  return "KENYA CORE";
}

function isArchiveDisclosure(headline: string | null | undefined, sourceId: string | null | undefined): boolean {
  if ((sourceId || "").toLowerCase() !== "company_ir_pages") return false;
  const text = (headline || "").toLowerCase();
  const years = [...text.matchAll(/\b(20\d{2})\b/g)].map((m) => Number(m[1]));
  const minYear = years.length ? Math.min(...years) : null;
  const oldYear = minYear !== null && minYear <= new Date().getFullYear() - 2;
  const archivalWords = /(full year results|half year results|quarter \d|agm\s+\d{4}|voting results|notice and notes|proxy)/i.test(text);
  return oldYear || archivalWords;
}

function excerpt(value: string | null | undefined, max = 230): string {
  const text = (value || "").replace(/\s+/g, " ").trim();
  if (!text) return "No short brief available yet for this source item.";
  if (text.length <= max) return text;
  return `${text.slice(0, max).trim()}...`;
}

function sourceUrl(row: { canonical_url?: string | null; url?: string | null }): string | null {
  const url = row.canonical_url || row.url;
  if (!url) return null;
  if (/^https?:\/\//i.test(url)) return url;
  return null;
}

type SourcePulseItem = {
  sourceId: string;
  count: number;
  latestAt: string | null;
  latestHeadline: string;
  latestUrl: string | null;
};

export default function NewsIntelPage() {
  const [lane, setLane] = useState<LaneFilter>("all");
  const [theme, setTheme] = useState("all");
  const [onlyMapped, setOnlyMapped] = useState(false);
  const [includeArchive, setIncludeArchive] = useState(false);
  const [search, setSearch] = useState("");
  const [visibleCount, setVisibleCount] = useState(FEED_PAGE_SIZE);

  const feedContainerRef = useRef<HTMLDivElement | null>(null);
  const feedSentinelRef = useRef<HTMLDivElement | null>(null);

  const announcements = useQuery({
    queryKey: ["announcements", "news-intel", lane],
    queryFn: () =>
      fetchAnnouncements({
        limit: 400,
        scope: lane === "all" ? undefined : lane,
      }),
    refetchInterval: 15000,
    staleTime: 15000,
  });

  const marketStory = useQuery({
    queryKey: ["stories-latest", "market", "announcements", "news-intel"],
    queryFn: () => fetchLatestStory({ scope: "market", context: "announcements" }),
    refetchInterval: 30000,
    staleTime: 30000,
  });

  const items = useMemo(() => announcements.data?.items || [], [announcements.data?.items]);

  const themeOptions = useMemo(() => {
    const set = new Set<string>();
    for (const item of items) {
      if (item.theme) set.add(item.theme);
    }
    return Array.from(set).sort();
  }, [items]);

  const ranked = useMemo(() => {
    const q = search.trim().toLowerCase();
    const sorted = [...items].sort((a, b) => Date.parse(b.announcement_date || "") - Date.parse(a.announcement_date || ""));
    const deduped: typeof sorted = [];
    const seen = new Set<string>();

    for (const item of sorted) {
      const ticker = (item.ticker || "").trim().toUpperCase();
      if (theme !== "all" && (item.theme || "other") !== theme) continue;
      if (!includeArchive && isArchiveDisclosure(item.headline, item.source_id)) continue;
      if (onlyMapped && (!ticker || ticker === "UNMAPPED")) continue;

      if (q) {
        const haystack = [item.headline, item.ticker, item.source_id, item.theme, item.announcement_type, item.company]
          .filter(Boolean)
          .join(" ")
          .toLowerCase();
        if (!haystack.includes(q)) continue;
      }

      const key = [
        item.scope || "kenya_core",
        item.ticker || "UNMAPPED",
        (item.headline || "").toLowerCase().trim().slice(0, 120),
        item.source_id || "-",
      ].join("|");
      if (seen.has(key)) continue;
      seen.add(key);
      deduped.push(item);
      if (deduped.length >= 200) break;
    }

    return deduped;
  }, [includeArchive, items, onlyMapped, search, theme]);

  const visibleRanked = useMemo(() => ranked.slice(0, visibleCount), [ranked, visibleCount]);

  const sourcePulse = useMemo(() => {
    const map = new Map<string, SourcePulseItem>();
    for (const row of ranked) {
      const sourceId = row.source_id || "unknown";
      const headline = row.headline || "Untitled";
      const date = row.announcement_date || null;
      const url = sourceUrl(row);
      const existing = map.get(sourceId);
      if (!existing) {
        map.set(sourceId, {
          sourceId,
          count: 1,
          latestAt: date,
          latestHeadline: headline,
          latestUrl: url,
        });
        continue;
      }
      existing.count += 1;
      const isNewer = Date.parse(date || "") > Date.parse(existing.latestAt || "");
      if (isNewer) {
        existing.latestAt = date;
        existing.latestHeadline = headline;
        existing.latestUrl = url;
      }
    }

    return Array.from(map.values())
      .sort((a, b) => {
        if (b.count !== a.count) return b.count - a.count;
        return Date.parse(b.latestAt || "") - Date.parse(a.latestAt || "");
      })
      .slice(0, 8);
  }, [ranked]);

  const kenyaNow = useMemo(() => ranked.filter((row) => (row.scope || "kenya_core") !== "global_outside").slice(0, 5), [ranked]);
  const globalNow = useMemo(() => ranked.filter((row) => (row.scope || "kenya_core") === "global_outside").slice(0, 5), [ranked]);

  const storyParagraphs = useMemo(() => (marketStory.data?.item?.paragraphs || []).slice(0, 3), [marketStory.data?.item?.paragraphs]);
  const drivers = useMemo(() => (marketStory.data?.item?.global_drivers || []).slice(0, 6), [marketStory.data?.item?.global_drivers]);

  useEffect(() => {
    setVisibleCount(FEED_PAGE_SIZE);
  }, [lane, theme, onlyMapped, includeArchive, search, ranked.length]);

  useEffect(() => {
    const root = feedContainerRef.current;
    const target = feedSentinelRef.current;
    if (!root || !target) return;

    const observer = new IntersectionObserver(
      (entries) => {
        const entry = entries[0];
        if (!entry?.isIntersecting) return;
        setVisibleCount((prev) => Math.min(prev + FEED_PAGE_SIZE, ranked.length));
      },
      { root, rootMargin: "220px 0px", threshold: 0.01 },
    );

    observer.observe(target);
    return () => observer.disconnect();
  }, [ranked.length]);

  return (
    <div className="space-y-4">
      <Panel>
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-base font-semibold text-ink">News Intel Feed · Inside + Outside</h1>
            <p className="mt-1 text-xs text-muted">
              Live market feed with source links and Agent F narrative summary of what outlets are saying now.
            </p>
          </div>
          <div className="text-xs text-ink-faint">Auto-refresh: feed 15s · story 30s</div>
        </div>
      </Panel>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
        <Panel className="space-y-3">
          <div className="flex items-center justify-between border-b border-line pb-2">
            <h2 className="text-sm font-semibold text-ink">Agent F Brief</h2>
            <span className="text-xs text-ink-faint">What sources are saying</span>
          </div>
          <div className="text-sm font-medium text-ink">{marketStory.data?.item?.title || marketStory.data?.item?.headline || "Market story"}</div>
          {marketStory.isLoading ? (
            <div className="text-sm text-muted">Loading narrative...</div>
          ) : storyParagraphs.length === 0 ? (
            <div className="text-sm text-muted">No latest narrative text yet.</div>
          ) : (
            storyParagraphs.map((paragraph, idx) => (
              <p key={`story-${idx}`} className="text-sm leading-6 text-ink-soft">
                {paragraph}
              </p>
            ))
          )}
          {drivers.length > 0 ? (
            <div className="space-y-2 pt-1">
              <div className="text-xs uppercase tracking-[0.12em] text-ink-faint">Top global drivers</div>
              {drivers.slice(0, 3).map((driver, idx) => (
                <div key={`driver-${idx}`} className="rounded-lg border border-line bg-panel-soft p-2.5">
                  <div className="mb-1 flex items-center gap-2 text-xs">
                    <Badge value={cleanLabel(driver.theme || "global")} />
                    <span className="text-cyan-300">Impact {fmtNumber(driver.kenya_impact_score ?? 0)}</span>
                  </div>
                  <p className="text-sm text-ink">{driver.headline || driver.summary || "-"}</p>
                </div>
              ))}
            </div>
          ) : null}
        </Panel>

        <Panel className="space-y-3">
          <div className="flex items-center justify-between border-b border-line pb-2">
            <h2 className="text-sm font-semibold text-ink">Source Pulse</h2>
            <span className="text-xs text-ink-faint">Most active sources now</span>
          </div>
          {sourcePulse.length === 0 ? (
            <div className="text-sm text-muted">No source activity in current filter.</div>
          ) : (
            <div className="space-y-2">
              {sourcePulse.map((source) => (
                <div key={source.sourceId} className="rounded-lg border border-line bg-panel-soft p-2.5">
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-sm font-medium text-ink">{cleanLabel(source.sourceId)}</span>
                    <span className="text-xs text-ink-faint">{fmtNumber(source.count)} posts</span>
                  </div>
                  <div className="mt-1 text-xs text-ink-faint">Latest: {fmtDateTime(source.latestAt)}</div>
                  {source.latestUrl ? (
                    <a href={source.latestUrl} target="_blank" rel="noreferrer" className="mt-1 block text-xs text-cyan-300 hover:underline">
                      {source.latestHeadline}
                    </a>
                  ) : (
                    <p className="mt-1 text-xs text-ink-soft">{source.latestHeadline}</p>
                  )}
                </div>
              ))}
            </div>
          )}
        </Panel>
      </div>

      <Panel>
        <div className="grid gap-3 grid-cols-2 md:grid-cols-3 lg:grid-cols-5">
          <div>
            <label className="mb-1 block text-[11px] uppercase tracking-[0.12em] text-ink-faint">Lane</label>
            <Select value={lane} onChange={(e) => setLane(e.target.value as LaneFilter)}>
              <option value="all">All Lanes</option>
              <option value="kenya_core">Kenya Core</option>
              <option value="global_outside">Global Outside</option>
            </Select>
          </div>
          <div>
            <label className="mb-1 block text-[11px] uppercase tracking-[0.12em] text-ink-faint">Theme</label>
            <Select value={theme} onChange={(e) => setTheme(e.target.value)}>
              <option value="all">All Themes</option>
              {themeOptions.map((value) => (
                <option key={value} value={value}>
                  {cleanLabel(value)}
                </option>
              ))}
            </Select>
          </div>
          <div>
            <label className="mb-1 block text-[11px] uppercase tracking-[0.12em] text-ink-faint">Search</label>
            <Input placeholder="Headline, ticker, source..." value={search} onChange={(e) => setSearch(e.target.value)} />
          </div>
          <div className="flex items-end">
            <label className="inline-flex w-full cursor-pointer items-center gap-2 rounded-lg border border-line bg-panel-soft px-3 py-2 text-xs text-ink-soft">
              <input
                type="checkbox"
                className="h-4 w-4 accent-cyan-500"
                checked={onlyMapped}
                onChange={(e) => setOnlyMapped(e.target.checked)}
              />
              Only mapped tickers
            </label>
          </div>
          <div className="flex items-end">
            <label className="inline-flex w-full cursor-pointer items-center gap-2 rounded-lg border border-line bg-panel-soft px-3 py-2 text-xs text-ink-soft">
              <input
                type="checkbox"
                className="h-4 w-4 accent-cyan-500"
                checked={includeArchive}
                onChange={(e) => setIncludeArchive(e.target.checked)}
              />
              Include archive disclosures
            </label>
          </div>
        </div>
      </Panel>

      <div className="grid gap-4 xl:grid-cols-2">
        <Panel className="space-y-3">
          <div className="flex items-center justify-between border-b border-line pb-2">
            <h2 className="text-sm font-semibold text-ink">Kenya Core Now</h2>
            <span className="text-xs text-ink-faint">Latest {fmtNumber(kenyaNow.length)}</span>
          </div>
          <div className="space-y-2">
            {kenyaNow.length === 0 ? (
              <div className="text-sm text-muted">No Kenya-core posts in this filter.</div>
            ) : (
              kenyaNow.map((row) => (
                <a
                  key={`kenya-${row.announcement_id}`}
                  href={sourceUrl(row) || "#"}
                  target="_blank"
                  rel="noreferrer"
                  className="block rounded-lg border border-line bg-panel-soft p-2.5 text-sm text-ink hover:border-cyan-500/40"
                >
                  {row.headline || "Untitled"}
                </a>
              ))
            )}
          </div>
        </Panel>

        <Panel className="space-y-3">
          <div className="flex items-center justify-between border-b border-line pb-2">
            <h2 className="text-sm font-semibold text-ink">Global Outside Now</h2>
            <span className="text-xs text-ink-faint">Latest {fmtNumber(globalNow.length)}</span>
          </div>
          <div className="space-y-2">
            {globalNow.length === 0 ? (
              <div className="text-sm text-muted">No global-outside posts in this filter.</div>
            ) : (
              globalNow.map((row) => (
                <a
                  key={`global-${row.announcement_id}`}
                  href={sourceUrl(row) || "#"}
                  target="_blank"
                  rel="noreferrer"
                  className="block rounded-lg border border-line bg-panel-soft p-2.5 text-sm text-ink hover:border-cyan-500/40"
                >
                  {row.headline || "Untitled"}
                </a>
              ))
            )}
          </div>
        </Panel>
      </div>

      <Panel className="space-y-3">
        <div className="flex items-center justify-between border-b border-line pb-2">
          <h2 className="text-sm font-semibold text-ink">Latest Feed</h2>
          <span className="text-xs text-ink-faint">
            Showing {fmtNumber(visibleRanked.length)} / {fmtNumber(ranked.length)} posts
          </span>
        </div>

        {announcements.isLoading ? (
          <div className="text-sm text-muted">Loading live feed...</div>
        ) : announcements.isError ? (
          <div className="text-sm text-red-300">Failed to load feed from Agent B.</div>
        ) : ranked.length === 0 ? (
          <div className="text-sm text-muted">No posts match your current filters.</div>
        ) : (
          <div ref={feedContainerRef} className="max-h-[calc(100vh-360px)] space-y-3 overflow-auto pr-1">
            {visibleRanked.map((row) => {
              const url = sourceUrl(row);
              return (
                <article key={row.announcement_id} className="rounded-xl border border-line bg-panel-soft p-3">
                  <div className="mb-2 flex flex-wrap items-center gap-2 text-xs">
                    <span className="text-ink-faint">{fmtDateTime(row.announcement_date || null)}</span>
                    <Badge value={laneLabel(row.scope)} />
                    {row.theme ? <Badge value={cleanLabel(row.theme)} /> : null}
                    <span className="rounded-full border border-line px-2 py-0.5 font-medium text-ink-soft">{row.ticker || "UNMAPPED"}</span>
                    <span className="rounded-full border border-cyan-500/30 bg-cyan-500/10 px-2 py-0.5 font-medium text-cyan-300">
                      Impact {fmtNumber(row.kenya_impact_score ?? 0)}
                    </span>
                    <span className="text-muted">{cleanLabel(row.source_id || "unknown")}</span>
                  </div>

                  <h3 className="text-sm font-semibold leading-6 text-ink">
                    {url ? (
                      <a href={url} target="_blank" rel="noreferrer" className="hover:text-cyan-300 hover:underline">
                        {row.headline || "Untitled signal"}
                      </a>
                    ) : (
                      row.headline || "Untitled signal"
                    )}
                  </h3>

                  <p className="mt-2 text-sm leading-6 text-ink-soft">{excerpt(row.details || row.company || row.announcement_type, 230)}</p>

                  <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-muted">
                    {url ? (
                      <a href={url} target="_blank" rel="noreferrer" className="font-medium text-cyan-300 hover:underline">
                        Read full source
                      </a>
                    ) : (
                      <span className="text-ink-faint">No source URL</span>
                    )}
                  </div>
                </article>
              );
            })}
            <div ref={feedSentinelRef} className="h-0.5 w-full" />
            {visibleCount < ranked.length ? (
              <div className="flex justify-center pt-1">
                <button
                  type="button"
                  onClick={() => setVisibleCount((prev) => Math.min(prev + FEED_PAGE_SIZE, ranked.length))}
                  className="rounded-lg border border-line/80 bg-elevated px-3 py-1.5 text-xs font-medium text-ink-soft hover:border-cyan-500/40 hover:text-cyan-300"
                >
                  Load more
                </button>
              </div>
            ) : null}
          </div>
        )}
      </Panel>
    </div>
  );
}
