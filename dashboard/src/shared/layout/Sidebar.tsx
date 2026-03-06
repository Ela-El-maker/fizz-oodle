"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { X } from "lucide-react";
import { navItems } from "@/shared/config/nav";
import { cn } from "@/shared/lib/utils";

interface SidebarProps {
  mobileOpen?: boolean;
  onClose?: () => void;
}

function SidebarContent({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  return (
    <>
      <div className="border-b border-line px-5 py-5">
        <div className="text-xl font-semibold text-ink">Market Intel</div>
        <div className="mt-1 text-xs tracking-[0.2em] text-ink-faint">OPERATOR CONSOLE</div>
      </div>
      <nav className="space-y-1 px-3 py-3">
        {navItems.map((item) => {
          const active = pathname === item.href;
          const Icon = item.icon;
          return (
            <Link
              key={item.href}
              href={item.href}
              onClick={onNavigate}
              className={cn(
                "flex items-center gap-2 rounded-xl px-3 py-2.5 text-sm",
                active ? "bg-emerald-500/15 text-emerald-300 ring-1 ring-emerald-500/30" : "text-muted hover:bg-hover hover:text-ink",
              )}
            >
              <Icon className="h-4 w-4" />
              {item.label}
            </Link>
          );
        })}
      </nav>
    </>
  );
}

export function Sidebar({ mobileOpen, onClose }: SidebarProps) {
  return (
    <>
      {/* Desktop sidebar */}
      <aside className="hidden w-72 border-r border-line bg-[var(--sidebar-bg)] backdrop-blur lg:fixed lg:inset-y-0 lg:block">
        <SidebarContent />
      </aside>

      {/* Mobile drawer */}
      {mobileOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          {/* Backdrop */}
          <div className="fixed inset-0 bg-black/50 backdrop-blur-sm" onClick={onClose} />
          {/* Drawer panel */}
          <aside className="relative z-50 flex h-full w-72 max-w-[85vw] flex-col border-r border-line bg-[var(--sidebar-bg)]">
            <button
              type="button"
              onClick={onClose}
              className="absolute right-3 top-4 inline-flex h-8 w-8 items-center justify-center rounded-lg text-muted hover:bg-hover hover:text-ink"
              aria-label="Close sidebar"
            >
              <X size={18} />
            </button>
            <SidebarContent onNavigate={onClose} />
          </aside>
        </div>
      )}
    </>
  );
}
