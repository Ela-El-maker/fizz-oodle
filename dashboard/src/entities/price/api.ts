import { http } from "@/shared/lib/http";
import { DailyPricesSchema } from "@/entities/price/schema";

export async function fetchDailyPrices(date?: string) {
  const raw = await http.get<Record<string, unknown>>("/prices/daily", { date });
  return DailyPricesSchema.parse(raw);
}

