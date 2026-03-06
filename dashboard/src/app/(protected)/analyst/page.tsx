"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchLatestReport, fetchReports } from "@/entities/report/api";
import { fetchLatestStory } from "@/entities/story/api";
import { Panel } from "@/shared/ui/Panel";
import { StatCard } from "@/shared/ui/StatCard";
import { Select } from "@/shared/ui/Select";
import { Input } from "@/shared/ui/Input";
import { Badge } from "@/shared/ui/Badge";
import { fmtDateTime, fmtDecimal, fmtNumber } from "@/shared/lib/format";
import { normalizeStatus } from "@/shared/lib/status";

type ReportType = "daily" | "weekly";
type SortMode = "confidence_desc" | "convergence_desc" | "strength_desc" | "ticker_asc";

type DecisionTraceItem = {
  ticker?: string;
  final?: {
    direction?: string;
    confidence_pct?: number;
    strength?: number;
    convergence_score?: number;
    anomalies?: string[];
  };
  inputs?: {
    price?: string;
    announcement?: string;
    sentiment?: string;
  };
};

type ThemeRow = {
  theme_group?: string;
  theme?: string;
  mentions?: number;
  count?: number;
  weighted_score?: number;
};

function evidenceLabel(value: string): string {
  return value.replace(/_/g, " ").replace(/\s+/g, " ").trim();
}

function directionTone(direction: string | null | undefined): string {
  const d = (direction || "").toLowerCase();
  if (d === "bullish" || d === "positive" || d === "up") return "success";
  if (d === "bearish" || d === "negative" || d === "down") return "fail";
  return "partial";
}

function biasBasis(row: DecisionTraceItem): string {
  const direction = (row.final?.direction || "neutral").toLowerCase();
  const price = (row.inputs?.price || "none").toLowerCase();
  const announcement = (row.inputs?.announcement || "none").toLowerCase();
  const sentiment = (row.inputs?.sentiment || "none").toLowerCase();
  const anomalies = row.final?.anomalies || [];

  if (anomalies.includes("sentiment_price_divergence")) {
    return "Price and sentiment diverged; direction was damped.";
  }
  if (anomalies.includes("price_no_announcement")) {
    return "Price moved without announcement confirmation.";
  }
  if (direction === "bullish") {
    if (announcement === "positive") return "Positive announcement support with constructive cross-signal context.";
    if (price === "up") return "Upward price momentum is leading the bias.";
    if (sentiment === "bullish") return "Bullish sentiment is dominating this setup.";
    return "Bullish alignment across available evidence.";
  }
  if (direction === "bearish") {
    if (announcement === "negative") return "Negative announcement pressure is driving downside risk.";
    if (price === "down") return "Downward price momentum is leading the bias.";
    if (sentiment === "bearish") return "Bearish sentiment pressure is dominating this setup.";
    return "Bearish alignment across available evidence.";
  }
  if (price === "flat" && announcement === "none" && sentiment === "neutral") {
    return "No strong directional signal is present.";
  }
  return "Mixed signals across price, announcement, and sentiment.";
}

function ageMinutes(value: string | null | undefined): number | null {
  if (!value) return null;
  const ts = Date.parse(value);
  if (Number.isNaN(ts)) return null;
  return Math.max(0, Math.round((Date.now() - ts) / 60000));
}

function freshnessMeta(value: string | null | undefined): { label: string; detail: string; className: string } {
  const mins = ageMinutes(value);
  if (mins === null) {
    return {
      label: "Unknown",
      detail: "no timestamp",
      className: "border-line bg-elevated text-ink-soft",
    };
  }
  if (mins <= 15) {
    return {
      label: "Fresh",
      detail: `${mins}m old`,
      className: "border-emerald-700/70 bg-emerald-900/20 text-emerald-300",
    };
  }
  if (mins <= 60) {
    return {
      label: "Recent",
      detail: `${mins}m old`,
      className: "border-cyan-700/70 bg-cyan-900/20 text-cyan-300",
    };
  }
  if (mins <= 240) {
    return {
      label: "Aging",
      detail: `${mins}m old`,
      className: "border-amber-700/70 bg-amber-900/20 text-amber-300",
    };
  }
  return {
    label: "Stale",
    detail: `${mins}m old`,
    className: "border-red-700/70 bg-red-900/20 text-red-300",
  };
}

export default function AnalystPage() {
  const [reportType, setReportType] = useState<ReportType>("daily");
  const [tickerFilter, setTickerFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [sortMode, setSortMode] = useState<SortMode>("confidence_desc");
  const [expandNarrator, setExpandNarrator] = useState(false);

  const latest = useQuery({
    queryKey: ["report-latest", "page", reportType],
    queryFn: () => fetchLatestReport(reportType),
    refetchInterval: 15000,
    staleTime: 15000,
  });
  const history = useQuery({
    queryKey: ["report-history", "page", reportType],
    queryFn: () => fetchReports({ type: reportType, limit: 30 }),
    refetchInterval: 30000,
    staleTime: 30000,
  });
  const narrator = useQuery({
    queryKey: ["stories-latest", "analyst", reportType],
    queryFn: () => fetchLatestStory({ scope: "analyst", context: reportType }),
    refetchInterval: 30000,
    staleTime: 30000,
  });

  const decisionRows = useMemo(() => {
    const metrics = latest.data?.item?.metrics as Record<string, unknown> | undefined;
    return ((metrics?.decision_trace as DecisionTraceItem[] | undefined) || []).filter(Boolean);
  }, [latest.data?.item?.metrics]);

  const tickerOptions = useMemo(() => {
    const set = new Set<string>();
    for (const row of decisionRows) {
      if (row.ticker) set.add(row.ticker);
    }
    return Array.from(set).sort();
  }, [decisionRows]);

  const filteredRows = useMemo(() => {
    const q = search.trim().toUpperCase();
    let rows = decisionRows.filter((row) => {
      const ticker = row.ticker || "";
      if (tickerFilter !== "all" && ticker !== tickerFilter) return false;
      if (!q) return true;
      const direction = row.final?.direction || "";
      const signalPack = `${row.inputs?.price || ""} ${row.inputs?.announcement || ""} ${row.inputs?.sentiment || ""}`;
      return (
        ticker.toUpperCase().includes(q) ||
        direction.toUpperCase().includes(q) ||
        signalPack.toUpperCase().includes(q)
      );
    });

    rows = [...rows].sort((a, b) => {
      if (sortMode === "ticker_asc") return (a.ticker || "").localeCompare(b.ticker || "");
      if (sortMode === "convergence_desc") return Number(b.final?.convergence_score ?? 0) - Number(a.final?.convergence_score ?? 0);
      if (sortMode === "strength_desc") return Number(b.final?.strength ?? 0) - Number(a.final?.strength ?? 0);
      return Number(b.final?.confidence_pct ?? 0) - Number(a.final?.confidence_pct ?? 0);
    });
    return rows;
  }, [decisionRows, search, sortMode, tickerFilter]);

  const summary = latest.data?.item?.human_summary_v2 || latest.data?.item?.human_summary;
  const metrics = (latest.data?.item?.metrics || {}) as Record<string, unknown>;
  const payload = (latest.data?.item?.json_payload || {}) as Record<string, unknown>;
  const globalContext = useMemo<Record<string, unknown>>(() => {
    const payloadContext = payload.global_context;
    if (payloadContext && typeof payloadContext === "object" && !Array.isArray(payloadContext)) {
      return payloadContext as Record<string, unknown>;
    }
    const metricContext = metrics.global_context;
    if (metricContext && typeof metricContext === "object" && !Array.isArray(metricContext)) {
      return metricContext as Record<string, unknown>;
    }
    return {};
  }, [payload.global_context, metrics.global_context]);
  const globalThemeRows = useMemo<ThemeRow[]>(() => {
    const rows = globalContext.top_global_themes;
    if (!Array.isArray(rows)) return [];
    return rows.filter((row): row is ThemeRow => !!row && typeof row === "object");
  }, [globalContext]);
  const globalThemeBreakdown = useMemo<ThemeRow[]>(() => {
    const rows = globalContext.theme_breakdown;
    if (!Array.isArray(rows)) return [];
    return rows.filter((row): row is ThemeRow => !!row && typeof row === "object");
  }, [globalContext]);
  const highImpactGlobalEvents = useMemo<Array<Record<string, unknown>>>(() => {
    const rows = globalContext.high_impact_global_events;
    if (!Array.isArray(rows)) return [];
    return rows.filter((row): row is Record<string, unknown> => !!row && typeof row === "object");
  }, [globalContext]);
  const themeBreakdownRows = useMemo<ThemeRow[]>(() => {
    if (globalThemeBreakdown.length > 0) {
      return [...globalThemeBreakdown];
    }

    const buckets = new Map<string, { mentions: number; scoreSum: number; scoreWeight: number }>();
    const upsert = (themeValue: unknown, mentionsValue: unknown, scoreValue: unknown) => {
      const rawTheme = String(themeValue || "other")
        .trim()
        .toLowerCase()
        .replace(/\s+/g, "_");
      const theme = rawTheme || "other";
      const mentions = Math.max(1, Number(mentionsValue || 1));
      const score = Number(scoreValue || 0);
      const prev = buckets.get(theme) || { mentions: 0, scoreSum: 0, scoreWeight: 0 };
      prev.mentions += mentions;
      prev.scoreSum += score * mentions;
      prev.scoreWeight += mentions;
      buckets.set(theme, prev);
    };

    for (const row of globalThemeRows) {
      upsert(row.theme_group || row.theme, row.count || row.mentions, row.weighted_score);
    }
    for (const row of highImpactGlobalEvents) {
      upsert(row.theme, 1, Number(row.kenya_impact_score || 0) / 100);
    }

    return Array.from(buckets.entries())
      .map(([theme_group, val]) => ({
        theme_group,
        mentions: Math.round(val.mentions),
        weighted_score: val.scoreWeight > 0 ? val.scoreSum / val.scoreWeight : 0,
      }))
      .sort(
        (a, b) =>
          Number(b.mentions || 0) - Number(a.mentions || 0) ||
          Math.abs(Number(b.weighted_score || 0)) - Math.abs(Number(a.weighted_score || 0)),
      )
      .slice(0, 6);
  }, [globalThemeBreakdown, globalThemeRows, highImpactGlobalEvents]);
  const signalIntelligence = (payload.signal_intelligence || {}) as Record<string, unknown>;
  const feedbackDetail = (signalIntelligence.feedback || {}) as Record<string, unknown>;
  const hasFeedbackDetail = Object.keys(feedbackDetail).length > 0;
  const upstreamQuality =
    ((metrics.upstream_quality as Record<string, unknown> | undefined)?.score as number | undefined) ?? null;
  const feedbackApplied = (metrics.feedback_applied as boolean | undefined) ?? false;
  const feedbackCoverage = (metrics.feedback_coverage_pct as number | undefined) ?? null;
  const feedbackWarning = String(metrics.feedback_warning || "").trim().toLowerCase();
  const feedbackPatternCount = (feedbackDetail.patterns as number | undefined) ?? null;
  const feedbackActiveConfirmed = (feedbackDetail.active_confirmed_patterns as number | undefined) ?? null;
  const patternWeightCapped = Boolean(feedbackDetail.pattern_weight_capped);
  const patternCapFactor = (feedbackDetail.pattern_weight_cap_factor as number | undefined) ?? null;
  const patternCapAppliedCount = (feedbackDetail.pattern_weight_cap_applied_count as number | undefined) ?? null;
  const feedbackUnavailable =
    feedbackWarning === "archivist_feedback_missing" ||
    (!feedbackApplied &&
      (feedbackPatternCount ?? 0) === 0 &&
      (feedbackActiveConfirmed ?? 0) === 0 &&
      (feedbackCoverage ?? 0) <= 0);
  const feedbackStatusLabel = feedbackUnavailable ? "Unavailable" : feedbackApplied ? "Applied" : "Standby";
  const feedbackStatusHint = feedbackUnavailable
    ? "Agent E archive data unavailable"
    : feedbackCoverage === null
      ? "-"
      : `${fmtDecimal(feedbackCoverage, 2)}%`;
  const feedbackPatternValue = feedbackUnavailable
    ? "-"
    : feedbackPatternCount === null && feedbackActiveConfirmed === null
      ? "-"
      : `${fmtNumber(feedbackActiveConfirmed ?? 0)}/${fmtNumber(feedbackPatternCount ?? 0)}`;
  const feedbackPatternHint = feedbackUnavailable
    ? "waiting for Agent E archive patterns"
    : "active confirmed / total feedback patterns";
  const feedbackTone = feedbackUnavailable ? "neutral" : feedbackApplied ? "success" : "warning";
  const feedbackPatternTone = feedbackUnavailable ? "neutral" : (feedbackActiveConfirmed ?? 0) > 0 ? "success" : "warning";
  const patternCapValue = feedbackUnavailable || !hasFeedbackDetail ? "-" : patternWeightCapped ? "Active" : "Normal";
  const patternCapHint =
    feedbackUnavailable || !hasFeedbackDetail
      ? "feedback telemetry unavailable"
      : patternWeightCapped
        ? `factor ${fmtDecimal(patternCapFactor ?? null, 2)} · ${fmtNumber(patternCapAppliedCount ?? 0)} tickers`
        : "no damping applied";
  const patternCapTone = feedbackUnavailable || !hasFeedbackDetail ? "neutral" : patternWeightCapped ? "warning" : "success";
  const anomalyCount = filteredRows.reduce((acc, row) => acc + (row.final?.anomalies?.length || 0), 0);
  const biasCounts = useMemo(
    () =>
      filteredRows.reduce(
        (acc, row) => {
          const direction = (row.final?.direction || "neutral").toLowerCase();
          if (direction === "bullish") acc.bullish += 1;
          else if (direction === "bearish") acc.bearish += 1;
          else acc.neutral += 1;
          return acc;
        },
        { bullish: 0, neutral: 0, bearish: 0 }
      ),
    [filteredRows]
  );
  const marketBias = useMemo(() => {
    const entries = [
      { key: "bullish", count: biasCounts.bullish },
      { key: "neutral", count: biasCounts.neutral },
      { key: "bearish", count: biasCounts.bearish },
    ];
    const sorted = [...entries].sort((a, b) => b.count - a.count);
    if (sorted[0].count === 0) return "No Signal";
    if (sorted[0].count === sorted[1].count) return "Mixed";
    return sorted[0].key.charAt(0).toUpperCase() + sorted[0].key.slice(1);
  }, [biasCounts]);

  const narratorItem = narrator.data?.item;
  const narratorHeadline = narratorItem?.headline || narratorItem?.title || "Analyst Explainer";
  const narratorParagraphs = narratorItem?.paragraphs || [];
  const narratorVisible = expandNarrator ? narratorParagraphs : narratorParagraphs.slice(0, 3);
  const narratorFreshness = freshnessMeta(narratorItem?.generated_at || null);
  const reportFreshness = freshnessMeta(latest.data?.item?.generated_at || null);

  return (
    <div className="space-y-4">
      <Panel>
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-base font-semibold text-ink">Analyst · Signal Synthesis (Agent D)</h1>
            <p className="mt-1 text-xs text-muted">
              Cross-signal decision engine view with per-ticker traceability and narrator explanation.
            </p>
          </div>
          <div className="text-xs text-ink-faint">
            Latest report: {latest.data?.item?.period_key || "-"} · Generated {fmtDateTime(latest.data?.item?.generated_at || null)}
          </div>
        </div>
      </Panel>

      <Panel>
        <div className="grid gap-3 grid-cols-2 md:grid-cols-4">
          <div>
            <label className="mb-1 block text-[11px] uppercase tracking-[0.12em] text-ink-faint">Report Type</label>
            <Select value={reportType} onChange={(e) => setReportType(e.target.value as ReportType)}>
              <option value="daily">Daily</option>
              <option value="weekly">Weekly</option>
            </Select>
          </div>
          <div>
            <label className="mb-1 block text-[11px] uppercase tracking-[0.12em] text-ink-faint">Ticker</label>
            <Select value={tickerFilter} onChange={(e) => setTickerFilter(e.target.value)}>
              <option value="all">All tickers</option>
              {tickerOptions.map((ticker) => (
                <option key={ticker} value={ticker}>
                  {ticker}
                </option>
              ))}
            </Select>
          </div>
          <div>
            <label className="mb-1 block text-[11px] uppercase tracking-[0.12em] text-ink-faint">Sort</label>
            <Select value={sortMode} onChange={(e) => setSortMode(e.target.value as SortMode)}>
              <option value="confidence_desc">Confidence (High to Low)</option>
              <option value="convergence_desc">Convergence (High to Low)</option>
              <option value="strength_desc">Strength (High to Low)</option>
              <option value="ticker_asc">Ticker (A-Z)</option>
            </Select>
          </div>
          <div>
            <label className="mb-1 block text-[11px] uppercase tracking-[0.12em] text-ink-faint">Search</label>
            <Input placeholder="Ticker, direction, signal..." value={search} onChange={(e) => setSearch(e.target.value)} />
          </div>
        </div>
      </Panel>

      <div className="grid gap-3 grid-cols-2 sm:grid-cols-4 xl:grid-cols-8">
        <StatCard
          label="Latest Status"
          value={normalizeStatus(latest.data?.item?.status)}
          hint={latest.data?.item?.period_key || "-"}
          tone="brand"
        />
        <StatCard label="Decision Rows" value={fmtNumber(filteredRows.length)} tone="neutral" />
        <StatCard
          label="Upstream Quality"
          value={upstreamQuality === null ? "-" : fmtDecimal(upstreamQuality, 2)}
          tone="success"
        />
        <StatCard
          label="E Feedback"
          value={feedbackStatusLabel}
          hint={feedbackStatusHint}
          tone={feedbackTone}
        />
        <StatCard
          label="Pattern Coverage"
          value={feedbackPatternValue}
          hint={feedbackPatternHint}
          tone={feedbackPatternTone}
        />
        <StatCard
          label="Pattern Weight Cap"
          value={patternCapValue}
          hint={patternCapHint}
          tone={patternCapTone}
        />
        <StatCard
          label="Market Bias"
          value={marketBias}
          hint={`B:${fmtNumber(biasCounts.bullish)} · N:${fmtNumber(biasCounts.neutral)} · R:${fmtNumber(biasCounts.bearish)}`}
          tone={marketBias === "Bullish" ? "success" : marketBias === "Bearish" ? "danger" : "neutral"}
        />
        <StatCard label="Anomalies" value={fmtNumber(anomalyCount)} tone={anomalyCount > 0 ? "warning" : "success"} />
      </div>

      <Panel className="space-y-3">
        <div className="flex items-center justify-between border-b border-line pb-2">
          <h2 className="text-sm font-semibold text-ink">Global Context (A/B/C → D)</h2>
          <span className="text-xs text-ink-faint">
            Headlines {fmtNumber(Number(globalContext.global_news_collected ?? 0))}
          </span>
        </div>
        {globalThemeRows.length === 0 && highImpactGlobalEvents.length === 0 ? (
          <div className="text-sm text-muted">No global-context payload in this report window.</div>
        ) : (
          <div className="grid gap-3 lg:grid-cols-2">
            <div className="space-y-2 rounded-lg border border-line bg-panel-soft p-3">
              <div className="text-[11px] uppercase tracking-[0.12em] text-ink-faint">Theme Breakdown</div>
              {themeBreakdownRows.length === 0 ? (
                <div className="text-xs text-muted">No theme-level aggregates available in this run.</div>
              ) : (
                themeBreakdownRows.map((row, idx) => (
                  <div key={`global-theme-${idx}`} className="flex items-center justify-between gap-2 text-xs text-ink-soft">
                    <span className="capitalize">{String(row.theme_group || row.theme || "other").replace(/_/g, " ")}</span>
                    <span>
                      Mentions {fmtNumber(Number(row.mentions ?? row.count ?? 0))} · Score {fmtDecimal(Number(row.weighted_score ?? 0), 3)}
                    </span>
                  </div>
                ))
              )}
            </div>
            <div className="space-y-2 rounded-lg border border-line bg-panel-soft p-3">
              <div className="text-[11px] uppercase tracking-[0.12em] text-ink-faint">High-Impact Global Events</div>
              {highImpactGlobalEvents.length === 0 ? (
                <div className="text-xs text-muted">No events above Kenya impact threshold in this run.</div>
              ) : (
                highImpactGlobalEvents.slice(0, 5).map((row, idx) => (
                  <div key={`global-event-${idx}`} className="rounded border border-line bg-elevated/30 p-2">
                    <div className="flex items-center gap-2 text-[11px] text-muted">
                      <Badge value={String(row.theme || "global_macro")} />
                      <span>Impact {fmtNumber(Number(row.kenya_impact_score ?? 0))}</span>
                      {row.source_id ? <span>{String(row.source_id)}</span> : null}
                    </div>
                    <p className="mt-1 text-xs text-ink">{String(row.headline || "-")}</p>
                  </div>
                ))
              )}
            </div>
          </div>
        )}
      </Panel>

      <Panel className="space-y-3">
        <div className="flex items-center justify-between border-b border-line pb-2">
          <h2 className="text-sm font-semibold text-ink">Narrator Card (Agent F)</h2>
          <div className="flex items-center gap-2 text-xs text-ink-faint">
            {narratorItem?.fallback_mode && narratorItem.fallback_mode !== "none" ? (
              <span className="rounded border border-amber-700 px-2 py-1 text-amber-300">fallback:{narratorItem.fallback_mode}</span>
            ) : (
              <span className="rounded border border-emerald-700 px-2 py-1 text-emerald-300">Narrator Source: Agent F</span>
            )}
            <span>As of: {fmtDateTime(narratorItem?.generated_at || null)}</span>
            <span className={`inline-flex rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${narratorFreshness.className}`}>
              {narratorFreshness.label}
            </span>
            <span>{narratorFreshness.detail}</span>
          </div>
        </div>

        {narrator.isLoading ? (
          <div className="text-sm text-muted">Loading narrator explanation...</div>
        ) : narrator.isError ? (
          <div className="text-sm text-amber-300">Narrator is unavailable for analyst explainers right now.</div>
        ) : !narratorItem ? (
          <div className="text-sm text-muted">No narrator explainer available yet.</div>
        ) : (
          <div className="space-y-2">
            <p className="text-sm font-semibold text-ink">{narratorHeadline}</p>
            {narratorVisible.map((paragraph, idx) => (
              <p key={`narrator-analyst-${idx}`} className="text-sm leading-6 text-ink-soft">
                {paragraph}
              </p>
            ))}
            {narratorParagraphs.length > 3 ? (
              <button
                type="button"
                className="rounded-md border border-line px-2.5 py-1 text-xs text-ink hover:bg-elevated"
                onClick={() => setExpandNarrator((prev) => !prev)}
              >
                {expandNarrator ? "Show Less" : "Show Full Narrative"}
              </button>
            ) : null}
            {narratorItem.evidence_refs && narratorItem.evidence_refs.length > 0 ? (
              <div className="pt-1">
                <div className="mb-1 text-[11px] uppercase tracking-[0.12em] text-ink-faint">Evidence</div>
                <div className="flex flex-wrap gap-2">
                  {narratorItem.evidence_refs.slice(0, 6).map((ref, idx) => {
                    const label =
                      typeof ref === "string"
                        ? evidenceLabel(ref)
                        : evidenceLabel(String((ref as Record<string, unknown>).type || "evidence"));
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

      <Panel className="space-y-3">
        <div className="flex items-center justify-between border-b border-line pb-2">
          <h2 className="text-sm font-semibold text-ink">Analyst Narrative</h2>
          <div className="flex items-center gap-2 text-xs text-ink-faint">
            <span>As of: {fmtDateTime(latest.data?.item?.generated_at || null)}</span>
            <span className={`inline-flex rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${reportFreshness.className}`}>
              {reportFreshness.label}
            </span>
            <span>{reportFreshness.detail}</span>
            <span>· Report ID: {latest.data?.item?.report_id || "-"}</span>
          </div>
        </div>

        {latest.isLoading ? (
          <div className="text-sm text-muted">Loading latest report...</div>
        ) : latest.isError ? (
          <div className="text-sm text-red-300">Failed to load latest analyst report.</div>
        ) : !latest.data?.item ? (
          <div className="text-sm text-muted">No report available for this type yet.</div>
        ) : (
          <div className="space-y-2">
            <p className="text-sm font-semibold text-ink">{summary?.headline || "No headline available."}</p>
            <p className="text-sm leading-6 text-ink-soft">{summary?.plain_summary || "No narrative summary available."}</p>
          </div>
        )}
      </Panel>

      <Panel className="min-w-0 space-y-3 overflow-hidden">
        <div className="flex items-center justify-between border-b border-line pb-2">
          <h2 className="text-sm font-semibold text-ink">Per-Ticker Decision Trace</h2>
          <span className="text-xs text-ink-faint">{fmtNumber(filteredRows.length)} rows</span>
        </div>

        {latest.isLoading ? (
          <div className="text-sm text-muted">Loading decision traces...</div>
        ) : latest.isError ? (
          <div className="text-sm text-red-300">Failed to load decision traces.</div>
        ) : filteredRows.length === 0 ? (
          <div className="text-sm text-muted">No ticker decisions for selected filters.</div>
        ) : (
          <div className="max-h-[60vh] overflow-auto rounded-xl border border-line xl:max-h-[calc(100vh-360px)]">
            <table className="w-full min-w-[1160px] text-sm">
              <thead className="sticky top-0 z-10 bg-inset/95">
                <tr className="text-left text-[11px] uppercase tracking-[0.12em] text-ink-faint">
                  <th className="px-3 py-2">Ticker</th>
                  <th className="px-2 py-2">Direction</th>
                  <th className="px-2 py-2">Confidence</th>
                  <th className="px-2 py-2">Strength</th>
                  <th className="px-2 py-2">Convergence</th>
                  <th className="px-2 py-2">Signals (P/A/S)</th>
                  <th className="px-2 py-2">Bias Basis</th>
                  <th className="px-3 py-2">Anomalies</th>
                </tr>
              </thead>
              <tbody>
                {filteredRows.map((row, idx) => {
                  const anomalies = row.final?.anomalies || [];
                  const signalPack = `${row.inputs?.price || "-"} / ${row.inputs?.announcement || "-"} / ${row.inputs?.sentiment || "-"}`;
                  return (
                    <tr key={`${row.ticker || "ticker"}-${idx}`} className="border-t border-line hover:bg-hover">
                      <td className="px-3 py-2 font-medium text-ink">{row.ticker || "-"}</td>
                      <td className="px-2 py-2"><Badge value={directionTone(row.final?.direction)} /></td>
                      <td className="px-2 py-2 text-ink-soft">{fmtDecimal(row.final?.confidence_pct ?? null, 1)}%</td>
                      <td className="px-2 py-2 text-ink-soft">{fmtNumber(row.final?.strength ?? null)}</td>
                      <td className="px-2 py-2 text-ink-soft">{fmtNumber(row.final?.convergence_score ?? null)}</td>
                      <td className="px-2 py-2 text-xs text-muted">{signalPack}</td>
                      <td className="px-2 py-2 text-xs text-ink-soft">{biasBasis(row)}</td>
                      <td className="px-3 py-2 text-xs text-amber-300">{anomalies.length ? anomalies.join(", ") : "-"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Panel className="min-w-0 space-y-3 overflow-hidden">
        <div className="flex items-center justify-between border-b border-line pb-2">
          <h2 className="text-sm font-semibold text-ink">Report History</h2>
          <span className="text-xs text-ink-faint">{fmtNumber(history.data?.items?.length ?? 0)} records</span>
        </div>

        {history.isLoading ? (
          <div className="text-sm text-muted">Loading report history...</div>
        ) : history.isError ? (
          <div className="text-sm text-red-300">Failed to load report history.</div>
        ) : (
          <div className="max-h-[320px] overflow-auto rounded-xl border border-line">
            <table className="w-full min-w-[620px] text-sm">
              <thead className="sticky top-0 z-10 bg-inset/95">
                <tr className="text-left text-[11px] uppercase tracking-[0.12em] text-ink-faint">
                  <th className="px-3 py-2">Period</th>
                  <th className="px-2 py-2">Status</th>
                  <th className="px-2 py-2">Generated</th>
                  <th className="px-3 py-2">Degraded</th>
                </tr>
              </thead>
              <tbody>
                {(history.data?.items || []).map((item) => (
                  <tr key={item.report_id || `${item.report_type}-${item.period_key}`} className="border-t border-line hover:bg-hover">
                    <td className="px-3 py-2 text-ink">{item.period_key || "-"}</td>
                    <td className="px-2 py-2"><Badge value={normalizeStatus(item.status)} /></td>
                    <td className="px-2 py-2 text-ink-soft">{fmtDateTime(item.generated_at)}</td>
                    <td className="px-3 py-2 text-ink-soft">{item.degraded ? "yes" : "no"}</td>
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
