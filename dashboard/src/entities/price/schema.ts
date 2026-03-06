import { z } from "zod";

export const PriceRowSchema = z.object({
  ticker: z.string(),
  close: z.number().nullable().optional(),
  open: z.number().nullable().optional(),
  high: z.number().nullable().optional(),
  low: z.number().nullable().optional(),
  volume: z.number().nullable().optional(),
  currency: z.string().nullable().optional(),
  source_id: z.string().nullable().optional(),
});

export const DailyPricesSchema = z.object({
  date: z.string().nullable().optional(),
  items: z.array(PriceRowSchema),
});

