import { http } from "@/shared/lib/http";
import { ArchiveLatestSchema } from "@/entities/archive/schema";

export async function fetchLatestArchive(run_type: "weekly" | "monthly" = "weekly") {
  const raw = await http.get<Record<string, unknown>>("/archive/latest", { run_type });
  const normalized = raw && typeof raw === "object" && "item" in raw ? raw : { item: raw };
  return ArchiveLatestSchema.parse(normalized);
}
