import { TriangleAlert } from "lucide-react";
import type { StudentSubjectSummary } from "../../types/studentAttendance";
import { STATUS_META, STATUSES } from "../../types/attendance";
import { cn } from "../../utils/cn";
import { formatPercent } from "../../utils/format";

/** The server decides the percentage (finalized sessions, configured policy); null → N/A. */
export function percentText(value: number | null) {
  return value === null ? "N/A" : formatPercent(value);
}

export function LowAttendanceWarning({ threshold }: { threshold: number }) {
  return (
    <p role="alert" className="flex items-start gap-1.5 rounded-lg bg-red-50 px-3 py-2 text-xs font-medium text-red-700 dark:bg-red-950/50 dark:text-red-300">
      <TriangleAlert className="mt-px h-3.5 w-3.5 shrink-0" />
      <span>
        <strong>Low Attendance</strong> — Your attendance in this subject is below {formatPercent(threshold)}.
      </span>
    </p>
  );
}

/** Percentage, progress bar and P/A/L/E counts for one subject. */
export function SubjectStats({ s }: { s: StudentSubjectSummary }) {
  const pct = s.percentage ?? 0;
  return (
    <div className="space-y-3">
      <div className="flex items-end justify-between gap-3">
        <p className={cn("text-3xl font-semibold tabular-nums", s.low_attendance ? "text-red-600 dark:text-red-400" : "text-slate-900 dark:text-white")}>
          {percentText(s.percentage)}
        </p>
        <p className="text-right text-xs text-slate-500 dark:text-slate-400">
          {s.total_classes} finalized class{s.total_classes === 1 ? "" : "es"}
        </p>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800" role="progressbar" aria-label="Attendance" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
        <div className={cn("h-full rounded-full", s.low_attendance ? "bg-red-500" : "bg-emerald-500")} style={{ width: `${Math.min(pct, 100)}%` }} />
      </div>
      <dl className="grid grid-cols-4 gap-2 text-center">
        {STATUSES.map((status) => (
          <div key={status} className="rounded-lg border border-slate-200 px-1 py-1.5 dark:border-slate-800">
            <dd className={cn("text-lg font-semibold tabular-nums", STATUS_META[status].tone)}>{s[status]}</dd>
            <dt className="truncate text-[11px] text-slate-500 dark:text-slate-400">{STATUS_META[status].label}</dt>
          </div>
        ))}
      </dl>
    </div>
  );
}

export function subjectMeta(s: StudentSubjectSummary) {
  const teachers = s.teacher_names.length ? s.teacher_names.join(", ") : "Teacher not assigned";
  return `${teachers} · Section ${s.section_name}`;
}
