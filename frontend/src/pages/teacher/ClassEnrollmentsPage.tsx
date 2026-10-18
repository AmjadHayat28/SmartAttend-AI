import { ListChecks, Trash2, UserPlus, Users } from "lucide-react";
import { useEffect, useState } from "react";
import { PageHeader } from "../../components/layout/PageHeader";
import { Button } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";
import { ConfirmDialog } from "../../components/ui/ConfirmDialog";
import { DataTable, type Column } from "../../components/ui/DataTable";
import { Alert, Badge, EmptyState, Spinner } from "../../components/ui/Feedback";
import { Select } from "../../components/ui/FormField";
import { ListToolbar, SearchBox } from "../../components/ui/ListToolbar";
import { Modal } from "../../components/ui/Modal";
import { useToast } from "../../context/ToastContext";
import { useAsync } from "../../hooks/useAsync";
import { usePagedList } from "../../hooks/usePagedList";
import { getErrorMessage } from "../../services/api";
import { enrollmentApi } from "../../services/managementService";
import type { Assignment, BulkEnrollResult, Enrollment, ListParams, Page } from "../../types/api";
import { formatDateTime } from "../../utils/format";

const NO_ROWS: Page<Enrollment> = { items: [], total: 0, page: 1, page_size: 20 };

/** The enrolled-students list is only fetched once a class is chosen. */
function listEnrollments(params: ListParams) {
  return params.assignment_id ? enrollmentApi.list(params) : Promise.resolve(NO_ROWS);
}

const classLabel = (a: Assignment) => `${a.course_code} — ${a.course_title} · ${a.batch_name} · Sem ${a.semester_number} · Section ${a.section_name}`;

/**
 * My Class Enrollments: the teacher enrolls students of their own assigned classes.
 * Enrollments are the attendance roster (and face-recognition candidates) for the class.
 * HODs assign classes to teachers; they do not manage enrollments (API: 403).
 */
export function ClassEnrollmentsPage() {
  const toast = useToast();
  const classes = useAsync(() => enrollmentApi.classes());
  const list = usePagedList(listEnrollments);
  const assignmentId = list.filters.assignment_id ?? "";
  const current = classes.data?.find((a) => String(a.id) === assignmentId);
  const [adding, setAdding] = useState(false);
  const [removing, setRemoving] = useState<Enrollment | null>(null);
  const [preview, setPreview] = useState<BulkEnrollResult | null>(null);
  const [busy, setBusy] = useState(false);

  const { setFilter } = list;
  useEffect(() => {
    // Pick the first class automatically.
    if (!assignmentId && classes.data?.length) setFilter("assignment_id", String(classes.data[0].id));
  }, [assignmentId, classes.data, setFilter]);

  async function remove() {
    if (!removing) return;
    setBusy(true);
    try {
      await enrollmentApi.remove(removing.id);
      toast.success(`${removing.registration_no} removed from ${removing.course_code}.`);
      setRemoving(null);
      list.reload();
    } catch (err) {
      toast.error(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function bulk(dry_run: boolean) {
    setBusy(true);
    try {
      const res = await enrollmentApi.bulk({ assignment_id: Number(assignmentId), dry_run });
      if (dry_run) {
        setPreview(res);
      } else {
        setPreview(null);
        toast.success(`${res.newly_enrolled} student${res.newly_enrolled === 1 ? "" : "s"} enrolled in ${res.course_code}.`);
        list.reload();
      }
    } catch (err) {
      toast.error(getErrorMessage(err));
      setPreview(null);
    } finally {
      setBusy(false);
    }
  }

  const columns: Column<Enrollment>[] = [
    {
      header: "Student",
      cell: (e) => (
        <div>
          <p className="font-medium text-slate-900 dark:text-white">{e.student_name}</p>
          <p className="font-mono text-xs text-slate-500">{e.registration_no}</p>
        </div>
      ),
    },
    { header: "Class", cell: (e) => `${e.batch_name} · Sem ${e.semester_number} · ${e.section_name}`, className: "whitespace-nowrap" },
    { header: "Enrolled", cell: (e) => formatDateTime(e.created_at), className: "whitespace-nowrap text-slate-500" },
    {
      header: "Actions",
      className: "text-right",
      cell: (e) => (
        <Button size="sm" variant="ghost" onClick={() => setRemoving(e)} aria-label={`Remove ${e.registration_no} from ${e.course_code}`}>
          <Trash2 className="h-4 w-4 text-red-600" /> Remove
        </Button>
      ),
    },
  ];

  const header = <PageHeader title="My Class Enrollments" description="Enroll students of your assigned classes. Enrolled students make up the attendance roster." />;

  if (classes.loading) {
    return (
      <>
        {header}
        <Spinner className="py-12" />
      </>
    );
  }
  if (classes.error) {
    return (
      <>
        {header}
        <Alert>{classes.error}</Alert>
      </>
    );
  }
  if (!classes.data?.length) {
    return (
      <>
        {header}
        <Card>
          <EmptyState icon={ListChecks} title="No assigned classes" description="Your HOD assigns courses and sections to you. They will appear here." />
        </Card>
      </>
    );
  }

  return (
    <>
      {header}
      <Card>
        <div className="border-b border-slate-200 p-4 dark:border-slate-800">
          <Select
            label="Class"
            name="enrollment-class"
            value={assignmentId}
            onChange={(e) => list.setFilter("assignment_id", e.target.value)}
            options={classes.data.map((a) => ({ value: a.id, label: classLabel(a) }))}
          />
        </div>
        <ListToolbar>
          <SearchBox value={list.search} onChange={list.setSearch} placeholder="Search name or reg. no.…" />
          <div className="ml-auto flex flex-wrap gap-2">
            <Button size="sm" variant="secondary" disabled={!current} loading={busy && !preview && !removing} onClick={() => bulk(true)}>
              <Users className="h-4 w-4" /> Enroll all eligible students
            </Button>
            <Button size="sm" disabled={!current} onClick={() => setAdding(true)}>
              <UserPlus className="h-4 w-4" /> Add Student
            </Button>
          </div>
        </ListToolbar>
        <DataTable
          columns={columns}
          data={list.data}
          loading={list.loading}
          error={list.error}
          onRetry={list.reload}
          onPageChange={list.setPage}
          rowKey={(e) => e.id}
          empty={{ icon: ListChecks, title: "No students enrolled", description: "Add students one by one, or enroll every eligible student of the section." }}
        />
      </Card>

      {current && <AddStudentModal open={adding} assignment={current} onClose={() => setAdding(false)} onDone={list.reload} />}

      <ConfirmDialog
        open={!!removing}
        title="Remove student from this class?"
        description={removing && `${removing.student_name} (${removing.registration_no}) will no longer be on the ${removing.course_code} roster. Past attendance is kept.`}
        confirmLabel="Remove"
        tone="danger"
        loading={busy}
        onConfirm={remove}
        onCancel={() => setRemoving(null)}
      />

      <ConfirmDialog
        open={!!preview}
        title="Enroll all eligible students?"
        description={
          preview && (
            <>
              {preview.newly_enrolled === 0
                ? "Every eligible student of this section is already enrolled."
                : `${preview.newly_enrolled} student${preview.newly_enrolled === 1 ? "" : "s"} of Section ${current?.section_name} will be enrolled in ${preview.course_code}.`}{" "}
              {preview.already_enrolled} already enrolled
              {preview.skipped > 0 && `; ${preview.skipped} skipped (rejected or suspended account)`}.
            </>
          )
        }
        confirmLabel="Enroll students"
        loading={busy}
        onConfirm={() => (preview?.newly_enrolled ? bulk(false) : setPreview(null))}
        onCancel={() => setPreview(null)}
      />
    </>
  );
}

function AddStudentModal({ open, assignment, onClose, onDone }: { open: boolean; assignment: Assignment; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const [query, setQuery] = useState("");
  const [savingId, setSavingId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const candidates = useAsync(
    () => (open ? enrollmentApi.candidates({ assignment_id: assignment.id, q: query.trim() || undefined, page_size: 50 }) : Promise.resolve(null)),
    [open, assignment.id, query, version],
  );

  function close() {
    setQuery("");
    setError(null);
    onClose();
  }

  async function enroll(studentId: number) {
    setSavingId(studentId);
    setError(null);
    try {
      const e = await enrollmentApi.create({ assignment_id: assignment.id, student_id: studentId });
      toast.success(`${e.registration_no} enrolled in ${e.course_code}.`);
      setVersion((v) => v + 1);
      onDone();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setSavingId(null);
    }
  }

  return (
    <Modal open={open} title="Add student" description={`Students of Section ${assignment.section_name} not yet enrolled in ${assignment.course_code}.`} onClose={close} size="lg">
      {error && <Alert>{error}</Alert>}
      <SearchBox value={query} onChange={setQuery} placeholder="Search name or reg. no.…" />
      {candidates.loading ? (
        <Spinner className="py-6" />
      ) : candidates.error ? (
        <Alert>{candidates.error}</Alert>
      ) : !candidates.data?.items.length ? (
        <p className="py-6 text-center text-sm text-slate-500">{query.trim() ? "No matching students" : "Every eligible student of this section is already enrolled."}</p>
      ) : (
        <ul className="max-h-80 divide-y divide-slate-200 overflow-y-auto rounded-lg border border-slate-200 dark:divide-slate-800 dark:border-slate-700">
          {candidates.data.items.map((s) => (
            <li key={s.student_id} className="flex items-center justify-between gap-3 px-3 py-2">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-slate-900 dark:text-white">
                  {s.student_name} {s.status === "pending" && <Badge tone="amber">Pending approval</Badge>}
                </p>
                <p className="font-mono text-xs text-slate-500">{s.registration_no}</p>
              </div>
              <Button size="sm" loading={savingId === s.student_id} disabled={savingId !== null} onClick={() => enroll(s.student_id)}>
                Enroll
              </Button>
            </li>
          ))}
        </ul>
      )}
    </Modal>
  );
}
