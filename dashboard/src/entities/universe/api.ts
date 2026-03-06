import { http } from "@/shared/lib/http";
import { UniverseSummarySchema } from "@/entities/universe/schema";

export async function fetchUniverseSummary() {
  return UniverseSummarySchema.parse(await http.get("/universe/summary"));
}
