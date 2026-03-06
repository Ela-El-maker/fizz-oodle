import { cn } from "@/shared/lib/utils";

function toLabel(value: string) {
  return value
    .replace(/_/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

export function Badge({ value }: { value: string }) {
  const v = value.toLowerCase();
  const tone = v.includes("success") || v.includes("ok")
    ? "border-green-500/30 bg-green-500/10 text-green-300"
    : v.includes("partial") || v.includes("warn") || v.includes("degraded")
      ? "border-amber-500/30 bg-amber-500/10 text-amber-300"
      : v.includes("fail") || v.includes("error")
        ? "border-red-500/30 bg-red-500/10 text-red-300"
        : "border-line bg-elevated text-ink-soft";
  return <span className={cn("inline-flex rounded-full border px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wide", tone)}>{toLabel(value)}</span>;
}
