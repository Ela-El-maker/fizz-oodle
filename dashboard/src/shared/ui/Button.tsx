"use client";

import type { ButtonHTMLAttributes } from "react";
import { cn } from "@/shared/lib/utils";

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "danger" | "ghost";
  loading?: boolean;
};

export function Button({ variant = "primary", loading, disabled, className, children, ...rest }: Props) {
  const palette: Record<NonNullable<Props["variant"]>, string> = {
    primary: "bg-brand text-slate-950 hover:brightness-110",
    secondary: "bg-elevated text-ink hover:bg-hover border border-line",
    danger: "bg-danger text-white hover:brightness-110",
    ghost: "bg-transparent text-ink-soft hover:bg-hover border border-line",
  };

  return (
    <button
      {...rest}
      disabled={disabled || loading}
      className={cn(
        "inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-60",
        palette[variant],
        className,
      )}
    >
      {loading ? "Loading..." : children}
    </button>
  );
}
