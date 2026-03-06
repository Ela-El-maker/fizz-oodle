import { z } from "zod";

export const SchedulerStatusSchema = z.object({
  scheduler_status: z.string(),
  last_tick_at: z.string().nullable().optional(),
  last_tick_at_eat: z.string().nullable().optional(),
  loop_interval_seconds: z.number(),
  schedules_loaded: z.number(),
});

export const SchedulerMetricsSchema = z.object({
  active_runs: z.number(),
  queued_jobs: z.number(),
  blocked_jobs: z.number(),
  next_run_eta_seconds: z.number().nullable().optional(),
  next_email_eta_seconds: z.number().nullable().optional(),
  llm_active_jobs: z.number(),
});

export const SchedulerHistoryItemSchema = z.object({
  run_id: z.string(),
  agent_name: z.string(),
  agent_label: z.string(),
  status: z.string(),
  status_reason: z.string().nullable().optional(),
  trigger_type: z.string().nullable().optional(),
  started_at: z.string().nullable().optional(),
  finished_at: z.string().nullable().optional(),
  duration_seconds: z.number().nullable().optional(),
  email_sent: z.boolean().optional(),
  llm_used: z.boolean().optional(),
});

export const SchedulerPastSchema = z.object({
  items: z.array(SchedulerHistoryItemSchema),
  limit: z.number(),
});

export const SchedulerRunningItemSchema = z.object({
  run_id: z.string(),
  agent_name: z.string(),
  agent_label: z.string(),
  started_at: z.string().nullable().optional(),
  status: z.string(),
  status_reason: z.string().nullable().optional(),
  llm_used: z.boolean().optional(),
});

export const SchedulerQueuedItemSchema = z.object({
  command_id: z.string(),
  run_id: z.string(),
  agent_name: z.string(),
  agent_label: z.string(),
  requested_at: z.string().nullable().optional(),
  trigger_type: z.string().nullable().optional(),
  requested_by: z.string().nullable().optional(),
  schedule_key: z.string().nullable().optional(),
});

export const SchedulerBlockedItemSchema = z.object({
  run_id: z.string(),
  agent_name: z.string(),
  agent_label: z.string(),
  waiting_for: z.array(z.string()),
  requested_at: z.string().nullable().optional(),
  trigger_type: z.string().nullable().optional(),
});

export const SchedulerPresentSchema = z.object({
  running: z.array(SchedulerRunningItemSchema),
  queued: z.array(SchedulerQueuedItemSchema),
  blocked: z.array(SchedulerBlockedItemSchema),
});

export const SchedulerFutureItemSchema = z.object({
  schedule_key: z.string().nullable().optional(),
  task_name: z.string().nullable().optional(),
  agent_name: z.string().nullable().optional(),
  trigger_type: z.string().nullable().optional(),
  next_run_at_utc: z.string().nullable().optional(),
  next_run_at_eat: z.string().nullable().optional(),
  timezone: z.string().nullable().optional(),
  notes: z.string().nullable().optional(),
  predicted_duration_p50_seconds: z.number().nullable().optional(),
  predicted_duration_p95_seconds: z.number().nullable().optional(),
  predicted_complete_p50_utc: z.string().nullable().optional(),
  predicted_complete_p95_utc: z.string().nullable().optional(),
  llm_interaction: z.boolean().optional(),
});

export const SchedulerFutureSchema = z.object({
  hours: z.number(),
  items: z.array(SchedulerFutureItemSchema),
});

export const SchedulerPipelineNodeSchema = z.object({
  id: z.string(),
  agent_name: z.string(),
  label: z.string(),
  status: z.string(),
});

export const SchedulerPipelineLinkSchema = z.object({
  from: z.string(),
  to: z.string(),
  state: z.string(),
});

export const SchedulerPipelineSchema = z.object({
  window_minutes: z.number(),
  nodes: z.array(SchedulerPipelineNodeSchema),
  links: z.array(SchedulerPipelineLinkSchema),
});

export const SchedulerHeatmapRowSchema = z.object({
  agent_name: z.string(),
  label: z.string(),
  cells: z.array(z.number()),
});

export const SchedulerHeatmapSchema = z.object({
  hours: z.number(),
  buckets: z.array(z.string()),
  rows: z.array(SchedulerHeatmapRowSchema),
});

export const SchedulerEmailSchema = z.object({
  next_scheduled_at_utc: z.string().nullable().optional(),
  next_scheduled_at_eat: z.string().nullable().optional(),
  latest_validation_window: z.string().nullable().optional(),
  latest_validation_status: z.string().nullable().optional(),
  latest_validation_at: z.string().nullable().optional(),
  sent_count_recent: z.number(),
  failure_count_recent: z.number(),
  next_validation_dispatches: z
    .array(
      z.object({
        schedule_key: z.string().nullable().optional(),
        window: z.string(),
        next_run_at_utc: z.string().nullable().optional(),
        next_run_at_eat: z.string().nullable().optional(),
        agents: z.array(z.string()),
      }),
    )
    .optional()
    .default([]),
  next_email_by_agent: z
    .array(
      z.object({
        agent_name: z.string(),
        agent_label: z.string(),
        window: z.string().nullable().optional(),
        schedule_key: z.string().nullable().optional(),
        next_run_at_utc: z.string().nullable().optional(),
        next_run_at_eat: z.string().nullable().optional(),
      }),
    )
    .optional()
    .default([]),
});

export const SchedulerEventSchema = z.object({
  event_time: z.string().nullable().optional(),
  event_type: z.string(),
  severity: z.string(),
  source: z.string(),
  agent_name: z.string().nullable().optional(),
  run_id: z.string().nullable().optional(),
  schedule_key: z.string().nullable().optional(),
  message: z.string(),
  details: z.record(z.any()).optional(),
});

export const SchedulerEventsSchema = z.object({
  items: z.array(SchedulerEventSchema),
  limit: z.number(),
});

export const SchedulerImpactItemSchema = z.object({
  agent_name: z.string(),
  label: z.string(),
  next_run_at_utc: z.string().nullable().optional(),
  next_run_at_eat: z.string().nullable().optional(),
  estimated_slippage_seconds: z.number().nullable().optional(),
});

export const SchedulerImpactSchema = z.object({
  failed_agent: z.string().nullable().optional(),
  items: z.array(SchedulerImpactItemSchema),
});

export const SchedulerHealthSchema = z.object({
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
  scheduler_dispatch: z.object({
    status: z.string(),
    accepted: z.number(),
    failed: z.number(),
    skipped: z.number(),
  }),
  email_dispatch: z.object({
    status: z.string(),
    sent_count: z.number(),
    recent_failures: z.number(),
  }),
});

export const SchedulerMonitorSnapshotSchema = z.object({
  generated_at: z.string(),
  time: z.object({
    now_utc: z.string(),
    now_eat: z.string().nullable().optional(),
  }),
  status: SchedulerStatusSchema,
  metrics: SchedulerMetricsSchema,
  past: SchedulerPastSchema,
  present: SchedulerPresentSchema,
  future: SchedulerFutureSchema,
  pipeline: SchedulerPipelineSchema,
  heatmap: SchedulerHeatmapSchema,
  email: SchedulerEmailSchema,
  events: SchedulerEventsSchema,
  impact: SchedulerImpactSchema,
  health: SchedulerHealthSchema.optional().default({
    data_freshness: {
      status: "degraded",
      minutes_since_last_success: null,
    },
    agent_connectivity: {
      status: "degraded",
      healthy_agents: 0,
      total_agents: 0,
    },
    pipeline_latency: {
      status: "degraded",
      p50_seconds: 0,
      p95_seconds: 0,
    },
    scheduler_dispatch: {
      status: "degraded",
      accepted: 0,
      failed: 0,
      skipped: 0,
    },
    email_dispatch: {
      status: "degraded",
      sent_count: 0,
      recent_failures: 0,
    },
  }),
  daily_streak: z
    .object({
      date_eat: z.string(),
      items: z.array(
        z.object({
          agent_name: z.string(),
          agent_label: z.string(),
          runs_today: z.number(),
          success_today: z.number(),
          partial_today: z.number(),
          fail_today: z.number(),
          running_now: z.number(),
          email_sent_today: z.number(),
          last_run_at_utc: z.string().nullable().optional(),
          last_run_at_eat: z.string().nullable().optional(),
          actions_today: z.array(
            z.object({
              event_type: z.string(),
              count: z.number(),
            }),
          ),
        }),
      ),
    })
    .optional()
    .default({ date_eat: "", items: [] }),
});

export const SchedulerMonitorWsMessageSchema = z.object({
  type: z.string(),
  transport: z.string().optional(),
  generated_at: z.string().optional(),
  reason: z.string().optional(),
  data: SchedulerMonitorSnapshotSchema.optional(),
});

export type SchedulerMonitorSnapshot = z.infer<typeof SchedulerMonitorSnapshotSchema>;
export type SchedulerMonitorWsMessage = z.infer<typeof SchedulerMonitorWsMessageSchema>;
