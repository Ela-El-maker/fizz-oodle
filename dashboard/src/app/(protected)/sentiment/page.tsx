"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchSentimentDigestLatest, fetchThemeSentimentWeekly, fetchWeeklySentiment } from "@/entities/sentiment/api";
import { fetchLatestStory } from "@/entities/story/api";
import { fetchUniverseSummary } from "@/entities/universe/api";
import { Panel } from "@/shared/ui/Panel";
import { StatCard } from "@/shared/ui/StatCard";
import { Input } from "@/shared/ui/Input";
import { Select } from "@/shared/ui/Select";
import { fmtDateTime, fmtDecimal, fmtNumber } from "@/shared/lib/format";
import { normalizeStatus } from "@/shared/lib/status";

type CoverageFilter = "all" | "with_signal" | "bullish_leaders";
type SortMode = "mentions_desc" | "bull_desc" | "wow_desc" | "confidence_desc" | "ticker_asc";

function toneByScore(score: number | null | undefined): string {
  if (score === null || score === undefined || Number.isNaN(score)) return "text-ink-soft";
  if (score >= 0.55) return "text-green-300";
  if (score <= 0.3) return "text-amber-300";
  return "text-ink-soft";
}

function toneByDelta(delta: number | null | undefined): string {
  if (delta === null || delta === undefined || Number.isNaN(delta)) return "text-ink-soft";
  if (delta > 0) return "text-green-300";
  if (delta < 0) return "text-amber-300";
  return "text-ink-soft";
}

function normalizeEvidenceLabel(value: string): string {
  return value.replace(/_/g, " ").replace(/\s+/g, " ").trim();
}

function formatTopSources(sources: Record<string, number> | null | undefined): string {
  if (!sources) return "-";
  const rows = Object.entries(sources)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 2)
    .map(([key, count]) => `${key} (${count})`);
  return rows.length ? rows.join(", ") : "-";
}

function formatThemeLabel(theme: string | null | undefined): string {
  return (theme || "-").replace(/_/g, " ").replace(/\s+/g, " ").trim();
}

export default function SentimentPage() {
  const [query, setQuery] = useState("");
  const [coverageFilter, setCoverageFilter] = useState<CoverageFilter>("all");
  const [sortMode, setSortMode] = useState<SortMode>("mentions_desc");
  const [expandNarrative, setExpandNarrative] = useState(false);

  const digest = useQuery({
    queryKey: ["sentiment-digest-latest", "page"],
    queryFn: fetchSentimentDigestLatest,
    refetchInterval: 15000,
    staleTime: 15000,
  });
  const weekly = useQuery({
    queryKey: ["sentiment-weekly", "page"],
    queryFn: () => fetchWeeklySentiment({ limit: 200 }),
    refetchInterval: 15000,
    staleTime: 15000,
  });
  const themeWeekly = useQuery({
    queryKey: ["sentiment-theme-weekly", "page"],
    queryFn: () => fetchThemeSentimentWeekly(),
    refetchInterval: 30000,
    staleTime: 30000,
  });
  const narrator = useQuery({
    queryKey: ["stories-latest", "market", "sentiment"],
    queryFn: () => fetchLatestStory({ scope: "market", context: "sentiment" }),
    refetchInterval: 30000,
    staleTime: 30000,
  });
  const universe = useQuery({
    queryKey: ["universe-summary", "sentiment"],
    queryFn: fetchUniverseSummary,
    refetchInterval: 60000,
    staleTime: 60000,
  });

  const digestItem = digest.data?.item || null;
  const moodHeadline =
    digestItem?.human_summary_v2?.headline || digestItem?.human_summary?.headline || "Sentiment Digest";
  const moodPlain =
    digestItem?.human_summary_v2?.plain_summary || digestItem?.human_summary?.plain_summary || "";

  const baseRows = useMemo(() => weekly.data?.items || [], [weekly.data?.items]);
  const rows = useMemo(() => {
    const q = query.trim().toUpperCase();
    let out = baseRows.filter((item) => {
      if (!q) return true;
      return (
        (item.ticker || "").toUpperCase().includes(q) ||
        (item.company_name || "").toUpperCase().includes(q)
      );
    });

    if (coverageFilter === "with_signal") {
      out = out.filter((item) => Number(item.mentions ?? item.mentions_count ?? 0) > 0);
    }
    if (coverageFilter === "bullish_leaders") {
      out = out.filter((item) => Number(item.bullish_pct ?? 0) >= 55);
    }

    out = [...out].sort((a, b) => {
      if (sortMode === "ticker_asc") return (a.ticker || "").localeCompare(b.ticker || "");
      if (sortMode === "bull_desc") return Number(b.bullish_pct ?? 0) - Number(a.bullish_pct ?? 0);
      if (sortMode === "wow_desc") return Number(b.wow_delta ?? 0) - Number(a.wow_delta ?? 0);
      if (sortMode === "confidence_desc") return Number(b.confidence ?? 0) - Number(a.confidence ?? 0);
      return Number(b.mentions ?? b.mentions_count ?? 0) - Number(a.mentions ?? a.mentions_count ?? 0);
    });

    return out;
  }, [baseRows, coverageFilter, query, sortMode]);

  const totals = useMemo(() => {
    const items = baseRows;
    return {
      companies: items.length,
      mentions: items.reduce((acc, item) => acc + Number(item.mentions ?? item.mentions_count ?? 0), 0),
      bullishLeaders: items.filter((item) => Number(item.bullish_pct ?? 0) >= 55).length,
      withSignal: items.filter((item) => Number(item.mentions ?? item.mentions_count ?? 0) > 0).length,
    };
  }, [baseRows]);
  const trackedNse = universe.data?.nse_tickers || 0;
  const signalCoveragePct = trackedNse > 0 ? (totals.withSignal / trackedNse) * 100 : null;

  const narratorItem = narrator.data?.item;
  const narratorHeadline = narratorItem?.headline || narratorItem?.title || moodHeadline;
  const narratorParagraphs =
    narratorItem?.paragraphs && narratorItem.paragraphs.length > 0
      ? narratorItem.paragraphs
      : moodPlain
        ? [moodPlain]
        : [];
  const visibleParagraphs = expandNarrative ? narratorParagraphs : narratorParagraphs.slice(0, 2);

  return (
    <div className="space-y-4">
      <Panel>
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-base font-semibold text-ink">Sentiment · Company Breakdown (Agent C)</h1>
            <p className="mt-1 text-xs text-muted">
              Weekly sentiment telemetry with live narrator interpretation and ranked company signal table.
            </p>
          </div>
          <div className="text-xs text-ink-faint">
            Week: {digestItem?.week_start || "-"} · Updated: {fmtDateTime(digestItem?.generated_at || digestItem?.sent_at || null)}
          </div>
        </div>
      </Panel>

      <div className="grid gap-3 grid-cols-2 md:grid-cols-3 xl:grid-cols-5">
        <StatCard
          label="Digest Status"
          value={normalizeStatus(digestItem?.status)}
          hint={`Week ${digestItem?.week_start || "-"}`}
          tone="brand"
        />
        <StatCard label="Tracked NSE Tickers" value={fmtNumber(trackedNse)} tone="neutral" />
        <StatCard
          label="Companies with Signal"
          value={fmtNumber(totals.withSignal)}
          hint={signalCoveragePct === null ? undefined : `${fmtDecimal(signalCoveragePct, 1)}% coverage`}
          tone="success"
        />
        <StatCard label="Total Mentions" value={fmtNumber(totals.mentions)} tone="warning" />
        <StatCard label="Bullish Leaders (>=55%)" value={fmtNumber(totals.bullishLeaders)} tone="success" />
        <StatCard label="Rows in Weekly Table" value={fmtNumber(totals.companies)} tone="neutral" />
      </div>

      <Panel className="space-y-3">
        <div className="border-b border-line pb-2">
          <h2 className="text-sm font-semibold text-ink">Market Mood Snapshot</h2>
          <p className="mt-1 text-xs text-ink-faint">Digest-level summary for operator decision support.</p>
        </div>
        <p className="text-sm font-medium text-ink">{moodHeadline}</p>
        {moodPlain ? <p className="text-sm leading-6 text-ink-soft">{moodPlain}</p> : null}
      </Panel>

      <Panel className="space-y-3">
        <div className="flex items-center justify-between border-b border-line pb-2">
          <h2 className="text-sm font-semibold text-ink">Global Theme Sentiment</h2>
          <span className="text-xs text-ink-faint">Oil · USD/Rates · Bonds · Earnings/Dividends · Trading Risk · AI</span>
        </div>
        {themeWeekly.isLoading ? (
          <div className="text-sm text-muted">Loading theme sentiment...</div>
        ) : themeWeekly.isError ? (
          <div className="text-sm text-red-300">Failed to load global theme sentiment.</div>
        ) : (themeWeekly.data?.items || []).length === 0 ? (
          <div className="text-sm text-muted">No global theme rows available for the selected week.</div>
        ) : (
          <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
            {(themeWeekly.data?.items || []).slice(0, 9).map((item) => (
              <div key={item.theme} className="rounded-lg border border-line bg-panel-soft p-3">
                <div className="flex items-center justify-between gap-2">
                  <div className="text-[11px] uppercase tracking-[0.12em] text-ink-faint">{formatThemeLabel(item.theme)}</div>
                  {item.theme_group ? (
                    <span className="rounded border border-line px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-ink-soft">
                      {formatThemeLabel(item.theme_group)}
                    </span>
                  ) : null}
                </div>
                <div className="mt-1 text-sm text-ink">
                  Score {fmtDecimal(item.weighted_score ?? null, 3)} · Mentions {fmtNumber(item.mentions ?? null)}
                </div>
                <div className="mt-1 text-xs text-muted">
                  Kenya relevance {fmtDecimal(item.kenya_relevance_avg ?? null, 3)} · WoW {fmtDecimal(item.wow_delta ?? null, 3)}
                </div>
              </div>
            ))}
          </div>
        )}
      </Panel>

      <Panel className="space-y-3">
        <div className="flex items-center justify-between border-b border-line pb-2">
          <h2 className="text-sm font-semibold text-ink">Narrator Card (Agent F)</h2>
          <div className="flex items-center gap-2 text-xs">
            {narrator.isError ? (
              <span className="rounded border border-amber-700 px-2 py-1 text-amber-300">Fallback: Digest Context</span>
            ) : narratorItem?.fallback_mode && narratorItem.fallback_mode !== "none" ? (
              <span className="rounded border border-amber-700 px-2 py-1 text-amber-300">
                fallback:{narratorItem.fallback_mode}
              </span>
            ) : (
              <span className="rounded border border-emerald-700 px-2 py-1 text-emerald-300">Narrator Source: Agent F</span>
            )}
            <span className="text-ink-faint">Generated: {fmtDateTime(narratorItem?.generated_at || null)}</span>
          </div>
        </div>

        {narrator.isLoading ? (
          <div className="text-sm text-muted">Loading narrator interpretation...</div>
        ) : (
          <div className="space-y-2">
            <p className="text-sm font-semibold text-ink">{narratorHeadline}</p>
            {visibleParagraphs.map((paragraph, idx) => (
              <p key={`narrator-sentiment-${idx}`} className="text-sm leading-6 text-ink-soft">
                {paragraph}
              </p>
            ))}
            {narratorParagraphs.length > 2 ? (
              <button
                type="button"
                className="rounded-md border border-line px-2.5 py-1 text-xs text-ink hover:bg-elevated"
                onClick={() => setExpandNarrative((prev) => !prev)}
              >
                {expandNarrative ? "Show Less" : "Show Full Narrative"}
              </button>
            ) : null}

            {narratorItem?.evidence_refs && narratorItem.evidence_refs.length > 0 ? (
              <div className="pt-1">
                <div className="mb-1 text-[11px] uppercase tracking-[0.12em] text-ink-faint">Evidence</div>
                <div className="flex flex-wrap gap-2">
                  {narratorItem.evidence_refs.slice(0, 6).map((ref, idx) => {
                    const label =
                      typeof ref === "string"
                        ? normalizeEvidenceLabel(ref)
                        : normalizeEvidenceLabel(String((ref as Record<string, unknown>).type || "evidence"));
                    return (
                      <span
                        key={`${label}-${idx}`}
                        className="inline-flex rounded-full border border-line bg-elevated px-2.5 py-1 text-xs text-ink-soft"
                      >
                        {label}
                      </span>
                    );
                  })}
                </div>
              </div>
            ) : null}
          </div>
        )}
      </Panel>

      <Panel>
        <div className="grid gap-3 sm:grid-cols-2 md:grid-cols-3">
          <div>
            <label className="mb-1 block text-[11px] uppercase tracking-[0.12em] text-ink-faint">Filter</label>
            <Input
              placeholder="Ticker or company..."
              value={query}
              onChange={(e) => setQuery(e.target.value)}
            />
          </div>
          <div>
            <label className="mb-1 block text-[11px] uppercase tracking-[0.12em] text-ink-faint">Coverage</label>
            <Select value={coverageFilter} onChange={(e) => setCoverageFilter(e.target.value as CoverageFilter)}>
              <option value="all">All Companies</option>
              <option value="with_signal">Mentions &gt; 0</option>
              <option value="bullish_leaders">Bullish Leaders ({">="}55%)</option>
            </Select>
          </div>
          <div>
            <label className="mb-1 block text-[11px] uppercase tracking-[0.12em] text-ink-faint">Sort</label>
            <Select value={sortMode} onChange={(e) => setSortMode(e.target.value as SortMode)}>
              <option value="mentions_desc">Mentions (High to Low)</option>
              <option value="bull_desc">Bull % (High to Low)</option>
              <option value="wow_desc">WoW Δ (High to Low)</option>
              <option value="confidence_desc">Confidence (High to Low)</option>
              <option value="ticker_asc">Ticker (A-Z)</option>
            </Select>
          </div>
        </div>
      </Panel>

      <Panel className="space-y-3">
        <div className="flex items-center justify-between border-b border-line pb-2">
          <h2 className="text-sm font-semibold text-ink">Weekly Company Sentiment</h2>
          <span className="text-xs text-ink-faint">{fmtNumber(rows.length)} rows</span>
        </div>

        {digest.isLoading || weekly.isLoading ? (
          <div className="text-sm text-muted">Loading sentiment data...</div>
        ) : digest.isError || weekly.isError ? (
          <div className="text-sm text-red-300">Failed to load sentiment data.</div>
        ) : rows.length === 0 ? (
          <div className="text-sm text-muted">No sentiment rows match your filter.</div>
        ) : (
          <div className="max-h-[calc(100vh-360px)] overflow-auto rounded-xl border border-line">
            <table className="w-full min-w-[1050px] text-sm">
              <thead className="sticky top-0 z-10 bg-inset/95">
                <tr className="text-left text-[11px] uppercase tracking-[0.12em] text-ink-faint">
                  <th className="px-3 py-2">Ticker</th>
                  <th className="px-2 py-2">Company</th>
                  <th className="px-2 py-2">Mentions</th>
                  <th className="px-2 py-2">Bull %</th>
                  <th className="px-2 py-2">Bear %</th>
                  <th className="px-2 py-2">Neutral %</th>
                  <th className="px-2 py-2">Score</th>
                  <th className="px-2 py-2">Confidence</th>
                  <th className="px-2 py-2">WoW Δ</th>
                  <th className="px-3 py-2">Top Sources</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row, idx) => (
                  <tr key={`${row.ticker || "ticker"}-${idx}`} className="border-t border-line hover:bg-hover">
                    <td className="px-3 py-2 font-medium text-ink">{row.ticker || "-"}</td>
                    <td className="px-2 py-2 text-ink-soft">{row.company_name || "-"}</td>
                    <td className="px-2 py-2 text-ink-soft">{fmtNumber(row.mentions ?? row.mentions_count ?? null)}</td>
                    <td className="px-2 py-2 text-green-300">{fmtDecimal(row.bullish_pct ?? null, 1)}</td>
                    <td className="px-2 py-2 text-red-300">{fmtDecimal(row.bearish_pct ?? null, 1)}</td>
                    <td className="px-2 py-2 text-ink-soft">{fmtDecimal(row.neutral_pct ?? null, 1)}</td>
                    <td className={`px-2 py-2 ${toneByScore(row.weighted_score)}`}>{fmtDecimal(row.weighted_score ?? null, 3)}</td>
                    <td className="px-2 py-2 text-ink-soft">{fmtDecimal(row.confidence ?? null, 3)}</td>
                    <td className={`px-2 py-2 ${toneByDelta(row.wow_delta)}`}>{fmtDecimal(row.wow_delta ?? null, 2)}</td>
                    <td className="px-3 py-2 text-xs text-muted">{formatTopSources(row.top_sources || null)}</td>
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
