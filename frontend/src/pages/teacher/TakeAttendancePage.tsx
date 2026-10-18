import { BookOpen, CalendarCheck, FlaskConical, PlayCircle } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { PageHeader } from "../../components/layout/PageHeader";
import { Button } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";
import { Alert, Badge, EmptyState, ErrorState, Spinner } from "../../components/ui/Feedback";
import { useToast } from "../../context/ToastContext";
import { useAsync } from "../../hooks/useAsync";
import { getErrorMessage } from "../../services/api";
import { attendanceApi, formatSessionDate, localToday } from "../../services/attendanceService";
import { cn } from "../../utils/cn";
import { formatPercent } from "../../utils/format";

/** Step 1: pick an assigned class, the date and the session number. */
export function TakeAttendancePage() {
  const toast = useToast();
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const classes = useAsync(() => attendanceApi.classes());
  const [assignmentId, setAssignmentId] = useState<number | null>(Number(params.get("assignment")) || null);
  const [day, setDay] = useState(localToday());
  const [sessionNo, setSessionNo] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);

  // Pre-select the only class, or validate a ?assignment= link against the teacher's classes.
  useEffect(() => {
    if (!classes.data) return;
    if (assignmentId && !classes.data.some((c) => c.assignment_id === assignmentId)) setAssignmentId(null);
    if (!assignmentId && classes.data.length === 1) setAssignmentId(classes.data[0]!.assignment_id);
  }, [classes.data, assignmentId]);

  const selected = classes.data?.find((c) => c.assignment_id === assignmentId);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!assignmentId) return;
    setStarting(true);
    setError(null);
    try {
      const res = await attendanceApi.start(assignmentId, day, sessionNo);
      if (res.resumed) toast.info(res.added_to_roster ? `Draft resumed — ${res.added_to_roster} newly enrolled student(s) added.` : "Draft resumed.");
      navigate(`/teacher/attendance/${res.session.id}`);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setStarting(false);
    }
  }

  return (
    <>
      <PageHeader title="Take Attendance" description="Choose one of your classes, the date and the lecture number." />
      {classes.loading ? (
        <Spinner />
      ) : classes.error ? (
        <Card><ErrorState message={classes.error} onRetry={classes.reload} /></Card>
      ) : !classes.data?.length ? (
        <Card><EmptyState icon={BookOpen} title="No classes assigned" description="Your HOD assigns courses and sections to you." /></Card>
      ) : (
        <form onSubmit={submit} className="space-y-6">
          <fieldset>
            <legend className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">1. Class</legend>
            <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3" role="radiogroup">
              {classes.data.map((c) => {
                const active = c.assignment_id === assignmentId;
                return (
                  <button
                    key={c.assignment_id}
                    type="button"
                    role="radio"
                    aria-checked={active}
                    onClick={() => setAssignmentId(c.assignment_id)}
                    className={cn(
                      "rounded-xl border bg-white p-4 text-left shadow-sm transition-colors dark:bg-slate-900",
                      active ? "border-brand-600 ring-2 ring-brand-600/30" : "border-slate-200 hover:border-slate-300 dark:border-slate-800",
                    )}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <span className="flex items-center gap-2 font-semibold text-slate-900 dark:text-white">
                        {c.is_lab ? <FlaskConical className="h-4 w-4 text-brand-700" /> : <BookOpen className="h-4 w-4 text-brand-700" />}
                        {c.course_title}
                      </span>
                      <Badge tone="blue">{c.course_code}</Badge>
                    </div>
                    <p className="mt-1 text-sm text-slate-500">
                      {c.batch_name} · {c.semester_name} · Section {c.section_name}
                    </p>
                    <p className="mt-2 flex flex-wrap gap-x-3 text-xs text-slate-500">
                      <span>{c.enrolled_count} students</span>
                      <span>{c.finalized_sessions} sessions</span>
                      <span>Attendance {formatPercent(c.attendance_percentage)}</span>
                    </p>
                    {c.open_draft_session_id && <p className="mt-2 text-xs font-medium text-amber-700 dark:text-amber-300">A draft is open for this class</p>}
                  </button>
                );
              })}
            </div>
          </fieldset>

          <fieldset className="grid max-w-xl gap-4 sm:grid-cols-2">
            <legend className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500 sm:col-span-2">2. Date and session</legend>
            <div className="space-y-1.5">
              <label htmlFor="att-date" className="block text-sm font-medium text-slate-700 dark:text-slate-300">Date</label>
              <input id="att-date" type="date" required max={localToday()} value={day} onChange={(e) => setDay(e.target.value)} className="h-10 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm dark:border-slate-700 dark:bg-slate-900" />
            </div>
            <div className="space-y-1.5">
              <label htmlFor="att-session" className="block text-sm font-medium text-slate-700 dark:text-slate-300">Session (lecture) number</label>
              <select id="att-session" value={sessionNo} onChange={(e) => setSessionNo(Number(e.target.value))} className="h-10 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm dark:border-slate-700 dark:bg-slate-900">
                {Array.from({ length: 8 }, (_, i) => i + 1).map((n) => (
                  <option key={n} value={n}>Session {n}</option>
                ))}
              </select>
            </div>
          </fieldset>

          {error && <Alert>{error}</Alert>}
          <div className="flex flex-wrap items-center gap-3">
            <Button type="submit" loading={starting} disabled={!assignmentId || !day}>
              <PlayCircle className="h-4 w-4" /> Start Attendance
            </Button>
            {selected && (
              <p className="flex items-center gap-1.5 text-sm text-slate-500">
                <CalendarCheck className="h-4 w-4" /> {selected.course_code} · Section {selected.section_name} · {formatSessionDate(day)} · Session {sessionNo}
              </p>
            )}
          </div>
          <p className="text-xs text-slate-500">If a draft already exists for this class, date and session, it opens so you can continue.</p>
        </form>
      )}
    </>
  );
}
