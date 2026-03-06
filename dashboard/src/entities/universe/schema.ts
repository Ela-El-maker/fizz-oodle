import { z } from "zod";

export const UniverseSummarySchema = z.object({
  tracked_companies: z.number().optional(),
  tracked_tickers: z.number().optional(),
  nse_tickers: z.number().optional(),
  exchanges: z.record(z.number()).optional(),
  sectors: z.record(z.number()).optional(),
  tickers: z.array(z.string()).optional(),
});

export type UniverseSummary = z.infer<typeof UniverseSummarySchema>;
