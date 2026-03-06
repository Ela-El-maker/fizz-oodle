import type { ReactNode } from "react";
import { cn } from "@/shared/lib/utils";

type Tone = "neutral" | "success" | "warning" | "danger" | "brand";

const toneMap: Record<Tone, string> = {
  neutral: "from-slate-500/10 to-slate-800/10 border-line",
  success: "from-green-500/15 to-green-900/10 border-green-500/30",
  warning: "from-amber-500/15 to-amber-900/10 border-amber-500/30",
  danger: "from-red-500/15 to-red-900/10 border-red-500/30",
  brand: "from-emerald-500/20 to-cyan-900/10 border-emerald-500/40",
};

export function StatCard({
  label,
  value,
  hint,
  icon,
  tone = "neutral",
}: {
  label: string;
  value: string | number;
  hint?: string;
  icon?: ReactNode;
  tone?: Tone;
}) {
  return (
    <div className={cn("min-w-0 overflow-hidden rounded-xl border bg-gradient-to-br p-4", toneMap[tone])}>
      <div className="mb-2 flex items-center justify-between">
        <div className="truncate text-xs uppercase tracking-[0.16em] text-muted">{label}</div>
        {icon ? <div className="shrink-0 text-muted">{icon}</div> : null}
      </div>
      <div className="truncate text-2xl font-semibold text-ink">{value}</div>
      {hint ? <div className="mt-1 truncate text-xs text-muted" title={hint}>{hint}</div> : null}
    </div>
  );
}
