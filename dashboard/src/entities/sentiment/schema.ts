import { z } from "zod";
import { HumanSummaryV2Schema } from "@/shared/types/humanSummary";

export const SentimentDigestItemSchema = z.object({
  week_start: z.string().nullable().optional(),
  status: z.string().nullable().optional(),
  sent_at: z.string().nullable().optional(),
  generated_at: z.string().nullable().optional(),
  human_summary: z
    .object({
      headline: z.string().nullable().optional(),
      plain_summary: z.string().nullable().optional(),
      bullets: z.array(z.string()).optional(),
      coverage: z
        .object({
          tickers_with_signal: z.number().optional(),
          total_tickers: z.number().optional(),
        })
        .nullable()
        .optional(),
    })
    .nullable()
    .optional(),
  human_summary_v2: HumanSummaryV2Schema,
  theme_summary: z
    .object({
      week_start: z.string().nullable().optional(),
      items: z
        .array(
          z.object({
            theme: z.string(),
            theme_group: z.string().optional(),
            mentions: z.number(),
            bullish_pct: z.number(),
            bearish_pct: z.number(),
            neutral_pct: z.number(),
            weighted_score: z.number(),
            confidence: z.number(),
            kenya_relevance_avg: z.number(),
            wow_delta: z.number().nullable().optional(),
            top_sources: z.record(z.number()).optional(),
          }),
        )
        .optional(),
    })
    .nullable()
    .optional(),
});

export const SentimentDigestSchema = z.object({
  item: SentimentDigestItemSchema.nullable().optional(),
});

export const WeeklySentimentRowSchema = z.object({
  ticker: z.string().nullable().optional(),
  company_name: z.string().nullable().optional(),
  mentions_count: z.number().nullable().optional(),
  mentions: z.number().nullable().optional(),
  bullish_pct: z.number().nullable().optional(),
  bearish_pct: z.number().nullable().optional(),
  neutral_pct: z.number().nullable().optional(),
  wow_delta: z.number().nullable().optional(),
  top_sources: z.record(z.number()).nullable().optional(),
  weighted_score: z.number().nullable().optional(),
  confidence: z.number().nullable().optional(),
});

export const WeeklySentimentSchema = z.object({
  items: z.array(WeeklySentimentRowSchema),
});

export const ThemeSentimentRowSchema = z.object({
  theme: z.string(),
  theme_group: z.string().optional(),
  mentions: z.number(),
  bullish_pct: z.number(),
  bearish_pct: z.number(),
  neutral_pct: z.number(),
  weighted_score: z.number(),
  confidence: z.number(),
  kenya_relevance_avg: z.number(),
  wow_delta: z.number().nullable().optional(),
  top_sources: z.record(z.number()).optional(),
});

export const ThemeSentimentSchema = z.object({
  week_start: z.string().nullable().optional(),
  items: z.array(ThemeSentimentRowSchema),
});
