import { Building2, ShieldAlert, UserCog, UserMinus, Users } from "lucide-react";
import { Link } from "react-router-dom";
import { PageHeader } from "../../components/layout/PageHeader";
import { Card, CardHeader, StatCard } from "../../components/ui/Card";
import { Alert } from "../../components/ui/Feedback";
import { useAsync } from "../../hooks/useAsync";
import { dashboardService } from "../../services/dashboardService";
import { formatDateTime } from "../../utils/format";

/** "teacher.created" → "Teacher created" */
function describe(action: string) {
  const text = action.replace(/[._]/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** System administration overview: departments and staff only — no students or attendance. */
export function AdminDashboard() {
  const { data, loading, error } = useAsync(() => dashboardService.admin());
  const of = (active?: number, total?: number) => (data ? `${active} active of ${total}` : undefined);

  return (
    <>
      <PageHeader title="System Administration" description="Departments, HODs and teachers across the university" />
      {error && (
        <div className="mb-4">
          <Alert>{error}</Alert>
        </div>
      )}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <StatCard label="Departments" value={data?.departments ?? "—"} icon={Building2} hint={of(data?.active_departments, data?.departments)} loading={loading} />
        <StatCard label="HODs" value={data?.hods ?? "—"} icon={UserCog} tone="violet" hint={of(data?.active_hods, data?.hods)} loading={loading} />
        <StatCard label="Teachers" value={data?.teachers ?? "—"} icon={Users} tone="green" hint={of(data?.active_teachers, data?.teachers)} loading={loading} />
        <StatCard label="Suspended staff" value={data?.suspended_staff ?? "—"} icon={UserMinus} tone="rose" hint="HOD and teacher accounts" loading={loading} />
      </div>

      {data && data.departments_without_hod > 0 && (
        <div className="mt-4">
          <Alert tone="warning">
            {data.departments_without_hod} active department{data.departments_without_hod === 1 ? " has" : "s have"} no HOD.{" "}
            <Link to="/admin/hods" className="font-medium underline">Assign an HOD</Link>
          </Alert>
        </div>
      )}

      <Card className="mt-6">
        <CardHeader title="Recent administrative activity" description="Departments and HOD and teacher accounts." />
        {loading && !data ? (
          <p className="px-4 py-6 text-sm text-slate-500">Loading…</p>
        ) : !data?.recent_activity.length ? (
          <p className="flex items-center gap-2 px-4 py-6 text-sm text-slate-500">
            <ShieldAlert className="h-4 w-4" /> No administrative activity yet.
          </p>
        ) : (
          <ol className="divide-y divide-slate-200 dark:divide-slate-800">
            {data.recent_activity.map((a) => (
              <li key={a.id} className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5 px-4 py-3 text-sm">
                <span className="font-medium text-slate-900 dark:text-white">{describe(a.action)}</span>
                <span className="text-xs text-slate-500">
                  {a.actor_name ?? "System"} · {formatDateTime(a.timestamp)}
                </span>
              </li>
            ))}
          </ol>
        )}
      </Card>
    </>
  );
}
