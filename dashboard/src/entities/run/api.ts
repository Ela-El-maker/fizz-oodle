import { http } from "@/shared/lib/http";
import { RunListSchema } from "@/entities/run/schema";
import type { RunFilters } from "@/entities/run/types";

export async function fetchRuns(filters: RunFilters = {}) {
  return RunListSchema.parse(await http.get("/runs", filters));
}

export async function triggerAgent(agent: string, params?: Record<string, string | boolean | undefined>) {
  return await http.post<{ run_id: string; status: string }>(`/run/${agent}`, undefined, params);
}
