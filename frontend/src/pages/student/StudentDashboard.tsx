import { BookOpen, History, TriangleAlert } from "lucide-react";
import { Link } from "react-router-dom";
import { FaceEnrollmentBanner } from "../../components/face/FaceEnrollmentBanner";
import { PageHeader } from "../../components/layout/PageHeader";
import { Card } from "../../components/ui/Card";
import { Alert, EmptyState, ErrorState, Spinner } from "../../components/ui/Feedback";
import { useAuth } from "../../hooks/useAuth";
import { useAsync } from "../../hooks/useAsync";
import { dashboardService } from "../../services/dashboardService";
import type { SubjectAttendance } from "../../types/api";
import { cn } from "../../utils/cn";
import { formatPercent } from "../../utils/format";

function SubjectCard({ s }: { s: SubjectAttendance }) {
  const pct = s.percentage ?? 0;
  return (
    <Card className={cn("p-5", s.low_attendance && "border-red-300 dark:border-red-900")}>
      <p className="text-xs font-medium text-slate-500 dark:text-slate-400">{s.course_code}</p>
      <h3 className="mt-0.5 font-semibold text-slate-900 dark:text-white">{s.course_title}</h3>
      <div className="mt-4 flex items-end justify-between">
        <p className={cn("text-3xl font-semibold tabular-nums", s.low_attendance ? "text-red-600 dark:text-red-400" : "text-slate-900 dark:text-white")}>
          {formatPercent(s.percentage)}
        </p>
        <p className="text-xs text-slate-500 dark:text-slate-400">
          {s.attended}/{s.conducted} classes
        </p>
      </div>
      <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
        <div className={cn("h-full rounded-full", s.low_attendance ? "bg-red-500" : "bg-emerald-500")} style={{ width: `${Math.min(pct, 100)}%` }} />
      </div>
      {s.low_attendance && (
        <p className="mt-3 flex items-center gap-1.5 text-xs font-medium text-red-600 dark:text-red-400">
          <TriangleAlert className="h-3.5 w-3.5" /> Low attendance
        </p>
      )}
    </Card>
  );
}

export function StudentDashboard() {
  const { user } = useAuth();
  const { data, loading, error, reload } = useAsync(() => dashboardService.studentSubjects());
  const low = data?.subjects.filter((s) => s.low_attendance) ?? [];

  return (
    <>
      <PageHeader
        title={user?.full_name ?? "Student"}
        description={[user?.registration_no, user?.department_name].filter(Boolean).join(" · ")}
        actions={
          <Link to="/student/history" className="inline-flex h-10 items-center gap-2 rounded-lg border border-slate-300 bg-white px-4 text-sm font-medium text-slate-700 hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-slate-200">
            <History className="h-4 w-4" /> View Attendance History
          </Link>
        }
      />
      <FaceEnrollmentBanner />
      {low.length > 0 && data && (
        <div className="mb-4">
          <Alert tone="warning">
            Your attendance is below {data.threshold}% in {low.map((s) => s.course_title).join(", ")}.
          </Alert>
        </div>
      )}
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
            <SubjectCard key={s.course_id} s={s} />
          ))}
        </div>
      )}
    </>
  );
}
