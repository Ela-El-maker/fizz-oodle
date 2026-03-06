import { z } from "zod";

export const MonitorStatusSchema = z.object({
  agent_status: z.string(),
  current_task: z.string(),
  progress_pct: z.number(),
  progress_label: z.string(),
  started_at: z.string().nullable().optional(),
  estimated_completion_at: z.string().nullable().optional(),
  last_cycle_id: z.string().nullable().optional(),
  status_reason: z.string().nullable().optional(),
});

export const MonitorNodeSchema = z.object({
  id: z.string(),
  label: z.string(),
  status: z.string(),
});

export const MonitorLinkSchema = z.object({
  from: z.string(),
  to: z.string(),
  state: z.string(),
});

export const MonitorPipelineSchema = z.object({
  window_minutes: z.number(),
  nodes: z.array(MonitorNodeSchema),
  links: z.array(MonitorLinkSchema),
});

export const MonitorRequestItemSchema = z.object({
  time: z.string().nullable().optional(),
  source_agent: z.string(),
  request: z.string(),
  status: z.string(),
  inferred: z.boolean().optional(),
  evidence: z.string().nullable().optional(),
});

export const MonitorRequestsSchema = z.object({
  items: z.array(MonitorRequestItemSchema),
  limit: z.number(),
});

export const MonitorScraperItemSchema = z.object({
  name: z.string(),
  status: z.string(),
  progress_pct: z.number(),
  last_update_at: z.string().nullable().optional(),
  inferred: z.boolean().optional(),
});

export const MonitorScrapersSchema = z.object({
  items: z.array(MonitorScraperItemSchema),
});

export const MonitorEventItemSchema = z.object({
  time: z.string().nullable().optional(),
  level: z.string(),
  message: z.string(),
  source: z.string(),
});

export const MonitorEventsSchema = z.object({
  items: z.array(MonitorEventItemSchema),
  limit: z.number(),
});

export const MonitorCycleItemSchema = z.object({
  cycle_id: z.string(),
  run_id: z.string().nullable().optional(),
  start: z.string().nullable().optional(),
  duration_seconds: z.number().nullable().optional(),
  result: z.string(),
  status_reason: z.string().nullable().optional(),
});

export const MonitorCyclesSchema = z.object({
  items: z.array(MonitorCycleItemSchema),
  limit: z.number(),
});

export const MonitorHealthSchema = z.object({
  data_freshness: z.object({
    status: z.string(),
    minutes_since_last_success: z.number().nullable().optional(),
  }),
  agent_connectivity: z.object({
    status: z.string(),
    healthy_agents: z.number(),
    total_agents: z.number(),
  }),
  pipeline_latency: z.object({
    status: z.string(),
    p50_seconds: z.number(),
    p95_seconds: z.number(),
  }),
  scraper_health: z.object({
    status: z.string(),
    active_jobs: z.number(),
    recent_failures: z.number(),
  }),
});

export const StoryMonitorSnapshotSchema = z.object({
  generated_at: z.string(),
  status: MonitorStatusSchema,
  pipeline: MonitorPipelineSchema,
  requests: MonitorRequestsSchema,
  scrapers: MonitorScrapersSchema,
  events: MonitorEventsSchema,
  cycles: MonitorCyclesSchema,
  health: MonitorHealthSchema,
});

export const StoryMonitorWsMessageSchema = z.object({
  type: z.string(),
  transport: z.string().optional(),
  generated_at: z.string().optional(),
  reason: z.string().optional(),
  data: StoryMonitorSnapshotSchema.optional(),
});

export type StoryMonitorSnapshot = z.infer<typeof StoryMonitorSnapshotSchema>;
export type StoryMonitorWsMessage = z.infer<typeof StoryMonitorWsMessageSchema>;
