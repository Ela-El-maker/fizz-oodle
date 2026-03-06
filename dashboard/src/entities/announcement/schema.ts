import { z } from "zod";
import { HumanSummaryV2Schema } from "@/shared/types/humanSummary";

export const AnnouncementSchema = z.object({
  announcement_id: z.string(),
  ticker: z.string().nullable().optional(),
  company: z.string().nullable().optional(),
  source_id: z.string().nullable().optional(),
  announcement_type: z.string().nullable().optional(),
  headline: z.string().nullable().optional(),
  url: z.string().nullable().optional(),
  canonical_url: z.string().nullable().optional(),
  announcement_date: z.string().nullable().optional(),
  type_confidence: z.number().nullable().optional(),
  details: z.string().nullable().optional(),
  first_seen_at: z.string().nullable().optional(),
  last_seen_at: z.string().nullable().optional(),
  alerted: z.boolean().nullable().optional(),
  alerted_at: z.string().nullable().optional(),
  severity: z.string().nullable().optional(),
  severity_score: z.number().nullable().optional(),
  scope: z.string().nullable().optional(),
  source_scope_label: z.string().nullable().optional(),
  theme: z.string().nullable().optional(),
  signal_class: z.string().nullable().optional(),
  market_region: z.string().nullable().optional(),
  kenya_impact_score: z.number().nullable().optional(),
  affected_sectors: z.array(z.string()).optional(),
  transmission_channels: z.array(z.string()).optional(),
  promoted_to_core_feed: z.boolean().nullable().optional(),
  alpha_context: z.record(z.any()).nullable().optional(),
});

export const AnnouncementsListSchema = z.object({
  items: z.array(AnnouncementSchema),
  total: z.number().optional(),
  limit: z.number().optional(),
  offset: z.number().optional(),
});

export const AnnouncementStatsSchema = z.object({
  total: z.number().optional(),
  alerted: z.number().optional(),
  unalerted: z.number().optional(),
  kenya_core_total: z.number().optional(),
  kenya_extended_total: z.number().optional(),
  global_outside_total: z.number().optional(),
  high_impact_global_total: z.number().optional(),
  by_theme: z.record(z.number()).optional(),
  high_impact_global_by_theme: z.record(z.number()).optional(),
  global_impact_threshold: z.number().optional(),
  human_summary: z
    .object({
      headline: z.string().nullable().optional(),
      plain_summary: z.string().nullable().optional(),
      bullets: z.array(z.string()).optional(),
    })
    .nullable()
    .optional(),
  human_summary_v2: HumanSummaryV2Schema,
});

export const AnnouncementInsightSchema = z.object({
  version: z.string().nullable().optional(),
  generated_at: z.string().nullable().optional(),
  source: z
    .object({
      id: z.string().nullable().optional(),
      url: z.string().nullable().optional(),
      canonical_url: z.string().nullable().optional(),
    })
    .nullable()
    .optional(),
  headline: z.string().nullable().optional(),
  classification: z
    .object({
      announcement_type: z.string().nullable().optional(),
      severity: z.string().nullable().optional(),
      confidence: z.number().nullable().optional(),
    })
    .nullable()
    .optional(),
  insight: z
    .object({
      what_happened: z.string().nullable().optional(),
      why_it_matters: z.string().nullable().optional(),
      market_impact: z.string().nullable().optional(),
      sector_impact: z.string().nullable().optional(),
      competitor_watch: z.string().nullable().optional(),
      what_to_watch_next: z.array(z.string()).optional(),
    })
    .nullable()
    .optional(),
  quality: z
    .object({
      llm_used: z.boolean().nullable().optional(),
      fallback_used: z.boolean().nullable().optional(),
      fallback_mode: z.string().nullable().optional(),
      context_refreshed: z.boolean().nullable().optional(),
      context_age_minutes: z.number().nullable().optional(),
      coverage_score: z.number().nullable().optional(),
      freshness_score: z.number().nullable().optional(),
      reason_codes: z.array(z.string()).optional(),
      llm_error: z.string().nullable().optional(),
    })
    .nullable()
    .optional(),
  evidence_refs: z.array(z.record(z.any())).optional(),
  status: z.string().nullable().optional(),
  research_links: z
    .array(
      z.object({
        label: z.string().nullable().optional(),
        url: z.string().nullable().optional(),
      }),
    )
    .optional(),
});

export const AnnouncementInsightResponseSchema = z.object({
  announcement_id: z.string(),
  item: AnnouncementInsightSchema,
  meta: z.record(z.any()).optional(),
});

export const AnnouncementContextRefreshSchema = z.object({
  announcement_id: z.string(),
  refresh: z.record(z.any()),
  details_length: z.number().optional(),
  last_seen_at: z.string().nullable().optional(),
  url: z.string().nullable().optional(),
  canonical_url: z.string().nullable().optional(),
});
