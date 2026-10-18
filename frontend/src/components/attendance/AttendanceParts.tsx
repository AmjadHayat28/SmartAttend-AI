import { CalendarDays, Hash, Users } from "lucide-react";
import { formatSessionDate } from "../../services/attendanceService";
import { STATUS_META, STATUSES, type AttendanceSession, type AttendanceStatus, type AttendanceSummary, type SessionStatus } from "../../types/attendance";
import { cn } from "../../utils/cn";
import { Badge } from "../ui/Feedback";

export function SessionStatusBadge({ status }: { status: SessionStatus }) {
  const meta = { draft: ["Draft", "amber"], finalized: ["Finalized", "green"], cancelled: ["Cancelled", "gray"] } as const;
  return <Badge tone={meta[status][1]}>{meta[status][0]}</Badge>;
}

/** Segmented P / A / L / E control. Large touch targets; labels for screen readers. */
export function StatusToggle({ value, onChange, name, disabled }: { value: AttendanceStatus | null; onChange: (s: AttendanceStatus) => void; name: string; disabled?: boolean }) {
  return (
    <div role="radiogroup" aria-label={`Attendance for ${name}`} className="grid grid-cols-4 gap-1">
      {STATUSES.map((status) => {
        const meta = STATUS_META[status];
        const selected = value === status;
        return (
          <button
            key={status}
            type="button"
            role="radio"
            aria-checked={selected}
            aria-label={meta.label}
            title={meta.label}
            disabled={disabled}
            onClick={() => onChange(status)}
            className={cn(
              "h-9 min-w-10 rounded-md border text-sm font-semibold transition-colors focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-brand-600 disabled:opacity-50",
              selected ? meta.active : "border-slate-300 bg-white text-slate-600 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-300 dark:hover:bg-slate-800",
            )}
          >
            <span aria-hidden>{meta.short}</span>
          </button>
        );
      })}
    </div>
  );
}

export function StatusPill({ status }: { status: AttendanceStatus | null }) {
  if (!status) return <Badge>Not marked</Badge>;
  const tone = { present: "green", absent: "red", late: "amber", excused: "blue" } as const;
  return <Badge tone={tone[status]}>{STATUS_META[status].label}</Badge>;
}

export function SummaryGrid({ summary, photos }: { summary: AttendanceSummary; photos?: number }) {
  const items: [string, number | string, string][] = [
    ["Total", summary.total, "text-slate-900 dark:text-white"],
    ["Present", summary.present, STATUS_META.present.tone],
    ["Absent", summary.absent, STATUS_META.absent.tone],
    ["Late", summary.late, STATUS_META.late.tone],
    ["Excused", summary.excused, STATUS_META.excused.tone],
  ];
  if (summary.unmarked) items.push(["Not marked", summary.unmarked, "text-slate-500"]);
  if (photos !== undefined) items.push(["Photos", photos, "text-slate-900 dark:text-white"]);
  return (
    <dl className="grid grid-cols-3 gap-2 sm:grid-cols-4">
      {items.map(([label, value, tone]) => (
        <div key={label} className="rounded-lg border border-slate-200 px-3 py-2 dark:border-slate-800">
          <dt className="text-xs text-slate-500">{label}</dt>
          <dd className={cn("text-xl font-semibold tabular-nums", tone)}>{value}</dd>
        </div>
      ))}
    </dl>
  );
}

export function SessionHeading({ session }: { session: AttendanceSession }) {
  return (
    <div className="min-w-0">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="text-xl font-semibold tracking-tight text-slate-900 sm:text-2xl dark:text-white">{session.course_title}</h1>
        <SessionStatusBadge status={session.status} />
        {session.is_lab && <Badge tone="blue">Lab</Badge>}
      </div>
      <p className="mt-1 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-slate-500 dark:text-slate-400">
        <span className="font-mono text-xs">{session.course_code}</span>
        <span className="flex items-center gap-1">
          <Users className="h-3.5 w-3.5" /> {session.batch_name} · {session.semester_name} · Section {session.section_name}
        </span>
        <span className="flex items-center gap-1">
          <CalendarDays className="h-3.5 w-3.5" /> {formatSessionDate(session.session_date)}
        </span>
        <span className="flex items-center gap-1">
          <Hash className="h-3.5 w-3.5" /> Session {session.session_number}
        </span>
      </p>
    </div>
  );
}

/** Counts by status computed on the client (identical rules to the server's SummaryOut). */
export function localSummary(statuses: (AttendanceStatus | null)[], percentage: number | null = null): AttendanceSummary {
  const s = { total: statuses.length, present: 0, absent: 0, late: 0, excused: 0, unmarked: 0, percentage };
  for (const st of statuses) s[st ?? "unmarked"] += 1;
  return s;
}
