import { http } from "@/shared/lib/http";
import { StoryMonitorSnapshotSchema } from "@/entities/story/monitor.schema";

export async function fetchStoryMonitorSnapshot(options: {
  window_minutes?: number;
  events_limit?: number;
  cycles_limit?: number;
} = {}) {
  return StoryMonitorSnapshotSchema.parse(
    await http.get("/stories/monitor/snapshot", {
      window_minutes: options.window_minutes ?? 30,
      events_limit: options.events_limit ?? 20,
      cycles_limit: options.cycles_limit ?? 5,
    }),
  );
}
