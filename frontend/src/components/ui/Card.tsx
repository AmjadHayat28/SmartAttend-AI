import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "../../utils/cn";

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <div className={cn("rounded-xl border border-slate-200 bg-white shadow-sm dark:border-slate-800 dark:bg-slate-900", className)}>
      {children}
    </div>
  );
}

export function CardHeader({ title, description, action }: { title: string; description?: string; action?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-200 px-5 py-4 dark:border-slate-800">
      <div>
        <h2 className="text-base font-semibold text-slate-900 dark:text-slate-100">{title}</h2>
        {description && <p className="mt-0.5 text-sm text-slate-500 dark:text-slate-400">{description}</p>}
      </div>
      {action}
    </div>
  );
}

const TONES = {
  brand: "bg-brand-50 text-brand-700 dark:bg-brand-900/40 dark:text-brand-200",
  green: "bg-emerald-50 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300",
  amber: "bg-amber-50 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300",
  violet: "bg-violet-50 text-violet-700 dark:bg-violet-900/30 dark:text-violet-300",
  rose: "bg-rose-50 text-rose-700 dark:bg-rose-900/30 dark:text-rose-300",
};

interface StatCardProps {
  label: string;
  value: ReactNode;
  icon: LucideIcon;
  tone?: keyof typeof TONES;
  hint?: string;
  loading?: boolean;
}

export function StatCard({ label, value, icon: Icon, tone = "brand", hint, loading }: StatCardProps) {
  return (
    <Card className="p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-sm font-medium text-slate-500 dark:text-slate-400">{label}</p>
          {loading ? (
            <div className="mt-2 h-8 w-16 animate-pulse rounded bg-slate-200 dark:bg-slate-800" />
          ) : (
            <p className="mt-1 text-3xl font-semibold tabular-nums text-slate-900 dark:text-white">{value}</p>
          )}
          {hint && <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{hint}</p>}
        </div>
        <span className={cn("rounded-lg p-2.5", TONES[tone])}>
          <Icon className="h-5 w-5" />
        </span>
      </div>
    </Card>
  );
}
