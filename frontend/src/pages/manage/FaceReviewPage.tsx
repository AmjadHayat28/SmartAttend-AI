import { Check, Eye, RotateCcw, ScanFace, UserRound } from "lucide-react";
import { useState } from "react";
import { AccountStatusBadge } from "../../components/accounts/AccountActions";
import { PlacementFilters } from "../../components/academics/PlacementSelects";
import { AuthedImage } from "../../components/face/AuthedImage";
import { FaceStatusBadge } from "../../components/face/FaceStatusBadge";
import { PageHeader } from "../../components/layout/PageHeader";
import { Button } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";
import { ConfirmDialog } from "../../components/ui/ConfirmDialog";
import { DataTable, type Column } from "../../components/ui/DataTable";
import { Alert, Badge, ErrorState, Spinner } from "../../components/ui/Feedback";
import { FilterSelect, ListToolbar, SearchBox } from "../../components/ui/ListToolbar";
import { Modal } from "../../components/ui/Modal";
import { useToast } from "../../context/ToastContext";
import { useAsync } from "../../hooks/useAsync";
import { usePagedList } from "../../hooks/usePagedList";
import { useRole } from "../../hooks/useRole";
import { useStructure, type Placement } from "../../hooks/useStructure";
import { getErrorMessage } from "../../services/api";
import { faceReviewApi } from "../../services/faceEnrollmentService";
import { POSE_LABELS, type FaceEnrollmentListItem } from "../../types/face";
import { formatDateTime } from "../../utils/format";

const STATUS_OPTIONS = [
  { value: "pending_review", label: "Ready for review" },
  { value: "approved", label: "Approved" },
  { value: "rejected", label: "Retake required" },
  { value: "incomplete", label: "Incomplete" },
  { value: "not_started", label: "Not started" },
];

export function FaceReviewPage() {
  const { isAdmin } = useRole();
  const structure = useStructure();
  const list = usePagedList(faceReviewApi.list, { initialFilters: { status: "pending_review" } });
  const [reviewing, setReviewing] = useState<number | null>(null);
  const f = list.filters;
  const placement: Placement = { department_id: f.department_id ?? "", batch_id: f.batch_id ?? "", semester_id: f.semester_id ?? "", section_id: f.section_id ?? "" };

  const columns: Column<FaceEnrollmentListItem>[] = [
    {
      header: "Student",
      cell: (r) => (
        <div>
          <p className="font-medium text-slate-900 dark:text-white">{r.full_name}</p>
          <p className="font-mono text-xs text-slate-500">{r.registration_no}</p>
        </div>
      ),
    },
    { header: "Class", cell: (r) => `${isAdmin ? `${r.department_code} · ` : ""}${r.batch_name} · ${r.semester_name} · ${r.section_name}`, className: "whitespace-nowrap" },
    {
      header: "Photos",
      cell: (r) => (
        <div className="flex flex-wrap items-center gap-1.5">
          <span className="tabular-nums">{r.photo_count}</span>
          {r.requirements_met ? <Badge tone="green">F/L/R ✓</Badge> : <Badge tone="amber">Missing poses</Badge>}
          {!r.has_profile_photo && <Badge>No profile</Badge>}
        </div>
      ),
    },
    { header: "Account", cell: (r) => <AccountStatusBadge status={r.account_status} /> },
    { header: "Face status", cell: (r) => <FaceStatusBadge status={r.status} /> },
    { header: "Submitted", cell: (r) => formatDateTime(r.submitted_at), className: "whitespace-nowrap text-slate-500" },
    {
      header: "Actions",
      className: "text-right",
      cell: (r) => (
        <Button size="sm" variant={r.status === "pending_review" ? "primary" : "secondary"} onClick={() => setReviewing(r.student_id)}>
          <Eye className="h-4 w-4" /> {r.status === "pending_review" ? "Review" : "View"}
        </Button>
      ),
    },
  ];

  return (
    <>
      <PageHeader title="Face enrollment review" description="Check that each student's photos clearly show the same person, one face per photo. Separate from account approval." />
      <Card>
        <ListToolbar>
          <SearchBox value={list.search} onChange={list.setSearch} placeholder="Search name, reg. no. or email…" />
          <FilterSelect label="Status" value={f.status ?? ""} onChange={(v) => list.setFilter("status", v)} options={STATUS_OPTIONS} />
          <PlacementFilters departments={structure.departments} value={placement} onChange={(p) => list.setFilters((x) => ({ ...x, ...p }))} hideDepartment={!isAdmin} />
        </ListToolbar>
        <DataTable
          columns={columns}
          data={list.data}
          loading={list.loading}
          error={list.error}
          onRetry={list.reload}
          onPageChange={list.setPage}
          rowKey={(r) => r.student_id}
          empty={{ icon: ScanFace, title: f.status === "pending_review" ? "Nothing waiting for review" : "No students match these filters" }}
        />
      </Card>
      {reviewing !== null && <ReviewDialog studentId={reviewing} onClose={() => setReviewing(null)} onChanged={list.reload} />}
    </>
  );
}

function ReviewDialog({ studentId, onClose, onChanged }: { studentId: number; onClose: () => void; onChanged: () => void }) {
  const toast = useToast();
  const { data, loading, error, reload, setData } = useAsync(() => faceReviewApi.get(studentId), [studentId]);
  const [action, setAction] = useState<"approve" | "reject" | null>(null);
  const [saving, setSaving] = useState(false);

  async function confirm(reason: string) {
    setSaving(true);
    try {
      const updated = action === "approve" ? await faceReviewApi.approve(studentId) : await faceReviewApi.reject(studentId, reason);
      setData(updated);
      toast.success(action === "approve" ? `Face enrollment approved for ${updated.full_name}.` : `Retake requested from ${updated.full_name}.`);
      setAction(null);
      onChanged();
    } catch (err) {
      toast.error(getErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal open title={data ? `${data.full_name} · ${data.registration_no}` : "Face enrollment"} onClose={onClose} size="xl">
      {loading && !data ? (
        <Spinner />
      ) : error ? (
        <ErrorState message={error} onRetry={reload} />
      ) : data ? (
        <>
          <div className="flex flex-col gap-4 sm:flex-row sm:items-start">
            <div className="shrink-0">
              {data.profile_photo_url ? (
                <AuthedImage src={data.profile_photo_url} alt={`${data.full_name} profile photo`} className="h-28 w-28 rounded-full" />
              ) : (
                <div className="grid h-28 w-28 place-items-center rounded-full bg-slate-100 text-slate-400 dark:bg-slate-800">
                  <UserRound className="h-12 w-12" />
                </div>
              )}
            </div>
            <dl className="grid flex-1 grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-3">
              {[
                ["Department", `${data.department_code} — ${data.department_name}`],
                ["Batch", data.batch_name],
                ["Semester", data.semester_name],
                ["Section", data.section_name],
                ["Email", data.email],
                ["Submitted", formatDateTime(data.submitted_at)],
              ].map(([k, v]) => (
                <div key={k} className="min-w-0">
                  <dt className="text-xs uppercase tracking-wide text-slate-500">{k}</dt>
                  <dd className="truncate text-slate-900 dark:text-slate-100">{v}</dd>
                </div>
              ))}
              <div>
                <dt className="text-xs uppercase tracking-wide text-slate-500">Account</dt>
                <dd><AccountStatusBadge status={data.account_status} /></dd>
              </div>
              <div>
                <dt className="text-xs uppercase tracking-wide text-slate-500">Face status</dt>
                <dd><FaceStatusBadge status={data.status} /></dd>
              </div>
            </dl>
          </div>

          {data.review_note && (
            <Alert tone="warning">
              Last review{data.reviewed_by_name ? ` by ${data.reviewed_by_name}` : ""}: {data.review_note}
            </Alert>
          )}
          {!data.requirements_met && <Alert tone="warning">Missing required poses: {data.missing_poses.map((p) => POSE_LABELS[p]).join(", ")}.</Alert>}

          {data.photos.length === 0 ? (
            <p className="py-6 text-center text-sm text-slate-500">No face photos uploaded yet.</p>
          ) : (
            <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {data.photos.map((p) => (
                <li key={p.id} className="rounded-xl border border-slate-200 p-3 dark:border-slate-700">
                  <div className="mb-2 flex items-center justify-between">
                    <span className="font-medium">{POSE_LABELS[p.pose]}</span>
                    <Badge tone={p.validation_status === "pass" ? "green" : "amber"}>{p.validation_status === "pass" ? "Passed checks" : "Warnings"}</Badge>
                  </div>
                  <AuthedImage src={p.image_url} alt={`${POSE_LABELS[p.pose]} photo`} className="aspect-[4/3] w-full rounded-lg" />
                  <p className="mt-2 text-xs text-slate-500">
                    {p.width}×{p.height} · uploaded {formatDateTime(p.updated_at)}
                  </p>
                  {p.validation_message && <p className="mt-1 text-xs text-amber-700 dark:text-amber-300">{p.validation_message}</p>}
                </li>
              ))}
            </ul>
          )}

          <div className="flex flex-wrap justify-end gap-2 border-t border-slate-200 pt-4 dark:border-slate-800">
            <Button type="button" variant="secondary" onClick={onClose}>
              Close
            </Button>
            {(data.status === "pending_review" || data.status === "approved") && (
              <Button type="button" variant="danger" onClick={() => setAction("reject")}>
                <RotateCcw className="h-4 w-4" /> {data.status === "approved" ? "Request retake" : "Reject / request retake"}
              </Button>
            )}
            {data.status === "pending_review" && (
              <Button type="button" onClick={() => setAction("approve")} disabled={!data.requirements_met}>
                <Check className="h-4 w-4" /> Approve face enrollment
              </Button>
            )}
          </div>

          <ConfirmDialog
            open={action !== null}
            title={action === "approve" ? "Approve face enrollment?" : "Request a retake?"}
            description={
              action === "approve"
                ? "The photos will be locked and used for attendance recognition once that feature is enabled."
                : "The student will see your reason and must upload new photos and submit again."
            }
            confirmLabel={action === "approve" ? "Approve" : "Request retake"}
            tone={action === "approve" ? "primary" : "danger"}
            reasonLabel={action === "reject" ? "Reason shown to the student" : undefined}
            reasonRequired={action === "reject"}
            loading={saving}
            onConfirm={confirm}
            onCancel={() => setAction(null)}
          />
        </>
      ) : null}
    </Modal>
  );
}
