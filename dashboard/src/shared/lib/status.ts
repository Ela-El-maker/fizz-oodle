const CANONICAL_STATUS = new Set([
  "queued",
  "running",
  "success",
  "partial",
  "fail",
  "stale_timeout",
  "pending_data",
]);

export function normalizeStatus(value: unknown): string {
  if (typeof value === "string") {
    const normalized = value.trim().toLowerCase();
    if (CANONICAL_STATUS.has(normalized)) {
      return normalized;
    }
    // Common control-plane health values.
    if (normalized === "ok" || normalized === "up" || normalized === "online" || normalized === "ready") {
      return "success";
    }
    if (normalized === "degraded" || normalized === "warning" || normalized === "warn") {
      return "partial";
    }
    if (normalized === "down" || normalized === "offline" || normalized === "critical") {
      return "fail";
    }
    if (normalized === "stale_run_timeout") {
      return "stale_timeout";
    }
    // Report/digest/archive artifact statuses
    if (normalized === "sent") {
      return "success";
    }
    if (normalized === "skipped") {
      return "partial";
    }
    // Source breaker states
    if (normalized === "closed") {
      return "success";
    }
    if (normalized === "half_open" || normalized === "half-open") {
      return "partial";
    }
    if (normalized === "open") {
      return "fail";
    }
    // Common health aliases
    if (normalized === "healthy") {
      return "success";
    }
    if (normalized === "unhealthy") {
      return "fail";
    }
  }
  return "pending_data";
}
