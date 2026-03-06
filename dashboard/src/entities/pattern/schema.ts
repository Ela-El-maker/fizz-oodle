import { z } from "zod";

export const PatternItemSchema = z.object({
  pattern_id: z.string().optional(),
  ticker: z.string().nullable().optional(),
  pattern_type: z.string().nullable().optional(),
  description: z.string().nullable().optional(),
  status: z.string().nullable().optional(),
  confidence_pct: z.number().nullable().optional(),
  accuracy_pct: z.number().nullable().optional(),
  occurrence_count: z.number().nullable().optional(),
  avg_impact_1d: z.number().nullable().optional(),
  avg_impact_5d: z.number().nullable().optional(),
  active: z.boolean().nullable().optional(),
  updated_at: z.string().nullable().optional(),
});

export const PatternListSchema = z.object({
  items: z.array(PatternItemSchema),
});

export const PatternSummarySchema = z.object({
  total_count: z.number().optional(),
  active_count: z.number().optional(),
  confirmed_count: z.number().optional(),
  candidate_count: z.number().optional(),
  retired_count: z.number().optional(),
});
