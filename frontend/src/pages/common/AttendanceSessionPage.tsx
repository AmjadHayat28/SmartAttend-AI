import { ArrowLeft } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { AttendanceDetailView } from "../../components/attendance/AttendanceDetailView";
import { AttendanceEditor } from "../../components/attendance/AttendanceEditor";
import { Card } from "../../components/ui/Card";
import { ErrorState, Spinner } from "../../components/ui/Feedback";
import { useAsync } from "../../hooks/useAsync";
import { attendanceApi } from "../../services/attendanceService";

/** One of the teacher's own sessions: the draft editor, or the read-only view once finalized. */
export function AttendanceSessionPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const sessionId = Number(id);
  const { data, loading, error, reload, setData } = useAsync(() => attendanceApi.get(sessionId), [sessionId]);

  return (
    <>
      <Link to="/teacher/history" className="mb-4 inline-flex items-center gap-1.5 text-sm text-slate-600 hover:text-slate-900 dark:text-slate-300 dark:hover:text-white">
        <ArrowLeft className="h-4 w-4" /> Attendance history
      </Link>
      {loading && !data ? (
        <Spinner />
      ) : error ? (
        <Card><ErrorState message={error} onRetry={reload} /></Card>
      ) : data ? (
        data.can_edit ? (
          <AttendanceEditor
            key={data.id}
            initial={data}
            onDone={(s) => {
              if (s.status === "cancelled") navigate("/teacher/history");
              else setData(s);
            }}
          />
        ) : (
          <AttendanceDetailView session={data} onChanged={setData} />
        )
      ) : null}
    </>
  );
}
