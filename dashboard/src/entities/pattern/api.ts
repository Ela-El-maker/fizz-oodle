import { http } from "@/shared/lib/http";
import { PatternListSchema, PatternSummarySchema } from "@/entities/pattern/schema";
import type { PatternFilters } from "@/entities/pattern/types";

export async function fetchPatterns(filters: PatternFilters = {}) {
  return PatternListSchema.parse(await http.get("/patterns", filters));
}

export async function fetchActivePatterns(limit = 50) {
  return PatternListSchema.parse(await http.get("/patterns/active", { limit }));
}

export async function fetchPatternSummary() {
  const raw = await http.get<Record<string, unknown>>("/patterns/summary");
  return PatternSummarySchema.parse({
    total_count: Number(raw.total_count ?? raw.total ?? 0),
    active_count: Number(raw.active_count ?? raw.active ?? 0),
    confirmed_count: Number(raw.confirmed_count ?? raw.confirmed ?? 0),
    candidate_count: Number(raw.candidate_count ?? raw.candidate ?? 0),
    retired_count: Number(raw.retired_count ?? raw.retired ?? 0),
  });
}
