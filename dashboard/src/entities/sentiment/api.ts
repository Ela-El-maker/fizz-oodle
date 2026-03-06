import { http } from "@/shared/lib/http";
import { SentimentDigestSchema, ThemeSentimentSchema, WeeklySentimentSchema } from "@/entities/sentiment/schema";
import type { SentimentFilters } from "@/entities/sentiment/types";

export async function fetchSentimentDigestLatest() {
  const raw = await http.get<Record<string, unknown>>("/sentiment/digest/latest");
  const item = (raw.item ?? null) as Record<string, unknown> | null;
  const normalized = item
      ? {
        item: {
          ...item,
          sent_at:
            (item.sent_at as string | undefined) ??
            (item.email_sent_at as string | undefined) ??
            (item.generated_at as string | undefined) ??
            null,
        },
      }
    : { item: null };
  return SentimentDigestSchema.parse(normalized);
}

export async function fetchWeeklySentiment(filters: SentimentFilters = {}) {
  const raw = await http.get<{ items?: Array<Record<string, unknown>> }>("/sentiment/weekly", filters);
  const normalized = {
    ...raw,
    items: (raw.items || []).map((item) => ({
      ...item,
      mentions: Number(item.mentions ?? item.mentions_count ?? 0),
    })),
  };
  return WeeklySentimentSchema.parse(normalized);
}

export async function fetchSentimentSourceHealth() {
  return await http.get<{ items?: Array<Record<string, unknown>> }>("/sentiment/sources/health");
}

export async function fetchThemeSentimentWeekly(week_start?: string) {
  return ThemeSentimentSchema.parse(
    await http.get("/sentiment/themes/weekly", {
      week_start,
    }),
  );
}
