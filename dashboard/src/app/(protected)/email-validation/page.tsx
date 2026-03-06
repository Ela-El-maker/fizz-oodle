"use client";

import { useMemo, useState } from "react";
import { useEmailValidation, useRunEmailValidation } from "@/features/email-validation/useEmailValidation";
import { Button } from "@/shared/ui/Button";
import { Panel } from "@/shared/ui/Panel";
import { Badge } from "@/shared/ui/Badge";
import { KeyValueList } from "@/shared/ui/KeyValueList";
import { StatCard } from "@/shared/ui/StatCard";
import { fmtDateTime } from "@/shared/lib/format";
import { normalizeStatus } from "@/shared/lib/status";
import { ApiError } from "@/shared/lib/errors";

type ValidationStep = {
  agent_name: string;
  status: string;
  email_sent: boolean;
  email_error: string;
};

type ValidationItem = {
  validation_run_id?: string;
  window?: string | null;
  status?: string | null;
  period_key?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  summary_json?: Record<string, unknown>;
  steps?: Array<Record<string, unknown>>;
};

function toStep(step: Record<string, unknown>, idx: number): ValidationStep {
  return {
    agent_name: typeof step.agent_name === "string" ? step.agent_name : `step-${idx + 1}`,
    status: normalizeStatus(typeof step.status === "string" ? step.status : "unknown"),
    email_sent: step.email_sent === true,
    email_error: typeof step.email_error === "string" ? step.email_error : "",
  };
}

function fmtDuration(startedAt?: string | null, finishedAt?: string | null): string {
  if (!startedAt || !finishedAt) return "-";
  const start = Date.parse(startedAt);
  const end = Date.parse(finishedAt);
  if (Number.isNaN(start) || Number.isNaN(end) || end < start) return "-";
  const seconds = Math.floor((end - start) / 1000);
  const mins = Math.floor(seconds / 60);
  const rem = seconds % 60;
  if (mins <= 0) return `${rem}s`;
  return `${mins}m ${rem}s`;
}

function statToneFromStatus(status: string): "neutral" | "success" | "warning" | "danger" {
  const normalized = status.toLowerCase();
  if (normalized.includes("success")) return "success";
  if (normalized.includes("partial") || normalized.includes("warn")) return "warning";
  if (normalized.includes("fail") || normalized.includes("error")) return "danger";
  return "neutral";
}

function errorText(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status >= 500) return "Service temporarily unavailable";
    if (error.status === 401 || error.status === 403) return "Authentication required";
    return `Request failed (${error.status})`;
  }
  if (error instanceof Error) return error.message;
  return "Unknown error";
}

function ValidationCard({
  title,
  window,
  loading,
  error,
  item,
  onRun,
  running,
}: {
  title: string;
  window: "daily" | "weekly";
  loading: boolean;
  error: unknown;
  item: ValidationItem | null | undefined;
  onRun: () => void;
  running: boolean;
}) {
  const steps = useMemo(() => (item?.steps || []).map(toStep), [item?.steps]);
  const status = normalizeStatus(item?.status);
  const sentCount = steps.filter((step) => step.email_sent).length;
  const failedCount = steps.filter((step) => step.status.includes("fail") || step.status.includes("error")).length;
  const stepCount = steps.length;
  const hasError = !!error;

  return (
    <Panel title={title}>
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          {!item ? (
            <Badge value="idle" />
          ) : (
            <Badge value={status} />
          )}
          <span className="text-xs uppercase tracking-[0.12em] text-ink-faint">
            {item?.period_key || `${window} window`}
          </span>
        </div>
        <Button loading={running} onClick={onRun}>
          Run {title}
        </Button>
      </div>

      {loading ? (
        <div className="space-y-3">
          <div className="h-20 animate-pulse rounded-xl border border-line bg-panel-soft" />
          <div className="h-20 animate-pulse rounded-xl border border-line bg-panel-soft" />
        </div>
      ) : hasError ? (
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-200">
          <div className="font-medium">Unable to load {window} validation.</div>
          <div className="mt-1 text-red-300/90">{errorText(error)}</div>
        </div>
      ) : !item ? (
        <div className="rounded-xl border border-line bg-panel-soft p-4 text-sm text-ink-soft">
          No {window} validation run has been recorded yet. Trigger a run to populate this panel.
        </div>
      ) : (
        <div className="grid gap-4">
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <StatCard label="Run Status" value={status} tone={statToneFromStatus(status)} />
            <StatCard label="Steps" value={stepCount} hint="Agents executed" />
            <StatCard label="Emails Sent" value={sentCount} tone={sentCount > 0 ? "success" : "neutral"} />
            <StatCard label="Failed Steps" value={failedCount} tone={failedCount > 0 ? "danger" : "success"} />
          </div>

          <KeyValueList
            rows={[
              { label: "Run ID", value: item.validation_run_id || "-" },
              { label: "Started", value: fmtDateTime(item.started_at) },
              { label: "Finished", value: fmtDateTime(item.finished_at) },
              { label: "Duration", value: fmtDuration(item.started_at, item.finished_at) },
            ]}
          />

          <div className="rounded-xl border border-line bg-panel-soft p-3">
            <div className="mb-2 text-xs uppercase tracking-[0.12em] text-ink-faint">Agent Steps</div>
            <div className="max-h-72 space-y-2 overflow-y-auto pr-1">
              {steps.length === 0 ? (
                <div className="rounded-lg border border-line bg-panel px-3 py-2 text-sm text-muted">
                  No step records available.
                </div>
              ) : null}
              {steps.map((step, idx) => (
                <div key={`${step.agent_name}-${idx}`} className="rounded-lg border border-line bg-panel px-3 py-2">
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <div className="text-sm font-medium text-ink">{step.agent_name}</div>
                    <Badge value={step.status} />
                  </div>
                  <div className="mt-2 flex flex-wrap items-center gap-2 text-xs text-ink-soft">
                    <span
                      className={
                        step.email_sent
                          ? "rounded-full border border-green-500/30 bg-green-500/10 px-2 py-0.5 text-green-300"
                          : "rounded-full border border-line bg-elevated px-2 py-0.5 text-muted"
                      }
                    >
                      {step.email_sent ? "email sent" : "email not sent"}
                    </span>
                    {step.email_error ? <span className="text-red-300">{step.email_error}</span> : null}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </Panel>
  );
}

export default function EmailValidationPage() {
  const daily = useEmailValidation("daily");
  const weekly = useEmailValidation("weekly");
  const run = useRunEmailValidation();
  const [runningWindow, setRunningWindow] = useState<"daily" | "weekly" | null>(null);

  const overview = useMemo(() => {
    const items = [daily.data?.item, weekly.data?.item].filter(Boolean) as ValidationItem[];
    const totalRuns = items.length;
    const totalSteps = items.reduce((sum, item) => sum + (item.steps?.length || 0), 0);
    const totalSent = items.reduce(
      (sum, item) =>
        sum +
        (item.steps || []).reduce((inner, step) => inner + (step.email_sent === true ? 1 : 0), 0),
      0,
    );
    const failingWindows = [daily.data?.item, weekly.data?.item].filter(
      (item) => item && normalizeStatus(item.status).includes("fail"),
    ).length;
    return { totalRuns, totalSteps, totalSent, failingWindows };
  }, [daily.data?.item, weekly.data?.item]);

  const runWindow = (window: "daily" | "weekly") => {
    setRunningWindow(window);
    run.mutate(window, {
      onSettled: () => setRunningWindow(null),
    });
  };

  return (
    <div className="grid gap-4">
      <Panel title="Email Validation Ops">
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <StatCard label="Tracked Windows" value={overview.totalRuns} hint="Daily + Weekly panels" />
          <StatCard label="Steps Recorded" value={overview.totalSteps} hint="Latest run per window" />
          <StatCard label="Emails Sent" value={overview.totalSent} tone={overview.totalSent > 0 ? "success" : "neutral"} />
          <StatCard
            label="Failing Windows"
            value={overview.failingWindows}
            tone={overview.failingWindows > 0 ? "danger" : "success"}
            hint="Latest status snapshot"
          />
        </div>
      </Panel>

      <div className="grid gap-4 lg:grid-cols-2">
        <ValidationCard
          title="Daily Validation"
          window="daily"
          loading={daily.isLoading}
          error={daily.error}
          item={daily.data?.item}
          running={run.isPending && runningWindow === "daily"}
          onRun={() => runWindow("daily")}
        />
        <ValidationCard
          title="Weekly Validation"
          window="weekly"
          loading={weekly.isLoading}
          error={weekly.error}
          item={weekly.data?.item}
          running={run.isPending && runningWindow === "weekly"}
          onRun={() => runWindow("weekly")}
        />
      </div>
    </div>
  );
}
