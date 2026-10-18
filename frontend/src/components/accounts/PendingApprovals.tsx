import { Check, UserCheck, X } from "lucide-react";
import { useState } from "react";
import { useToast } from "../../context/ToastContext";
import { useAsync } from "../../hooks/useAsync";
import { getErrorMessage } from "../../services/api";
import { accountService } from "../../services/dashboardService";
import type { PendingStudent } from "../../types/api";
import { formatDateTime } from "../../utils/format";
import { FaceStatusBadge } from "../face/FaceStatusBadge";
import { Button } from "../ui/Button";
import { Card, CardHeader } from "../ui/Card";
import { ConfirmDialog } from "../ui/ConfirmDialog";
import { EmptyState, ErrorState, Spinner } from "../ui/Feedback";
import { Pagination } from "../ui/Pagination";

type Decision = { student: PendingStudent; action: "active" | "rejected" };

/** Pending student registrations. The API scopes results to the HOD's department automatically. */
export function PendingApprovals({ pageSize = 10, onChanged }: { pageSize?: number; onChanged?: () => void }) {
  const toast = useToast();
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [decision, setDecision] = useState<Decision | null>(null);
  const [saving, setSaving] = useState(false);
  const { data, loading, error, reload } = useAsync(() => accountService.pendingStudents(page, pageSize), [page, pageSize]);

  const q = search.trim().toLowerCase();
  const rows = (data?.items ?? []).filter(
    (s) => !q || s.full_name.toLowerCase().includes(q) || s.registration_no.toLowerCase().includes(q) || s.email.toLowerCase().includes(q),
  );

  async function confirm(reason: string) {
    if (!decision) return;
    setSaving(true);
    try {
      await accountService.setStatus(decision.student.user_id, decision.action, reason || undefined);
      toast.success(`${decision.student.full_name} ${decision.action === "active" ? "approved" : "rejected"}.`);
      setDecision(null);
      // Step back a page if we just emptied the last one.
      if (data && data.items.length === 1 && page > 1) setPage(page - 1);
      else reload();
      onChanged?.();
    } catch (err) {
      toast.error(getErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card>
      <CardHeader
        title="Pending student approvals"
        description={data ? `${data.total} awaiting review` : undefined}
        action={
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search this page…"
            aria-label="Search pending students"
            className="h-9 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20 sm:w-60 dark:border-slate-700 dark:bg-slate-950"
          />
        }
      />
      {loading ? (
        <Spinner />
      ) : error ? (
        <ErrorState message={error} onRetry={reload} />
      ) : !rows.length ? (
        <EmptyState icon={UserCheck} title={q ? "No matches" : "All caught up"} description={q ? "Try a different search." : "There are no registrations waiting for approval."} />
      ) : (
        <div className="relative overflow-x-auto">
          <table className="min-w-full divide-y divide-slate-200 text-sm dark:divide-slate-800">
            <thead className="bg-slate-50 text-left text-xs font-semibold uppercase tracking-wide text-slate-500 dark:bg-slate-900/60 dark:text-slate-400">
              <tr>
                <th className="px-5 py-3">Student</th>
                <th className="px-5 py-3">Reg. no.</th>
                <th className="px-5 py-3">Class</th>
                <th className="px-5 py-3">Face photos</th>
                <th className="px-5 py-3">Registered</th>
                <th className="px-5 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-200 dark:divide-slate-800">
              {rows.map((s) => (
                <tr key={s.user_id} className="hover:bg-slate-50 dark:hover:bg-slate-800/40">
                  <td className="px-5 py-3">
                    <p className="font-medium text-slate-900 dark:text-white">{s.full_name}</p>
                    <p className="text-xs text-slate-500">{s.email}</p>
                  </td>
                  <td className="px-5 py-3 font-mono text-xs">{s.registration_no}</td>
                  <td className="whitespace-nowrap px-5 py-3">
                    {s.batch} · Sem {s.semester} · {s.section}
                  </td>
                  <td className="px-5 py-3">
                    <FaceStatusBadge status={s.face_enrollment_status} />
                  </td>
                  <td className="whitespace-nowrap px-5 py-3 text-slate-500">{formatDateTime(s.registered_at)}</td>
                  <td className="px-5 py-3">
                    <div className="flex justify-end gap-2">
                      <Button size="sm" onClick={() => setDecision({ student: s, action: "active" })}>
                        <Check className="h-4 w-4" /> Approve
                      </Button>
                      <Button size="sm" variant="secondary" onClick={() => setDecision({ student: s, action: "rejected" })}>
                        <X className="h-4 w-4" /> Reject
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data && <Pagination page={page} pageSize={pageSize} total={data.total} onPageChange={setPage} />}

      <ConfirmDialog
        open={!!decision}
        title={decision?.action === "active" ? "Approve registration?" : "Reject registration?"}
        description={
          decision && (
            <>
              <strong>{decision.student.full_name}</strong> ({decision.student.registration_no}){" "}
              {decision.action === "active" ? "will be able to sign in." : "will not be able to sign in."}
            </>
          )
        }
        confirmLabel={decision?.action === "active" ? "Approve" : "Reject"}
        tone={decision?.action === "active" ? "primary" : "danger"}
        reasonLabel={decision?.action === "rejected" ? "Reason for rejection" : undefined}
        reasonRequired={decision?.action === "rejected"}
        loading={saving}
        onConfirm={confirm}
        onCancel={() => setDecision(null)}
      />
    </Card>
  );
}
