import { z } from "zod";

export const StoryItemSchema = z.object({
  card_id: z.string().optional(),
  scope: z.string().nullable().optional(),
  context: z.string().nullable().optional(),
  scope_id: z.string().nullable().optional(),
  ticker: z.string().nullable().optional(),
  title: z.string().nullable().optional(),
  headline: z.string().nullable().optional(),
  paragraphs: z.array(z.string()).optional(),
  evidence_refs: z.array(z.union([z.string(), z.record(z.any())])).optional(),
  quality: z.record(z.any()).optional(),
  status: z.string().nullable().optional(),
  fallback_mode: z.string().nullable().optional(),
  generated_at: z.string().nullable().optional(),
  global_drivers: z
    .array(
      z.object({
        headline: z.string().optional(),
        theme: z.string().optional(),
        kenya_impact_score: z.number().optional(),
        source_id: z.string().optional().nullable(),
        signal_class: z.string().optional().nullable(),
        summary: z.string().optional(),
        affected_sectors: z.array(z.string()).optional(),
        transmission_channels: z.array(z.string()).optional(),
      }),
    )
    .optional(),
});

export const StoryLatestSchema = z.object({
  item: StoryItemSchema.nullable().optional(),
  meta: z.record(z.any()).optional(),
});

export const StoriesListSchema = z.object({
  items: z.array(StoryItemSchema),
  limit: z.number().optional(),
  offset: z.number().optional(),
});
