import { GraduationCap } from "lucide-react";
import { cn } from "../../utils/cn";

export function Logo({ inverted, className }: { inverted?: boolean; className?: string }) {
  return (
    <div className={cn("flex items-center gap-2.5", className)}>
      <span className={cn("grid h-9 w-9 place-items-center rounded-lg", inverted ? "bg-white/15 text-white" : "bg-brand-800 text-white")}>
        <GraduationCap className="h-5 w-5" />
      </span>
      <div className="leading-tight">
        <p className={cn("text-sm font-semibold", inverted ? "text-white" : "text-slate-900 dark:text-white")}>SmartClass</p>
        <p className={cn("text-xs", inverted ? "text-brand-100" : "text-slate-500 dark:text-slate-400")}>AI Attendance</p>
      </div>
    </div>
  );
}
