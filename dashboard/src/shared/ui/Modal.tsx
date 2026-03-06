"use client";

import type { ReactNode } from "react";
import { cn } from "@/shared/lib/utils";

export function Modal({
  open,
  title,
  onClose,
  children,
  footer,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  children: ReactNode;
  footer?: ReactNode;
}) {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4">
      <div className="w-full max-w-lg rounded-xl border border-line bg-panel shadow-2xl">
        <div className="flex items-center justify-between border-b border-line px-4 py-3">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-ink">{title}</h3>
          <button
            type="button"
            onClick={onClose}
            className={cn("rounded-md border border-line px-2 py-1 text-xs text-ink-soft hover:bg-hover")}
          >
            Close
          </button>
        </div>
        <div className="px-4 py-4">{children}</div>
        {footer ? <div className="border-t border-line px-4 py-3">{footer}</div> : null}
      </div>
    </div>
  );
}
