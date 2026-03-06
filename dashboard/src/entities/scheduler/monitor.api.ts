import { http } from "@/shared/lib/http";
import { SchedulerImpactSchema, SchedulerMonitorSnapshotSchema } from "@/entities/scheduler/monitor.schema";

export async function fetchSchedulerMonitorSnapshot(options: {
  hours?: number;
  events_limit?: number;
  failed_agent?: string;
} = {}) {
  return SchedulerMonitorSnapshotSchema.parse(
    await http.get("/scheduler/monitor/snapshot", {
      hours: options.hours ?? 24,
      events_limit: options.events_limit ?? 50,
      failed_agent: options.failed_agent,
    }),
  );
}

export async function fetchSchedulerImpact(failed_agent: string) {
  return SchedulerImpactSchema.parse(
    await http.get("/scheduler/monitor/impact", { failed_agent }),
  );
}

export async function dispatchScheduleNow(scheduleKey: string) {
  return http.post(`/scheduler/control/dispatch/${encodeURIComponent(scheduleKey)}`);
}

export async function retryRun(runId: string) {
  return http.post(`/scheduler/control/retry/${encodeURIComponent(runId)}`);
}

export async function rebuildNarrator(force_regenerate = true) {
  return http.post("/scheduler/control/rebuild-narrator", undefined, { force_regenerate });
}
