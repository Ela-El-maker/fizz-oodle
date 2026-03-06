import { z } from "zod";
import { HumanSummaryV2Schema } from "@/shared/types/humanSummary";

const HumanSummarySchema = z
  .object({
    headline: z.string().nullable().optional(),
    plain_summary: z.string().nullable().optional(),
    bullets: z.array(z.string()).optional(),
    coverage: z.record(z.any()).nullable().optional(),
    flags: z.record(z.any()).nullable().optional(),
  })
  .nullable()
  .optional();

export const ReportSchema = z.object({
  report_id: z.string().optional(),
  report_type: z.string().nullable().optional(),
  period_key: z.string().nullable().optional(),
  status: z.string().nullable().optional(),
  generated_at: z.string().nullable().optional(),
  degraded: z.boolean().nullable().optional(),
  llm_used: z.boolean().nullable().optional(),
  json_payload: z.record(z.any()).optional(),
  inputs_summary: z.record(z.any()).optional(),
  metrics: z.record(z.any()).optional(),
  human_summary: HumanSummarySchema,
  human_summary_v2: HumanSummaryV2Schema,
  email_sent_at: z.string().nullable().optional(),
  email_error: z.string().nullable().optional(),
});

export const ReportLatestSchema = z.object({
  item: ReportSchema.nullable().optional(),
});

export const ReportsListSchema = z.object({
  items: z.array(ReportSchema),
});
