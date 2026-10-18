import { History, PencilLine, Search, Trash2 } from "lucide-react";
import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useToast } from "../../context/ToastContext";
import { getErrorMessage } from "../../services/api";
import { attendanceApi, formatSessionDate } from "../../services/attendanceService";
import { STATUS_META, type AttendanceRecord, type AttendanceSession, type AttendanceStatus } from "../../types/attendance";
import { formatDateTime } from "../../utils/format";
import { Button } from "../ui/Button";
import { Card, CardHeader } from "../ui/Card";
import { ConfirmDialog } from "../ui/ConfirmDialog";
import { Alert, Badge } from "../ui/Feedback";
import { Modal } from "../ui/Modal";
import { SessionHeading, StatusPill, StatusToggle, SummaryGrid } from "./AttendanceParts";
import { AiBadge, StudentAvatar } from "./AttendanceEditor";
import { RecognitionPanel } from "./RecognitionPanel";
import { ClassroomPhotos } from "./ClassroomPhotos";

/**
 * Read-only view of a session (finalized or cancelled), with two distinct correction tools:
 * - Edit Student Attendance: fix one student's record (reason required, kept in history).
 * - Delete Attendance: permanently delete this one session; other dates and sessions are untouched.
 */
export function AttendanceDetailView({ session, onChanged }: { session: AttendanceSession; onChanged: (s: AttendanceSession) => void }) {
  const toast = useToast();
  const navigate = useNavigate();
  const searchRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [correcting, setCorrecting] = useState<AttendanceRecord | null>(null);
  const [editMode, setEditMode] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const q = query.trim().toLowerCase();
  const finalized = session.status === "finalized";
  const canEditStudents = finalized && session.can_correct;

  function startEditing() {
    setEditMode(true);
    searchRef.current?.focus();
  }

  async function deleteSession(reason: string) {
    setDeleting(true);
    try {
      await attendanceApi.remove(session.id, reason, session.version);
      toast.success("Attendance deleted successfully.");
      navigate("/teacher/history", { replace: true });
    } catch (err) {
      toast.error(getErrorMessage(err));
      setDeleting(false);
    }
  }

  const rows = session.records.filter((r) => !q || r.full_name.toLowerCase().includes(q) || r.registration_no.toLowerCase().includes(q));

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <SessionHeading session={session} />
        {finalized && (canEditStudents || session.can_delete) && (
          <div className="flex flex-wrap gap-2">
            {canEditStudents && (
              <Button variant={editMode ? "primary" : "secondary"} onClick={() => (editMode ? setEditMode(false) : startEditing())} aria-pressed={editMode}>
                <PencilLine className="h-4 w-4" /> {editMode ? "Done Editing" : "Edit Student Attendance"}
              </Button>
            )}
            {session.can_delete && (
              <Button variant="danger" onClick={() => setConfirmDelete(true)}>
                <Trash2 className="h-4 w-4" /> Delete Attendance
              </Button>
            )}
          </div>
        )}
      </div>

      {editMode && (
        <Alert tone="info">
          Choose a student below and click <strong>Edit</strong> to change only that student's attendance. Every change needs a reason and is kept in the correction history.
        </Alert>
      )}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="min-w-0 space-y-4">
          <Card className="p-4">
            <SummaryGrid summary={session.summary} photos={session.images.length} />
            <dl className="mt-3 grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
              <div><dt className="inline text-slate-500">Teacher: </dt><dd className="inline">{session.teacher_name}</dd></div>
              {session.finalized_at && (
                <div><dt className="inline text-slate-500">Finalized: </dt><dd className="inline">{formatDateTime(session.finalized_at)}{session.finalized_by_name ? ` by ${session.finalized_by_name}` : ""}</dd></div>
              )}
              {session.cancelled_at && (
                <div><dt className="inline text-slate-500">Cancelled: </dt><dd className="inline">{formatDateTime(session.cancelled_at)}{session.cancel_reason ? ` — ${session.cancel_reason}` : ""}</dd></div>
              )}
              {session.summary.percentage !== null && (
                <div><dt className="inline text-slate-500">Attendance: </dt><dd className="inline tabular-nums">{session.summary.percentage}%</dd></div>
              )}
            </dl>
            {session.note && <p className="mt-3 rounded-lg bg-slate-50 px-3 py-2 text-sm text-slate-700 dark:bg-slate-800/50 dark:text-slate-300">{session.note}</p>}
            {session.can_correct && session.correction_deadline && (
              <p className="mt-3 text-xs text-slate-500">You can edit or delete this attendance until {formatDateTime(session.correction_deadline)}.</p>
            )}
          </Card>

          <RecognitionPanel session={session} />

          <Card className="min-w-0">
            <div className="border-b border-slate-200 p-4 dark:border-slate-800">
              <div className="relative sm:max-w-xs">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                <input ref={searchRef} type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search name or reg. no." aria-label="Search students" className="h-9 w-full rounded-lg border border-slate-300 bg-white pl-8 pr-3 text-sm dark:border-slate-700 dark:bg-slate-950" />
              </div>
            </div>
            <ul className="divide-y divide-slate-200 dark:divide-slate-800">
              {rows.map((r) => (
                <li key={r.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
                  <StudentAvatar record={r} />
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-medium text-slate-900 dark:text-white">{r.full_name}</p>
                    <p className="flex items-center gap-1.5 font-mono text-xs text-slate-500">
                      {r.registration_no}
                      <AiBadge record={r} />
                    </p>
                    {r.note && <p className="mt-0.5 text-xs text-slate-600 dark:text-slate-300">{r.note}</p>}
                  </div>
                  <div className="flex items-center gap-2">
                    {r.corrected && <Badge tone="blue">Corrected</Badge>}
                    <StatusPill status={r.status} />
                    {editMode && canEditStudents && (
                      <Button size="sm" variant="secondary" onClick={() => setCorrecting(r)} aria-label={`Edit attendance for ${r.full_name}`}>
                        <PencilLine className="h-4 w-4" /> Edit
                      </Button>
                    )}
                  </div>
                </li>
              ))}
              {rows.length === 0 && <li className="p-6 text-center text-sm text-slate-500">No students match.</li>}
            </ul>
          </Card>
        </div>

        <div className="space-y-4">
          <ClassroomPhotos session={session} editable={false} />
          {session.modifications.length > 0 && (
            <Card>
              <CardHeader title="Corrections" description="Every change after finalizing, with its reason." />
              <ol className="divide-y divide-slate-200 dark:divide-slate-800">
                {session.modifications.map((m) => (
                  <li key={m.id} className="space-y-0.5 px-4 py-3 text-sm">
                    <p className="flex items-center gap-1.5 font-medium">
                      <History className="h-3.5 w-3.5 text-slate-400" /> {m.student_name} <span className="font-mono text-xs text-slate-500">{m.registration_no}</span>
                    </p>
                    <p>
                      {m.old_status ? STATUS_META[m.old_status].label : "—"} → <strong>{m.new_status ? STATUS_META[m.new_status].label : "—"}</strong>
                    </p>
                    <p className="text-slate-600 dark:text-slate-300">“{m.reason}”</p>
                    <p className="text-xs text-slate-500">
                      {m.modified_by_name} ({m.modifier_role.replace("_", " ")}) · {formatDateTime(m.modified_at)}
                    </p>
                  </li>
                ))}
              </ol>
            </Card>
          )}
        </div>
      </div>

      <ConfirmDialog
        open={confirmDelete}
        title="Delete this attendance?"
        tone="danger"
        confirmLabel="Delete Attendance"
        description={
          <div className="space-y-2">
            <p className="font-medium text-slate-800 dark:text-slate-200">
              {session.course_title} · Section {session.section_name} · {formatSessionDate(session.session_date)} · Session {session.session_number}
            </p>
            <p>This will permanently remove this specific attendance session and its associated attendance records. Other dates and sessions will not be affected.</p>
          </div>
        }
        reasonLabel="Reason for deletion"
        reasonRequired
        reasonMinLength={5}
        reasonMaxLength={300}
        reasonPlaceholder="e.g. Attendance was taken incorrectly."
        loading={deleting}
        onConfirm={deleteSession}
        onCancel={() => setConfirmDelete(false)}
      />

      {correcting && <CorrectionDialog record={correcting} onClose={() => setCorrecting(null)} onSaved={(s) => { onChanged(s); setCorrecting(null); }} />}
    </div>
  );
}

function CorrectionDialog({ record, onClose, onSaved }: { record: AttendanceRecord; onClose: () => void; onSaved: (s: AttendanceSession) => void }) {
  const toast = useToast();
  const [status, setStatus] = useState<AttendanceStatus | null>(record.status);
  const [note, setNote] = useState(record.note ?? "");
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const unchanged = status === record.status && (note.trim() || null) === (record.note || null);

  async function save() {
    if (!status) return;
    setSaving(true);
    setError(null);
    try {
      onSaved(await attendanceApi.correct(record.id, status, reason, note.trim() || null));
      toast.success(`Attendance corrected for ${record.full_name}.`);
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal open title={`Edit student attendance — ${record.full_name}`} description="Finalized attendance is official; every correction is recorded with your reason." onClose={onClose} onSubmit={save} submitLabel="Save correction" submitting={saving} submitDisabled={!status || unchanged || reason.trim().length < 3}>
      {error && <Alert>{error}</Alert>}
      <div>
        <p className="mb-1.5 text-sm font-medium">Status</p>
        <StatusToggle value={status} name={record.full_name} onChange={setStatus} />
      </div>
      <div className="space-y-1.5">
        <label htmlFor="corr-note" className="block text-sm font-medium">Note (optional)</label>
        <input id="corr-note" maxLength={200} value={note} onChange={(e) => setNote(e.target.value)} className="h-9 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm dark:border-slate-700 dark:bg-slate-950" />
      </div>
      <div className="space-y-1.5">
        <label htmlFor="corr-reason" className="block text-sm font-medium">
          Reason for the correction <span className="text-red-600">*</span>
        </label>
        <textarea id="corr-reason" rows={2} maxLength={300} value={reason} onChange={(e) => setReason(e.target.value)} placeholder="e.g. Medical certificate received" className="block w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm dark:border-slate-700 dark:bg-slate-950" />
      </div>
    </Modal>
  );
}
