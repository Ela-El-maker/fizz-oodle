import { http } from "@/shared/lib/http";
import { StoryLatestSchema, StoriesListSchema } from "@/entities/story/schema";

export async function fetchLatestStory(options: {
  scope?: string;
  context?: string;
  ticker?: string;
  force_regenerate?: boolean;
} = {}) {
  return StoryLatestSchema.parse(
    await http.get("/stories/latest", {
      scope: options.scope ?? "market",
      context: options.context ?? "prices",
      ticker: options.ticker,
      force_regenerate: options.force_regenerate ?? false,
    }),
  );
}

export async function fetchStories(options: {
  scope?: string;
  ticker?: string;
  status?: string;
  limit?: number;
  offset?: number;
} = {}) {
  return StoriesListSchema.parse(
    await http.get("/stories", {
      scope: options.scope,
      ticker: options.ticker,
      status: options.status,
      limit: options.limit ?? 50,
      offset: options.offset ?? 0,
    }),
  );
}

export async function rebuildStories(forceRegenerate = true) {
  return await http.post("/stories/rebuild", { force_regenerate: forceRegenerate });
}
