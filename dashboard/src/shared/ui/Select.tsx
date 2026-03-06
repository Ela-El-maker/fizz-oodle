import type { SelectHTMLAttributes } from "react";
import { cn } from "@/shared/lib/utils";

export function Select({ className, ...rest }: SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      {...rest}
      className={cn(
        "w-full rounded-lg border border-line bg-inset px-3 py-2 text-sm text-ink focus:border-brand focus:outline-none",
        className,
      )}
    />
  );
}
