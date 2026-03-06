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

export const ArchiveLatestSchema = z.object({
  item: z
    .object({
      run_id: z.string().optional(),
      archive_run_id: z.string().optional(),
      run_type: z.string().nullable().optional(),
      period_key: z.string().nullable().optional(),
      status: z.string().nullable().optional(),
      summary: z.record(z.any()).optional(),
      human_summary: HumanSummarySchema,
      human_summary_v2: HumanSummaryV2Schema,
      created_at: z.string().nullable().optional(),
      updated_at: z.string().nullable().optional(),
    })
    .nullable()
    .optional(),
});
