import { z } from "zod";

export const EmailValidationSchema = z.object({
  item: z
    .object({
      validation_run_id: z.string().optional(),
      window: z.string().nullable().optional(),
      period_key: z.string().nullable().optional(),
      status: z.string().nullable().optional(),
      started_at: z.string().nullable().optional(),
      finished_at: z.string().nullable().optional(),
      summary_json: z.record(z.any()).optional(),
      steps: z.array(z.record(z.any())).optional(),
    })
    .nullable()
    .optional(),
});
