import { z } from "zod";

export const RunItemSchema = z.object({
  run_id: z.string(),
  agent_name: z.string(),
  status: z.string(),
  started_at: z.string().nullable().optional(),
  finished_at: z.string().nullable().optional(),
  metrics: z.record(z.any()).optional(),
  error_message: z.string().nullable().optional(),
  records_processed: z.number().nullable().optional(),
  records_new: z.number().nullable().optional(),
  errors_count: z.number().nullable().optional(),
  status_reason: z.string().nullable().optional(),
  is_stale_reconciled: z.boolean().optional(),
});

export const RunListSchema = z.object({
  items: z.array(RunItemSchema),
});

export type RunItem = z.infer<typeof RunItemSchema>;
