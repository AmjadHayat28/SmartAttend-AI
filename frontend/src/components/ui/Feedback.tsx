import { AlertCircle, Inbox, Loader2, type LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "../../utils/cn";
import { Button } from "./Button";

export function Spinner({ label = "Loading…", className }: { label?: string; className?: string }) {
  return (
    <div className={cn("flex items-center justify-center gap-2 py-10 text-sm text-slate-500", className)} role="status">
      <Loader2 className="h-5 w-5 animate-spin" />
      {label}
    </div>
  );
}

export function Alert({ children, tone = "error" }: { children: ReactNode; tone?: "error" | "warning" | "info" }) {
  const styles = {
    error: "border-red-200 bg-red-50 text-red-800 dark:border-red-900 dark:bg-red-950/50 dark:text-red-200",
    warning: "border-amber-200 bg-amber-50 text-amber-800 dark:border-amber-900 dark:bg-amber-950/50 dark:text-amber-200",
    info: "border-brand-200 bg-brand-50 text-brand-800 dark:border-brand-900 dark:bg-brand-950/50 dark:text-brand-200",
  }[tone];
  return (
    <div role="alert" className={cn("flex items-start gap-2 rounded-lg border px-3 py-2.5 text-sm", styles)}>
      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
      <div>{children}</div>
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="space-y-3 p-5">
      <Alert>{message}</Alert>
      {onRetry && (
        <Button variant="secondary" size="sm" onClick={onRetry}>
          Try again
        </Button>
      )}
    </div>
  );
}

export function EmptyState({ title, description, icon: Icon = Inbox, action }: { title: string; description?: string; icon?: LucideIcon; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center px-6 py-12 text-center">
      <span className="rounded-full bg-slate-100 p-3 text-slate-500 dark:bg-slate-800 dark:text-slate-400">
        <Icon className="h-6 w-6" />
      </span>
      <h3 className="mt-3 text-sm font-semibold text-slate-900 dark:text-slate-100">{title}</h3>
      {description && <p className="mt-1 max-w-sm text-sm text-slate-500 dark:text-slate-400">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

const BADGE_TONES = {
  gray: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
  green: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
  red: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
  amber: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
  blue: "bg-brand-100 text-brand-800 dark:bg-brand-900/40 dark:text-brand-200",
};

export function Badge({ children, tone = "gray" }: { children: ReactNode; tone?: keyof typeof BADGE_TONES }) {
  return <span className={cn("inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium", BADGE_TONES[tone])}>{children}</span>;
}
