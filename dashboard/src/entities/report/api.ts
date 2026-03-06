import { http } from "@/shared/lib/http";
import { ReportLatestSchema, ReportsListSchema } from "@/entities/report/schema";
import type { ReportsFilters } from "@/entities/report/types";

export async function fetchLatestReport(type: "daily" | "weekly") {
  return ReportLatestSchema.parse(await http.get("/reports/latest", { type }));
}

export async function fetchReports(filters: ReportsFilters = {}) {
  return ReportsListSchema.parse(await http.get("/reports", filters));
}
