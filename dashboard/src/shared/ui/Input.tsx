import type { InputHTMLAttributes } from "react";
import { cn } from "@/shared/lib/utils";

export function Input({ className, ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...rest}
      className={cn(
        "w-full rounded-lg border border-line bg-inset px-3 py-2 text-sm text-ink placeholder:text-ink-faint focus:border-brand focus:outline-none",
        className,
      )}
    />
  );
}
