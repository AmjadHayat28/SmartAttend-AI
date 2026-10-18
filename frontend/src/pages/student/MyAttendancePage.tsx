import { BookOpen, ChevronRight } from "lucide-react";
import { Link } from "react-router-dom";
import { LowAttendanceWarning, SubjectStats, subjectMeta } from "../../components/attendance/StudentSubjectParts";
import { PageHeader } from "../../components/layout/PageHeader";
import { Card } from "../../components/ui/Card";
import { EmptyState, ErrorState, Spinner } from "../../components/ui/Feedback";
import { useAsync } from "../../hooks/useAsync";
import { studentAttendanceApi } from "../../services/studentAttendanceService";
import { cn } from "../../utils/cn";

/** Subject-wise summary of the signed-in student's own attendance (finalized classes only). */
export function MyAttendancePage() {
  const { data, loading, error, reload } = useAsync(() => studentAttendanceApi.overview());

  return (
    <>
      <PageHeader title="My Attendance" description="Only finalized classes count. Open a subject to see each class." />
      {loading ? (
        <Spinner />
      ) : error ? (
        <Card>
          <ErrorState message={error} onRetry={reload} />
        </Card>
      ) : !data?.subjects.length ? (
        <Card>
          <EmptyState icon={BookOpen} title="You are not enrolled in any classes yet." description="Your teachers enroll you in their classes; your subjects will appear here." />
        </Card>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {data.subjects.map((s) => (
            <Link
              key={s.course_id}
              to={`/student/history/${s.course_id}`}
              aria-label={`${s.course_code} ${s.course_title} — view attendance details`}
              className="group block min-w-0 rounded-xl focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500"
            >
              <Card className={cn("flex h-full flex-col gap-4 p-5 transition group-hover:border-brand-300 dark:group-hover:border-brand-800", s.low_attendance && "border-red-300 dark:border-red-900")}>
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="font-mono text-xs font-medium text-slate-500 dark:text-slate-400">{s.course_code}</p>
                    <h2 className="mt-0.5 font-semibold text-slate-900 dark:text-white">{s.course_title}</h2>
                    <p className="mt-0.5 break-words text-xs text-slate-500 dark:text-slate-400">{subjectMeta(s)}</p>
                  </div>
                  <ChevronRight className="mt-1 h-4 w-4 shrink-0 text-slate-400 group-hover:text-brand-600" />
                </div>
                <SubjectStats s={s} />
                {s.low_attendance && <LowAttendanceWarning threshold={data.threshold} />}
              </Card>
            </Link>
          ))}
        </div>
      )}
    </>
  );
}
