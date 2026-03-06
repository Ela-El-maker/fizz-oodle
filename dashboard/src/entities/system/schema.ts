import { z } from "zod";

export const HealthDependencySchema = z.record(z.any());

export const HealthResponseSchema = z.object({
  status: z.string(),
  timestamp: z.string(),
  dependencies: HealthDependencySchema,
});

export const AutonomyStateSchema = z.object({
  state_key: z.string(),
  queue_depth: z.number(),
  safe_mode: z.boolean(),
  active_policies: z.record(z.any()),
  summary: z.record(z.any()),
  last_policy_recompute_at: z.string().nullable().optional(),
  updated_at: z.string().nullable().optional(),
});

export const AutonomyStateResponseSchema = z.object({
  item: AutonomyStateSchema,
});

export const HealingIncidentSchema = z.object({
  incident_id: z.string(),
  component: z.string(),
  failure_type: z.string(),
  action: z.string(),
  result: z.string(),
  duration_ms: z.number(),
  auto_applied: z.boolean(),
  escalated: z.boolean(),
  details: z.record(z.any()),
  error_message: z.string().nullable().optional(),
  created_at: z.string().nullable().optional(),
});

export const HealingIncidentsResponseSchema = z.object({
  items: z.array(HealingIncidentSchema),
  limit: z.number(),
});

export const LearningSummarySchema = z.object({
  summary_id: z.string(),
  scope: z.string(),
  created_at: z.string().nullable().optional(),
  summary: z.record(z.any()),
});

export const LearningSummaryResponseSchema = z.object({
  item: LearningSummarySchema,
});

export const SelfModStateSchema = z.object({
  pending_count: z.number(),
  applied_last_24h_count: z.number(),
  last_action_at: z.string().nullable().optional(),
  runtime_overrides: z.record(z.any()),
});

export const SelfModStateResponseSchema = z.object({
  item: SelfModStateSchema,
});

export const SelfModProposalSchema = z.object({
  proposal_id: z.string(),
  scope: z.string(),
  agent_name: z.string().nullable().optional(),
  proposal_type: z.string(),
  risk_level: z.string(),
  status: z.string(),
  reason: z.string(),
  auto_eligible: z.boolean(),
  created_at: z.string().nullable().optional(),
  applied_at: z.string().nullable().optional(),
});

export const SelfModProposalsResponseSchema = z.object({
  items: z.array(SelfModProposalSchema),
  limit: z.number(),
});

export type HealthResponse = z.infer<typeof HealthResponseSchema>;
export type AutonomyStateResponse = z.infer<typeof AutonomyStateResponseSchema>;
export type HealingIncidentsResponse = z.infer<typeof HealingIncidentsResponseSchema>;
export type LearningSummaryResponse = z.infer<typeof LearningSummaryResponseSchema>;
export type SelfModStateResponse = z.infer<typeof SelfModStateResponseSchema>;
export type SelfModProposalsResponse = z.infer<typeof SelfModProposalsResponseSchema>;
