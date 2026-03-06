import type { ReactNode } from "react";
import { cn } from "@/shared/lib/utils";

export function Panel({ title, children, className }: { title?: string; children: ReactNode; className?: string }) {
  return (
    <section className={cn("rounded-2xl border border-[color:var(--panel-border)] bg-[color:var(--panel)] p-5 shadow-[0_10px_28px_rgba(2,6,23,0.28)]", className)}>
      {title ? <h2 className="mb-4 text-sm font-semibold tracking-wide text-ink">{title}</h2> : null}
      {children}
    </section>
  );
}
