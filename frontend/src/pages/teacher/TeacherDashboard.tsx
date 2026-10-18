import { BookOpen, CalendarCheck, FlaskConical, PencilLine } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { SessionStatusBadge } from "../../components/attendance/AttendanceParts";
import { PageHeader } from "../../components/layout/PageHeader";
import { Button } from "../../components/ui/Button";
import { Card, CardHeader } from "../../components/ui/Card";
import { Badge, EmptyState, ErrorState, Spinner } from "../../components/ui/Feedback";
import { useAuth } from "../../hooks/useAuth";
import { useAsync } from "../../hooks/useAsync";
import { attendanceApi, formatSessionDate } from "../../services/attendanceService";
import { cn } from "../../utils/cn";
import { formatPercent } from "../../utils/format";

export function TeacherDashboard() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const { data, loading, error, reload } = useAsync(() => attendanceApi.classes());
  const recent = useAsync(() => attendanceApi.list({ page_size: 5 }));

  return (
    <>
      <PageHeader title={`Welcome, ${user?.full_name ?? ""}`} description={user?.employee_id ? `Employee ID ${user.employee_id}` : undefined} />
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">My classes</h2>
      {loading ? (
        <Spinner />
      ) : error ? (
        <Card>
          <ErrorState message={error} onRetry={reload} />
        </Card>
      ) : !data?.length ? (
        <Card>
          <EmptyState icon={BookOpen} title="No classes assigned yet" description="Your HOD or the administrator assigns subjects and sections to you." />
        </Card>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {data.map((c) => (
            <Card key={c.assignment_id} className="flex flex-col p-5">
              <div className="flex items-start justify-between gap-2">
                <span className="rounded-lg bg-brand-50 p-2 text-brand-700 dark:bg-brand-900/40 dark:text-brand-200">
                  {c.is_lab ? <FlaskConical className="h-5 w-5" /> : <BookOpen className="h-5 w-5" />}
                </span>
                <Badge tone="blue">{c.course_code}</Badge>
              </div>
              <h3 className="mt-3 font-semibold text-slate-900 dark:text-white">{c.course_title}</h3>
              <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                {c.batch_name} · {c.semester_name} · Section {c.section_name}
              </p>
              <dl className="mt-3 grid grid-cols-3 gap-2 text-center">
                {[
                  ["Students", c.enrolled_count],
                  ["Sessions", c.finalized_sessions],
                  ["Attendance", formatPercent(c.attendance_percentage)],
                ].map(([k, v]) => (
                  <div key={k} className="rounded-lg bg-slate-50 py-1.5 dark:bg-slate-800/50">
                    <dt className="text-[11px] text-slate-500">{k}</dt>
                    <dd className="text-sm font-semibold tabular-nums">{v}</dd>
                  </div>
                ))}
              </dl>
              <div className="mt-auto space-y-2 pt-4">
                {c.open_draft_session_id && (
                  <Button className="w-full" variant="secondary" onClick={() => navigate(`/teacher/attendance/${c.open_draft_session_id}`)}>
                    <PencilLine className="h-4 w-4" /> Resume draft
                  </Button>
                )}
                <Button className="w-full" onClick={() => navigate(`/teacher/attendance/new?assignment=${c.assignment_id}`)}>
                  <CalendarCheck className="h-4 w-4" /> Take Attendance
                </Button>
              </div>
            </Card>
          ))}
        </div>
      )}

      <Card className="mt-6">
        <CardHeader title="Recent sessions" action={<Link to="/teacher/history" className="text-sm font-medium text-brand-700 hover:underline dark:text-brand-200">View all</Link>} />
        {recent.loading ? (
          <Spinner />
        ) : !recent.data?.items.length ? (
          <p className="p-5 text-sm text-slate-500">No attendance taken yet.</p>
        ) : (
          <ul className="divide-y divide-slate-200 dark:divide-slate-800">
            {recent.data.items.map((s) => (
              <li key={s.id}>
                <Link to={`/teacher/attendance/${s.id}`} className={cn("flex flex-wrap items-center gap-x-4 gap-y-1 px-5 py-3 hover:bg-slate-50 dark:hover:bg-slate-800/40")}>
                  <span className="w-32 text-sm text-slate-500">{formatSessionDate(s.session_date)}</span>
                  <span className="min-w-0 flex-1 truncate font-medium text-slate-900 dark:text-white">
                    {s.course_code} · Section {s.section_name} · S{s.session_number}
                  </span>
                  <span className="text-xs tabular-nums text-slate-500">
                    {s.summary.present + s.summary.late}/{s.summary.total} present
                  </span>
                  <SessionStatusBadge status={s.status} />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </>
  );
}
