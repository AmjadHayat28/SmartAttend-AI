import { ArrowLeft, CalendarX2 } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { LowAttendanceWarning, SubjectStats, subjectMeta } from "../../components/attendance/StudentSubjectParts";
import { PageHeader } from "../../components/layout/PageHeader";
import { Card, CardHeader } from "../../components/ui/Card";
import { EmptyState, ErrorState, Spinner } from "../../components/ui/Feedback";
import { useAsync } from "../../hooks/useAsync";
import { formatSessionDate } from "../../services/attendanceService";
import { studentAttendanceApi } from "../../services/studentAttendanceService";
import { STATUS_META } from "../../types/attendance";
import { cn } from "../../utils/cn";

const STATUS_PILL = {
  present: "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300",
  absent: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
  late: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
  excused: "bg-sky-100 text-sky-800 dark:bg-sky-900/40 dark:text-sky-300",
} as const;

/** One enrolled subject: summary plus every finalized class, newest first. */
export function MySubjectAttendancePage() {
  const { courseId = "" } = useParams();
  const { data, loading, error, reload } = useAsync(() => studentAttendanceApi.subject(courseId), [courseId]);

  return (
    <>
      <Link to="/student/history" className="mb-4 inline-flex items-center gap-1.5 text-sm text-slate-600 hover:text-slate-900 dark:text-slate-300 dark:hover:text-white">
        <ArrowLeft className="h-4 w-4" /> My Attendance
      </Link>
      {loading ? (
        <Spinner />
      ) : error || !data ? (
        <Card>
          <ErrorState message={error ?? "Subject not found"} onRetry={reload} />
        </Card>
      ) : (
        <>
          <PageHeader title={data.subject.course_title} description={`${data.subject.course_code} · ${subjectMeta(data.subject)}`} />
          <div className="grid gap-4 lg:grid-cols-[minmax(0,20rem)_minmax(0,1fr)]">
            <Card className="h-fit space-y-4 p-5">
              <SubjectStats s={data.subject} />
              {data.subject.low_attendance && <LowAttendanceWarning threshold={data.threshold} />}
            </Card>
            <Card className="min-w-0">
              <CardHeader title="Class history" description="Finalized classes, newest first." />
              {!data.records.length ? (
                <EmptyState icon={CalendarX2} title="No finalized classes yet" description="Your attendance will appear here once your teacher finalizes a class." />
              ) : (
                <ul className="divide-y divide-slate-200 dark:divide-slate-800">
                  {data.records.map((r) => (
                    <li key={`${r.session_date}-${r.session_number}`} className="flex items-center justify-between gap-3 px-5 py-3 text-sm">
                      <div className="min-w-0">
                        <p className="font-medium text-slate-900 dark:text-white">{formatSessionDate(r.session_date)}</p>
                        <p className="text-xs text-slate-500 dark:text-slate-400">Session {r.session_number}</p>
                      </div>
                      <span className={cn("shrink-0 rounded-full px-2.5 py-0.5 text-xs font-medium", STATUS_PILL[r.status])}>{STATUS_META[r.status].label}</span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>
        </>
      )}
    </>
  );
}
