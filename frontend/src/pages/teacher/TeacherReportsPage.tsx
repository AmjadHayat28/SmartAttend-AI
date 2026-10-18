import { BarChart3, CalendarDays, CalendarRange, CalendarX2, FileSpreadsheet, SearchX, UserRound } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { PageHeader } from "../../components/layout/PageHeader";
import { Button } from "../../components/ui/Button";
import { Card, CardHeader } from "../../components/ui/Card";
import { Alert, Badge, EmptyState, ErrorState, Spinner } from "../../components/ui/Feedback";
import { Input, Select } from "../../components/ui/FormField";
import { SearchBox } from "../../components/ui/ListToolbar";
import { useToast } from "../../context/ToastContext";
import { useAsync } from "../../hooks/useAsync";
import { getErrorMessage } from "../../services/api";
import { formatSessionDate } from "../../services/attendanceService";
import { reportApi } from "../../services/reportService";
import type { Assignment } from "../../types/api";
import { STATUS_META, type AttendanceStatus } from "../../types/attendance";
import type { ClassReport, DailyReport, ReportType, StudentReport, StudentReportRow } from "../../types/reports";
import { cn } from "../../utils/cn";
import { formatPercent } from "../../utils/format";

const TYPES: { value: ReportType; label: string; icon: typeof BarChart3 }[] = [
  { value: "summary", label: "Class summary", icon: BarChart3 },
  { value: "daily", label: "Daily", icon: CalendarDays },
  { value: "monthly", label: "Monthly", icon: CalendarRange },
  { value: "student", label: "Student", icon: UserRound },
];

const STATUS_PILL: Record<AttendanceStatus, string> = {
  present: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
  absent: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
  late: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
  excused: "bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-300",
};

function localIso(d = new Date()) {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** API percentage → text. The server decides the value (finalized sessions, configured policy). */
const pctText = (v: number | null) => (v === null ? "N/A" : formatPercent(v));
const classLabel = (a: Assignment) => `${a.course_code} — ${a.course_title} · ${a.batch_name} · Sem ${a.semester_number} · Section ${a.section_name}`;

function useDebounced(value: string, ms = 300) {
  const [v, setV] = useState(value);
  useEffect(() => {
    const t = window.setTimeout(() => setV(value.trim()), ms);
    return () => window.clearTimeout(t);
  }, [value, ms]);
  return v;
}

type Loaded =
  | { kind: "class"; data: ClassReport }
  | { kind: "daily"; data: DailyReport }
  | { kind: "student"; data: StudentReport }
  | null;

/**
 * Teacher Attendance Reports — own active classes only (the API refuses HOD/admin/students).
 * Only FINALIZED sessions count; every percentage and low flag comes from the API.
 */
export function TeacherReportsPage() {
  const toast = useToast();
  const classes = useAsync(() => reportApi.classes());
  const [assignmentId, setAssignmentId] = useState("");
  const [type, setType] = useState<ReportType>("summary");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [day, setDay] = useState(localIso());
  const [month, setMonth] = useState(localIso().slice(0, 7));
  const [studentId, setStudentId] = useState("");
  const [search, setSearch] = useState("");
  const q = useDebounced(search);
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    if (!assignmentId && classes.data?.length) setAssignmentId(String(classes.data[0]!.id));
  }, [assignmentId, classes.data]);

  const id = Number(assignmentId);
  const [year, mon] = month.split("-").map(Number);
  const range = { date_from: dateFrom, date_to: dateTo };

  // Everyone in the class (all-time) for the student picker.
  const roster = useAsync(() => (id && type === "student" ? reportApi.summary(id, {}) : Promise.resolve(null)), [id, type]);

  const report = useAsync<Loaded>(async () => {
    if (!id) return null;
    if (type === "summary") return { kind: "class", data: await reportApi.summary(id, { ...range, q }) };
    if (type === "monthly") return year && mon ? { kind: "class", data: await reportApi.monthly(id, { year, month: mon, q }) } : null;
    if (type === "daily") return day ? { kind: "daily", data: await reportApi.daily(id, { date: day, q }) } : null;
    return studentId ? { kind: "student", data: await reportApi.student(id, Number(studentId), range) } : null;
  }, [id, type, dateFrom, dateTo, day, month, studentId, q]);

  function openStudent(row: StudentReportRow) {
    setStudentId(String(row.student_id));
    setType("student");
  }

  const exportParams =
    type === "summary" ? { ...range, q } : type === "daily" ? { date: day, q } : type === "monthly" ? { year, month: mon, q } : { student_id: studentId, ...range };
  const canExport = !!id && (type !== "student" || !!studentId) && (type !== "daily" || !!day) && (type !== "monthly" || !!month);

  async function exportExcel() {
    setExporting(true);
    try {
      const name = await reportApi.exportExcel(id, type, exportParams);
      toast.success(`Downloaded ${name}`);
    } catch (err) {
      toast.error(err instanceof Error && !("isAxiosError" in err) ? err.message : getErrorMessage(err));
    } finally {
      setExporting(false);
    }
  }

  const header = <PageHeader title="Attendance Reports" description="Your own classes only. Only finalized attendance is counted." />;
  if (classes.loading) return <>{header}<Spinner /></>;
  if (classes.error) return <>{header}<Card><ErrorState message={classes.error} onRetry={classes.reload} /></Card></>;
  if (!classes.data?.length) {
    return (
      <>
        {header}
        <Card>
          <EmptyState icon={BarChart3} title="No assigned classes" description="Your HOD assigns courses and sections to you. Reports for them will appear here." />
        </Card>
      </>
    );
  }

  return (
    <>
      {header}
      <Card className="mb-4">
        <div className="space-y-4 p-4 sm:p-5">
          <Select label="Class" name="report-class" value={assignmentId} onChange={(e) => { setAssignmentId(e.target.value); setStudentId(""); }} options={classes.data.map((a) => ({ value: a.id, label: classLabel(a) }))} />
          <div role="tablist" aria-label="Report type" className="grid grid-cols-2 gap-1 rounded-lg border border-slate-200 bg-slate-50 p-1 sm:inline-grid sm:grid-cols-4 dark:border-slate-800 dark:bg-slate-950">
            {TYPES.map(({ value, label, icon: Icon }) => (
              <button
                key={value}
                role="tab"
                aria-selected={type === value}
                onClick={() => setType(value)}
                className={cn(
                  "inline-flex items-center justify-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium",
                  type === value ? "bg-brand-700 text-white" : "text-slate-600 hover:bg-white dark:text-slate-300 dark:hover:bg-slate-800",
                )}
              >
                <Icon className="h-4 w-4" /> {label}
              </button>
            ))}
          </div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 lg:items-end">
            {(type === "summary" || type === "student") && (
              <>
                <Input label="From" name="report-from" type="date" value={dateFrom} max={dateTo || undefined} onChange={(e) => setDateFrom(e.target.value)} />
                <Input label="To" name="report-to" type="date" value={dateTo} min={dateFrom || undefined} onChange={(e) => setDateTo(e.target.value)} />
              </>
            )}
            {type === "daily" && <Input label="Date" name="report-date" type="date" value={day} onChange={(e) => setDay(e.target.value)} />}
            {type === "monthly" && <Input label="Month" name="report-month" type="month" value={month} onChange={(e) => setMonth(e.target.value)} />}
            {type === "student" ? (
              <Select
                label="Student"
                name="report-student"
                value={studentId}
                onChange={(e) => setStudentId(e.target.value)}
                placeholder={roster.loading ? "Loading students…" : "Select a student"}
                disabled={roster.loading}
                options={(roster.data?.students ?? []).map((s) => ({ value: s.student_id, label: `${s.registration_no} — ${s.student_name}${s.currently_enrolled ? "" : " (unenrolled)"}` }))}
              />
            ) : (
              <div className="min-w-0">
                <span className="mb-1.5 block text-sm font-medium text-slate-700 dark:text-slate-200">Student</span>
                <SearchBox value={search} onChange={setSearch} placeholder="Name or reg. no.…" className="w-full" />
              </div>
            )}
            <div className="flex items-end">
              <Button className="w-full sm:w-auto" variant="secondary" disabled={!canExport} loading={exporting} onClick={exportExcel}>
                <FileSpreadsheet className="h-4 w-4" /> Export Excel
              </Button>
            </div>
          </div>
        </div>
      </Card>

      {report.loading ? (
        <Spinner />
      ) : report.error ? (
        <Card>
          <ErrorState message={report.error} onRetry={report.reload} />
        </Card>
      ) : !report.data ? (
        <Card>
          <EmptyState icon={UserRound} title="Choose a student" description="Pick a student of this class to see their attendance history." />
        </Card>
      ) : report.data.kind === "class" ? (
        <ClassReportView report={report.data.data} monthly={type === "monthly"} searching={!!q} onOpen={openStudent} />
      ) : report.data.kind === "daily" ? (
        <DailyReportView report={report.data.data} searching={!!q} />
      ) : (
        <StudentReportView report={report.data.data} />
      )}
    </>
  );
}

// ── Pieces ────────────────────────────────────────────────────────────────

function Stat({ label, value, tone }: { label: string; value: ReactNode; tone?: string }) {
  return (
    <Card className="min-w-0 p-4">
      <p className="truncate text-xs font-medium text-slate-500 dark:text-slate-400">{label}</p>
      <p className={cn("mt-1 text-2xl font-semibold tabular-nums text-slate-900 dark:text-white", tone)}>{value}</p>
    </Card>
  );
}

function LowBadge() {
  return <Badge tone="red">Low Attendance</Badge>;
}

function Pct({ row, className }: { row: StudentReportRow; className?: string }) {
  return <span className={cn("font-semibold tabular-nums", row.low_attendance && "text-red-600 dark:text-red-400", className)}>{pctText(row.percentage)}</span>;
}

function Counts({ row }: { row: Pick<StudentReportRow, "present" | "absent" | "late" | "excused"> }) {
  return (
    <span className="whitespace-nowrap text-xs tabular-nums">
      {(["present", "absent", "late", "excused"] as const).map((s, i) => (
        <span key={s}>
          {i > 0 && " · "}
          <span className={STATUS_META[s].tone}>
            {STATUS_META[s].short} {row[s]}
          </span>
        </span>
      ))}
    </span>
  );
}

function ClassReportView({ report, monthly, searching, onOpen }: { report: ClassReport; monthly: boolean; searching: boolean; onOpen: (r: StudentReportRow) => void }) {
  const c = report.report_class;
  const period = report.date_from || report.date_to ? `${report.date_from ?? "…"} to ${report.date_to ?? "…"}` : "All finalized classes";
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Finalized sessions" value={report.finalized_sessions} />
        <Stat label="Enrolled students" value={report.enrolled_students} />
        <Stat label="Class attendance" value={pctText(report.class_percentage)} />
        <Stat label={`Below ${formatPercent(report.threshold)}`} value={report.low_attendance_students} tone={report.low_attendance_students ? "text-red-600 dark:text-red-400" : undefined} />
      </div>
      <Card className="min-w-0">
        <CardHeader title={`${c.course_code} · Section ${c.section_name}`} description={`${c.course_title} · ${c.teacher_name} · ${monthly ? "Month" : "Period"}: ${period}`} />
        {report.finalized_sessions === 0 && !report.students.length ? (
          <EmptyState icon={CalendarX2} title={monthly ? "No finalized attendance this month" : "No finalized attendance yet"} description="Reports include sessions once they are finalized." />
        ) : !report.students.length ? (
          <EmptyState icon={SearchX} title={searching ? "No matching student" : "No students"} description={searching ? "Try another name or registration number." : undefined} />
        ) : (
          <>
            {report.finalized_sessions === 0 && <p className="px-5 pt-4 text-sm text-slate-500">{monthly ? "No finalized attendance in this month." : "No finalized attendance in this period."}</p>}
            {/* Mobile: cards */}
            <ul className="divide-y divide-slate-200 md:hidden dark:divide-slate-800">
              {report.students.map((s) => (
                <li key={s.student_id}>
                  <button type="button" onClick={() => onOpen(s)} className="w-full px-4 py-3 text-left hover:bg-slate-50 dark:hover:bg-slate-800/50">
                    <div className="flex items-start justify-between gap-3">
                      <div className="min-w-0">
                        <p className="truncate font-medium text-slate-900 dark:text-white">{s.student_name}</p>
                        <p className="font-mono text-xs text-slate-500">{s.registration_no}{!s.currently_enrolled && " · unenrolled"}</p>
                      </div>
                      <Pct row={s} />
                    </div>
                    <div className="mt-1.5 flex flex-wrap items-center justify-between gap-2">
                      <Counts row={s} />
                      <span className="text-xs text-slate-500">{s.total_classes} classes</span>
                    </div>
                    {s.low_attendance && <div className="mt-1.5"><LowBadge /></div>}
                  </button>
                </li>
              ))}
            </ul>
            {/* Desktop: table (scrolls inside the card if ever too wide) */}
            <div className="relative hidden overflow-x-auto md:block">
              <table className="min-w-full text-sm">
                <thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500 dark:bg-slate-950">
                  <tr>
                    <th className="px-4 py-2.5">Reg. no.</th>
                    <th className="px-4 py-2.5">Student</th>
                    <th className="px-4 py-2.5 text-right">Classes</th>
                    <th className="px-4 py-2.5 text-right">Present</th>
                    <th className="px-4 py-2.5 text-right">Absent</th>
                    <th className="px-4 py-2.5 text-right">Late</th>
                    <th className="px-4 py-2.5 text-right">Excused</th>
                    <th className="px-4 py-2.5 text-right">Attendance</th>
                    <th className="px-4 py-2.5" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-200 dark:divide-slate-800">
                  {report.students.map((s) => (
                    <tr key={s.student_id} className={cn("cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/50", s.low_attendance && "bg-red-50/50 dark:bg-red-950/20")} onClick={() => onOpen(s)}>
                      <td className="whitespace-nowrap px-4 py-2.5 font-mono text-xs">{s.registration_no}</td>
                      <td className="px-4 py-2.5">
                        <span className="font-medium text-slate-900 dark:text-white">{s.student_name}</span>
                        {!s.currently_enrolled && <span className="ml-2 text-xs text-slate-500">unenrolled</span>}
                      </td>
                      <td className="px-4 py-2.5 text-right tabular-nums">{s.total_classes}</td>
                      <td className={cn("px-4 py-2.5 text-right tabular-nums", STATUS_META.present.tone)}>{s.present}</td>
                      <td className={cn("px-4 py-2.5 text-right tabular-nums", STATUS_META.absent.tone)}>{s.absent}</td>
                      <td className={cn("px-4 py-2.5 text-right tabular-nums", STATUS_META.late.tone)}>{s.late}</td>
                      <td className={cn("px-4 py-2.5 text-right tabular-nums", STATUS_META.excused.tone)}>{s.excused}</td>
                      <td className="px-4 py-2.5 text-right"><Pct row={s} /></td>
                      <td className="whitespace-nowrap px-4 py-2.5 text-right">{s.low_attendance && <LowBadge />}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </Card>
    </div>
  );
}

function DailyReportView({ report, searching }: { report: DailyReport; searching: boolean }) {
  if (!report.sessions.length) {
    return (
      <Card>
        <EmptyState icon={CalendarX2} title="No finalized attendance on this day" description={`${formatSessionDate(report.report_date)} has no finalized session for this class.`} />
      </Card>
    );
  }
  return (
    <div className="space-y-4">
      {report.sessions.map((s) => (
        <Card key={s.session_number} className="min-w-0">
          <CardHeader
            title={`${formatSessionDate(report.report_date)} · Session ${s.session_number}`}
            description={`${report.report_class.course_code} · Section ${report.report_class.section_name} · Attendance ${pctText(s.percentage)}`}
            action={<Counts row={s} />}
          />
          {!s.records.length ? (
            <p className="px-5 py-6 text-center text-sm text-slate-500">{searching ? "No matching student in this session." : "No students."}</p>
          ) : (
            <ul className="divide-y divide-slate-200 dark:divide-slate-800">
              {s.records.map((r) => (
                <li key={r.student_id} className="flex items-center justify-between gap-3 px-5 py-2.5 text-sm">
                  <div className="min-w-0">
                    <p className="truncate font-medium text-slate-900 dark:text-white">{r.student_name}</p>
                    <p className="font-mono text-xs text-slate-500">{r.registration_no}</p>
                  </div>
                  <span className={cn("shrink-0 rounded-full px-2.5 py-0.5 text-xs font-medium", STATUS_PILL[r.status])}>{STATUS_META[r.status].label}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      ))}
    </div>
  );
}

function StudentReportView({ report }: { report: StudentReport }) {
  const s = report.student;
  const c = report.report_class;
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
      <Card className="h-fit min-w-0 space-y-4 p-5">
        <div>
          <p className="font-semibold text-slate-900 dark:text-white">{s.student_name}</p>
          <p className="font-mono text-xs text-slate-500">{s.registration_no}{!s.currently_enrolled && " · unenrolled"}</p>
          <p className="mt-1 text-xs text-slate-500">{c.course_code} — {c.course_title} · Section {c.section_name}</p>
        </div>
        <div className="flex items-end justify-between gap-3">
          <Pct row={s} className="text-3xl" />
          <span className="text-xs text-slate-500">{s.total_classes} finalized classes</span>
        </div>
        <Counts row={s} />
        {s.low_attendance && (
          <Alert>
            <strong>Low Attendance</strong> — below {formatPercent(report.threshold)}.
          </Alert>
        )}
      </Card>
      <Card className="min-w-0">
        <CardHeader title="Date-wise history" description="Finalized classes, newest first." />
        {!report.records.length ? (
          <EmptyState icon={CalendarX2} title="No finalized attendance" description="Nothing finalized for this student in the selected period." />
        ) : (
          <ul className="divide-y divide-slate-200 dark:divide-slate-800">
            {report.records.map((r) => (
              <li key={`${r.session_date}-${r.session_number}`} className="flex items-center justify-between gap-3 px-5 py-2.5 text-sm">
                <div className="min-w-0">
                  <p className="font-medium text-slate-900 dark:text-white">{formatSessionDate(r.session_date)}</p>
                  <p className="text-xs text-slate-500">Session {r.session_number}</p>
                </div>
                <span className={cn("shrink-0 rounded-full px-2.5 py-0.5 text-xs font-medium", STATUS_PILL[r.status])}>{STATUS_META[r.status].label}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </div>
  );
}
