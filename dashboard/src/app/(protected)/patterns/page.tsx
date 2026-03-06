"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchPatterns, fetchPatternSummary } from "@/entities/pattern/api";
import { fetchLatestArchive } from "@/entities/archive/api";
import { fetchLatestStory } from "@/entities/story/api";
import { Panel } from "@/shared/ui/Panel";
import { StatCard } from "@/shared/ui/StatCard";
import { Select } from "@/shared/ui/Select";
import { Input } from "@/shared/ui/Input";
import { Badge } from "@/shared/ui/Badge";
import { fmtDateTime, fmtDecimal, fmtNumber } from "@/shared/lib/format";

type SortMode =
  | "confidence_desc"
  | "accuracy_desc"
  | "occurrences_desc"
  | "impact1d_desc"
  | "updated_desc"
  | "ticker_asc";

function evidenceLabel(value: string): string {
  return value.replace(/_/g, " ").replace(/\s+/g, " ").trim();
}

function numberOrZero(value: number | null | undefined): number {
  return Number(value ?? 0);
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

function latestIso(values: Array<string | null | undefined>): string | null {
  let best: string | null = null;
  let bestTs = -1;
  for (const value of values) {
    if (!value) continue;
    const ts = Date.parse(value);
    if (Number.isNaN(ts)) continue;
    if (ts > bestTs) {
      bestTs = ts;
      best = value;
    }
  }
  return best;
}

export default function PatternsPage() {
  const [tickerFilter, setTickerFilter] = useState("all");
  const [statusFilter, setStatusFilter] = useState("all");
  const [patternTypeFilter, setPatternTypeFilter] = useState("all");
  const [sortMode, setSortMode] = useState<SortMode>("updated_desc");
  const [search, setSearch] = useState("");
  const [expandNarrator, setExpandNarrator] = useState(false);

  const summary = useQuery({
    queryKey: ["pattern-summary", "page"],
    queryFn: fetchPatternSummary,
    refetchInterval: 30000,
    staleTime: 30000,
  });
  const patterns = useQuery({
    queryKey: ["patterns", "page", 200],
    queryFn: () => fetchPatterns({ limit: 200 }),
    refetchInterval: 30000,
    staleTime: 30000,
  });
  const narrator = useQuery({
    queryKey: ["stories-latest", "pattern", "summary"],
    queryFn: () => fetchLatestStory({ scope: "pattern", context: "summary" }),
    refetchInterval: 30000,
    staleTime: 30000,
  });
  const archive = useQuery({
    queryKey: ["archive-latest", "weekly", "patterns-page"],
    queryFn: () => fetchLatestArchive("weekly"),
    refetchInterval: 30000,
    staleTime: 30000,
  });

  const items = useMemo(() => patterns.data?.items ?? [], [patterns.data?.items]);

  const tickerOptions = useMemo(() => {
    const set = new Set<string>();
    for (const item of items) {
      if (item.ticker) set.add(item.ticker);
    }
    return Array.from(set).sort();
  }, [items]);

  const statusOptions = useMemo(() => {
    const set = new Set<string>();
    for (const item of items) {
      if (item.status) set.add(item.status);
    }
    return Array.from(set).sort();
  }, [items]);

  const typeOptions = useMemo(() => {
    const set = new Set<string>();
    for (const item of items) {
      if (item.pattern_type) set.add(item.pattern_type);
    }
    return Array.from(set).sort();
  }, [items]);

  const filtered = useMemo(() => {
    const q = search.trim().toUpperCase();
    let out = items.filter((item) => {
      if (tickerFilter !== "all" && item.ticker !== tickerFilter) return false;
      if (statusFilter !== "all" && item.status !== statusFilter) return false;
      if (patternTypeFilter !== "all" && item.pattern_type !== patternTypeFilter) return false;
      if (!q) return true;
      return (
        (item.ticker || "").toUpperCase().includes(q) ||
        (item.pattern_type || "").toUpperCase().includes(q) ||
        (item.description || "").toUpperCase().includes(q)
      );
    });

    out = [...out].sort((a, b) => {
      if (sortMode === "ticker_asc") return (a.ticker || "").localeCompare(b.ticker || "");
      if (sortMode === "confidence_desc") return numberOrZero(b.confidence_pct) - numberOrZero(a.confidence_pct);
      if (sortMode === "accuracy_desc") return numberOrZero(b.accuracy_pct) - numberOrZero(a.accuracy_pct);
      if (sortMode === "occurrences_desc") return numberOrZero(b.occurrence_count) - numberOrZero(a.occurrence_count);
      if (sortMode === "impact1d_desc") return numberOrZero(b.avg_impact_1d) - numberOrZero(a.avg_impact_1d);
      return Date.parse(b.updated_at || "1970-01-01T00:00:00Z") - Date.parse(a.updated_at || "1970-01-01T00:00:00Z");
    });

    return out;
  }, [items, patternTypeFilter, search, sortMode, statusFilter, tickerFilter]);

  const narratorItem = narrator.data?.item;
  const narratorHeadline = narratorItem?.headline || narratorItem?.title || "Pattern Explainer";
  const narratorParagraphs = narratorItem?.paragraphs || [];
  const narratorVisible = expandNarrator ? narratorParagraphs : narratorParagraphs.slice(0, 3);
  const narratorFreshness = freshnessMeta(narratorItem?.generated_at || null);
  const archiveMetrics = ((archive.data?.item?.summary || {}) as Record<string, unknown>).metrics as
    | Record<string, unknown>
    | undefined;
  const lifecycleThresholds = (archiveMetrics?.lifecycle_thresholds as Record<string, unknown> | undefined) || {};
  const globalPatternContext =
    (archiveMetrics?.global_pattern_context as Record<string, unknown> | undefined) || {};
  const globalTopThemes =
    (globalPatternContext.top_themes as Array<Record<string, unknown>> | undefined) || [];
  const globalPatternCandidates =
    (globalPatternContext.global_pattern_candidates as Array<Record<string, unknown>> | undefined) || [];
  const replacementPressure = (archiveMetrics?.replacement_pressure as Record<string, unknown> | undefined) || {};
  const replacementPressurePost = (archiveMetrics?.replacement_pressure_post as Record<string, unknown> | undefined) || {};
  const marketRegime = (archiveMetrics?.market_regime as string | undefined) || "unknown";
  const allowPatternPromotion = archiveMetrics?.allow_pattern_promotion as boolean | undefined;
  const allowPatternPromotionReason = (archiveMetrics?.allow_pattern_promotion_reason as string | undefined) || null;
  const replacementHigh = Boolean(
    replacementPressurePost.replacement_pressure_high ?? replacementPressure.replacement_pressure_high
  );
  const replacementRatio = (replacementPressurePost.retired_dominance_ratio as number | undefined)
    ?? (replacementPressure.retired_dominance_ratio as number | undefined)
    ?? null;
  const promoteThreshold = (lifecycleThresholds.promotion_threshold_pct as number | undefined) ?? null;
  const retireThreshold = (lifecycleThresholds.retire_threshold_pct as number | undefined) ?? null;
  const minConfirm = (lifecycleThresholds.min_occurrences_for_confirm as number | undefined) ?? null;
  const minRetire = (lifecycleThresholds.min_occurrences_for_retire as number | undefined) ?? null;

  const avgConfidence = useMemo(() => {
    if (filtered.length === 0) return null;
    const values = filtered.map((item) => numberOrZero(item.confidence_pct));
    return values.reduce((a, b) => a + b, 0) / values.length;
  }, [filtered]);

  const avgAccuracy = useMemo(() => {
    if (filtered.length === 0) return null;
    const values = filtered.map((item) => numberOrZero(item.accuracy_pct));
    return values.reduce((a, b) => a + b, 0) / values.length;
  }, [filtered]);

  const pageUpdatedAt = useMemo(
    () =>
      latestIso([
        items[0]?.updated_at,
        archive.data?.item?.created_at,
        archive.data?.item?.updated_at,
        narratorItem?.generated_at,
      ]),
    [archive.data?.item?.created_at, archive.data?.item?.updated_at, items, narratorItem?.generated_at],
  );

  return (
    <div className="space-y-4">
      <Panel>
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-base font-semibold text-ink">Patterns · Outcome Memory (Agent E)</h1>
            <p className="mt-1 text-xs text-muted">
              Pattern lifecycle dashboard for confidence, reliability, and historical outcome tracking.
            </p>
          </div>
          <div className="text-xs text-ink-faint">Updated: {fmtDateTime(pageUpdatedAt)}</div>
        </div>
      </Panel>

      <Panel>
        <div className="grid gap-3 grid-cols-2 md:grid-cols-3 lg:grid-cols-5">
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
            <label className="mb-1 block text-[11px] uppercase tracking-[0.12em] text-ink-faint">Status</label>
            <Select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
              <option value="all">All statuses</option>
              {statusOptions.map((status) => (
                <option key={status} value={status}>
                  {status}
                </option>
              ))}
            </Select>
          </div>
          <div>
            <label className="mb-1 block text-[11px] uppercase tracking-[0.12em] text-ink-faint">Pattern Type</label>
            <Select value={patternTypeFilter} onChange={(e) => setPatternTypeFilter(e.target.value)}>
              <option value="all">All types</option>
              {typeOptions.map((type) => (
                <option key={type} value={type}>
                  {type}
                </option>
              ))}
            </Select>
          </div>
          <div>
            <label className="mb-1 block text-[11px] uppercase tracking-[0.12em] text-ink-faint">Sort</label>
            <Select value={sortMode} onChange={(e) => setSortMode(e.target.value as SortMode)}>
              <option value="updated_desc">Updated (Newest)</option>
              <option value="confidence_desc">Confidence (High to Low)</option>
              <option value="accuracy_desc">Accuracy (High to Low)</option>
              <option value="occurrences_desc">Occurrences (High to Low)</option>
              <option value="impact1d_desc">Impact 1D (High to Low)</option>
              <option value="ticker_asc">Ticker (A-Z)</option>
            </Select>
          </div>
          <div>
            <label className="mb-1 block text-[11px] uppercase tracking-[0.12em] text-ink-faint">Search</label>
            <Input placeholder="Ticker, pattern type, text..." value={search} onChange={(e) => setSearch(e.target.value)} />
          </div>
        </div>
      </Panel>

      <div className="grid gap-3 sm:grid-cols-3 xl:grid-cols-7">
        <StatCard label="Total" value={fmtNumber(summary.data?.total_count)} tone="brand" />
        <StatCard label="Active" value={fmtNumber(summary.data?.active_count)} tone="success" />
        <StatCard label="Confirmed" value={fmtNumber(summary.data?.confirmed_count)} tone="success" />
        <StatCard label="Candidate" value={fmtNumber(summary.data?.candidate_count)} tone="warning" />
        <StatCard label="Retired" value={fmtNumber(summary.data?.retired_count)} tone="neutral" />
        <StatCard
          label="Avg Confidence"
          value={avgConfidence === null ? "-" : `${fmtDecimal(avgConfidence, 1)}%`}
          tone="neutral"
        />
        <StatCard
          label="Avg Accuracy"
          value={avgAccuracy === null ? "-" : `${fmtDecimal(avgAccuracy, 1)}%`}
          tone="neutral"
        />
      </div>

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
        <StatCard
          label="Market Regime"
          value={(marketRegime || "unknown").replace(/_/g, " ")}
          hint="inferred from latest Analyst signal intelligence"
          tone={String(marketRegime).startsWith("risk_off") ? "warning" : "neutral"}
        />
        <StatCard
          label="Promotion Gate"
          value={allowPatternPromotion === undefined ? "-" : allowPatternPromotion ? "Enabled" : "Paused"}
          hint={allowPatternPromotionReason || "awaiting archive metrics"}
          tone={allowPatternPromotion ? "success" : "warning"}
        />
        <StatCard
          label="Replacement Pressure"
          value={replacementHigh ? "High" : "Normal"}
          hint={replacementRatio === null ? "ratio unavailable" : `retired dominance ${fmtDecimal(replacementRatio, 2)}x`}
          tone={replacementHigh ? "warning" : "success"}
        />
        <StatCard
          label="Lifecycle Thresholds"
          value={promoteThreshold === null ? "-" : `${fmtDecimal(promoteThreshold, 1)} / ${fmtDecimal(retireThreshold, 1)}%`}
          hint={minConfirm === null ? "promote / retire" : `min obs ${fmtNumber(minConfirm)} / ${fmtNumber(minRetire)}`}
          tone="neutral"
        />
      </div>

      <Panel className="space-y-3">
        <div className="flex items-center justify-between border-b border-line pb-2">
          <h2 className="text-sm font-semibold text-ink">Global Pattern Context</h2>
          <span className="text-xs text-ink-faint">
            High-impact global announcements {fmtNumber(Number(globalPatternContext.high_impact_global_announcements ?? 0))}
          </span>
        </div>
        {globalTopThemes.length === 0 && globalPatternCandidates.length === 0 ? (
          <div className="text-sm text-muted">No global pattern context available for this archive window.</div>
        ) : (
          <div className="grid gap-3 lg:grid-cols-2">
            <div className="space-y-2 rounded-lg border border-line bg-panel-soft p-3">
              <div className="text-[11px] uppercase tracking-[0.12em] text-ink-faint">Top Themes</div>
              {globalTopThemes.slice(0, 6).map((row, idx) => (
                <div key={`g-theme-${idx}`} className="flex items-center justify-between gap-2 text-xs text-ink-soft">
                  <span>{String(row.theme || "global").replace(/_/g, " ")}</span>
                  <span>
                    Mentions {fmtNumber(Number(row.mentions ?? 0))} · Score {fmtDecimal(Number(row.weighted_score ?? 0), 3)}
                  </span>
                </div>
              ))}
            </div>
            <div className="space-y-2 rounded-lg border border-line bg-panel-soft p-3">
              <div className="text-[11px] uppercase tracking-[0.12em] text-ink-faint">Pattern Candidates</div>
              {globalPatternCandidates.length === 0 ? (
                <div className="text-xs text-muted">No candidate patterns from global-theme divergence yet.</div>
              ) : (
                globalPatternCandidates.slice(0, 6).map((row, idx) => (
                  <div key={`g-candidate-${idx}`} className="rounded border border-line bg-elevated/30 p-2">
                    <div className="flex items-center gap-2 text-[11px] text-muted">
                      <Badge value={String(row.pattern_type || "candidate")} />
                      <span>{String(row.theme || "global").replace(/_/g, " ")}</span>
                      <span>Conf {fmtDecimal(Number(row.confidence_pct ?? 0), 1)}%</span>
                    </div>
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
          <div className="text-sm text-muted">Loading narrator pattern explainer...</div>
        ) : narrator.isError ? (
          <div className="text-sm text-amber-300">Narrator is unavailable for pattern explainers right now.</div>
        ) : !narratorItem ? (
          <div className="text-sm text-muted">No narrator pattern explainer available yet.</div>
        ) : (
          <div className="space-y-2">
            <p className="text-sm font-semibold text-ink">{narratorHeadline}</p>
            {narratorVisible.map((paragraph, idx) => (
              <p key={`narrator-pattern-${idx}`} className="text-sm leading-6 text-ink-soft">
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
          <h2 className="text-sm font-semibold text-ink">Pattern Table</h2>
          <span className="text-xs text-ink-faint">{fmtNumber(filtered.length)} rows</span>
        </div>

        {summary.isLoading || patterns.isLoading ? (
          <div className="text-sm text-muted">Loading patterns...</div>
        ) : summary.isError || patterns.isError ? (
          <div className="text-sm text-red-300">Failed to load patterns data.</div>
        ) : filtered.length === 0 ? (
          <div className="text-sm text-muted">No patterns match your filters.</div>
        ) : (
          <div className="max-h-[calc(100vh-360px)] overflow-auto rounded-xl border border-line">
            <table className="w-full min-w-[980px] text-sm">
              <thead className="sticky top-0 z-10 bg-inset/95">
                <tr className="text-left text-[11px] uppercase tracking-[0.12em] text-ink-faint">
                  <th className="px-3 py-2">Ticker</th>
                  <th className="px-2 py-2">Pattern Type</th>
                  <th className="px-2 py-2">Status</th>
                  <th className="px-2 py-2">Confidence</th>
                  <th className="px-2 py-2">Accuracy</th>
                  <th className="px-2 py-2">Occurrences</th>
                  <th className="px-2 py-2">Impact 1D</th>
                  <th className="px-2 py-2">Impact 5D</th>
                  <th className="px-3 py-2">Updated</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((item) => (
                  <tr key={item.pattern_id || `${item.ticker || "ticker"}-${item.pattern_type || "type"}`} className="border-t border-line hover:bg-hover">
                    <td className="px-3 py-2 font-medium text-ink">{item.ticker || "-"}</td>
                    <td className="px-2 py-2 text-ink">{item.pattern_type || "-"}</td>
                    <td className="px-2 py-2"><Badge value={item.status || "unknown"} /></td>
                    <td className="px-2 py-2 text-ink-soft">{fmtDecimal(item.confidence_pct ?? null, 1)}%</td>
                    <td className="px-2 py-2 text-ink-soft">{fmtDecimal(item.accuracy_pct ?? null, 1)}%</td>
                    <td className="px-2 py-2 text-ink-soft">{fmtNumber(item.occurrence_count ?? null)}</td>
                    <td className="px-2 py-2 text-ink-soft">{fmtDecimal(item.avg_impact_1d ?? null, 2)}</td>
                    <td className="px-2 py-2 text-ink-soft">{fmtDecimal(item.avg_impact_5d ?? null, 2)}</td>
                    <td className="px-3 py-2 text-xs text-muted">{fmtDateTime(item.updated_at)}</td>
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
