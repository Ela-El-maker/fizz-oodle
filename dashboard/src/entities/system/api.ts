import { http } from "@/shared/lib/http";
import {
  AutonomyStateResponseSchema,
  HealthResponseSchema,
  HealingIncidentsResponseSchema,
  LearningSummaryResponseSchema,
  SelfModProposalsResponseSchema,
  SelfModStateResponseSchema,
} from "@/entities/system/schema";

export async function fetchHealth() {
  return HealthResponseSchema.parse(await http.get("/health"));
}

export async function fetchAutonomyState(refresh = false) {
  return AutonomyStateResponseSchema.parse(await http.get("/system/autonomy/state", { refresh }));
}

export async function fetchHealingIncidents(limit = 20) {
  return HealingIncidentsResponseSchema.parse(await http.get("/system/healing/incidents", { limit }));
}

export async function fetchLearningSummary(refresh = false) {
  return LearningSummaryResponseSchema.parse(await http.get("/system/learning/summary", { refresh }));
}

export async function fetchSelfModState() {
  return SelfModStateResponseSchema.parse(await http.get("/system/self-mod/state"));
}

export async function fetchSelfModProposals(limit = 10) {
  return SelfModProposalsResponseSchema.parse(await http.get("/system/self-mod/proposals", { limit }));
}

export async function generateSelfModProposals(autoApply = true) {
  return http.post("/system/self-mod/generate", undefined, { refresh: true, auto_apply: autoApply });
}
