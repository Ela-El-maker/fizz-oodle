"use client";

import { cn } from "@/shared/lib/utils";

export type TabItem = {
  key: string;
  label: string;
};

export function Tabs({
  items,
  activeKey,
  onChange,
}: {
  items: TabItem[];
  activeKey: string;
  onChange: (key: string) => void;
}) {
  return (
    <div className="inline-flex overflow-x-auto rounded-lg border border-line bg-inset p-1">
      {items.map((item) => {
        const active = item.key === activeKey;
        return (
          <button
            key={item.key}
            type="button"
            onClick={() => onChange(item.key)}
            className={cn(
              "rounded-md px-3 py-1.5 text-sm transition",
              active ? "bg-brand text-slate-950 font-semibold" : "text-ink-soft hover:bg-hover",
            )}
          >
            {item.label}
          </button>
        );
      })}
    </div>
  );
}
