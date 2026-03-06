import { http } from "@/shared/lib/http";
import {
  AnnouncementsListSchema,
  AnnouncementStatsSchema,
  AnnouncementInsightResponseSchema,
  AnnouncementContextRefreshSchema,
} from "@/entities/announcement/schema";
import type { AnnouncementFilters } from "@/entities/announcement/types";

export async function fetchAnnouncements(filters: AnnouncementFilters = {}) {
  return AnnouncementsListSchema.parse(await http.get("/announcements", filters));
}

export async function fetchAnnouncementStats() {
  return AnnouncementStatsSchema.parse(await http.get("/announcements/stats"));
}

export async function fetchAnnouncementSourceHealth() {
  return await http.get<{ items?: Array<Record<string, unknown>> }>("/sources/health");
}

export async function fetchAnnouncementInsight(
  announcementId: string,
  options: { refresh_context_if_needed?: boolean; force_regenerate?: boolean } = {},
) {
  return AnnouncementInsightResponseSchema.parse(
    await http.get(`/announcements/${announcementId}/insight`, {
      refresh_context_if_needed: options.refresh_context_if_needed ?? true,
      force_regenerate: options.force_regenerate ?? false,
    }),
  );
}

export async function refreshAnnouncementContext(announcementId: string) {
  return AnnouncementContextRefreshSchema.parse(
    await http.post(`/announcements/${announcementId}/context/refresh`),
  );
}
