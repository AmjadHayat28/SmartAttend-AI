import { X } from "lucide-react";
import { NavLink } from "react-router-dom";
import { NAVIGATION } from "../../config/navigation";
import type { UserRole } from "../../types/auth";
import { cn } from "../../utils/cn";
import { Logo } from "./Logo";

interface SidebarProps {
  role: UserRole;
  open: boolean;
  onClose: () => void;
}

export function Sidebar({ role, open, onClose }: SidebarProps) {
  const items = NAVIGATION[role];
  // Preserve declaration order of groups; ungrouped items come first.
  const groups: [string, typeof items][] = [];
  for (const item of items) {
    const key = item.group ?? "";
    const bucket = groups.find(([g]) => g === key);
    if (bucket) bucket[1].push(item);
    else groups.push([key, [item]]);
  }
  return (
    <>
      {/* Mobile backdrop */}
      <div
        className={cn("fixed inset-0 z-30 bg-slate-900/50 transition-opacity lg:hidden", open ? "opacity-100" : "pointer-events-none opacity-0")}
        onClick={onClose}
        aria-hidden
      />
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-40 flex w-64 flex-col bg-brand-900 text-brand-100 transition-transform lg:translate-x-0 dark:bg-slate-900 dark:border-r dark:border-slate-800",
          open ? "translate-x-0" : "-translate-x-full",
        )}
      >
        <div className="flex h-16 items-center justify-between px-5">
          <Logo inverted />
          <button className="rounded p-1 text-brand-100 hover:bg-white/10 lg:hidden" onClick={onClose} aria-label="Close menu">
            <X className="h-5 w-5" />
          </button>
        </div>
        <nav className="flex-1 space-y-0.5 overflow-y-auto px-3 py-4 [scrollbar-color:rgb(255_255_255/0.2)_transparent] [scrollbar-width:thin]" aria-label="Main">
          {groups.map(([group, groupItems]) => (
            <div key={group || "main"} className={cn(group && "pt-4")}>
              {group && <p className="px-3 pb-1 text-[11px] font-semibold uppercase tracking-wider text-brand-200/60">{group}</p>}
              {groupItems.map(({ label, to, icon: Icon }) => (
                <NavLink
                  key={to}
                  to={to}
                  end
                  onClick={onClose}
                  className={({ isActive }) =>
                    cn(
                      "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
                      isActive ? "bg-white/15 text-white" : "text-brand-100/80 hover:bg-white/10 hover:text-white",
                    )
                  }
                >
                  <Icon className="h-4 w-4 shrink-0" />
                  <span className="flex-1 truncate">{label}</span>
                </NavLink>
              ))}
            </div>
          ))}
        </nav>
        <p className="px-5 py-4 text-xs text-brand-200/70">© {new Date().getFullYear()} SmartClass University</p>
      </aside>
    </>
  );
}
