import { z } from "zod";

export const EvidenceRefSchema = z.object({
  type: z.string().optional(),
  source_id: z.string().optional(),
  timestamp: z.string().nullable().optional(),
  url_or_id: z.string().optional(),
  confidence: z.number().nullable().optional(),
});

export const TickerInsightSchema = z.object({
  ticker: z.string().optional(),
  summary: z.string().optional(),
  outlook: z.string().optional(),
  confidence: z.number().nullable().optional(),
  evidence_refs: z.array(EvidenceRefSchema).optional(),
});

export const InsightQualitySchema = z.object({
  coverage_pct: z.number().optional(),
  freshness_score: z.number().optional(),
  confidence_score: z.number().optional(),
  degradation_flags: z.array(z.string()).optional(),
});

export const HumanSummaryV2Schema = z
  .object({
    headline: z.string().nullable().optional(),
    plain_summary: z.string().nullable().optional(),
    key_drivers: z.array(z.string()).optional(),
    risks: z.array(z.string()).optional(),
    sector_highlights: z.array(z.string()).optional(),
    ticker_insights: z.array(TickerInsightSchema).optional(),
    quality: InsightQualitySchema.nullable().optional(),
    evidence_refs: z.array(EvidenceRefSchema).optional(),
    next_watch: z.array(z.string()).optional(),
  })
  .nullable()
  .optional();

