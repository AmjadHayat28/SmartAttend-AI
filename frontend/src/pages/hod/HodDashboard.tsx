import { BookOpen, CalendarCheck, GraduationCap, UserCheck, Users } from "lucide-react";
import { PendingApprovals } from "../../components/accounts/PendingApprovals";
import { PageHeader } from "../../components/layout/PageHeader";
import { StatCard } from "../../components/ui/Card";
import { Alert } from "../../components/ui/Feedback";
import { useAsync } from "../../hooks/useAsync";
import { dashboardService } from "../../services/dashboardService";
import { formatPercent } from "../../utils/format";

export function HodDashboard() {
  const { data, loading, error, reload } = useAsync(() => dashboardService.hod());

  return (
    <>
      <PageHeader title={data?.department_name ?? "Department"} description="Department overview" />
      {error && (
        <div className="mb-4">
          <Alert>{error}</Alert>
        </div>
      )}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-5">
        <StatCard label="Students" value={data?.students ?? "—"} icon={GraduationCap} loading={loading} />
        <StatCard label="Teachers" value={data?.teachers ?? "—"} icon={Users} tone="green" loading={loading} />
        <StatCard label="Subjects" value={data?.subjects ?? "—"} icon={BookOpen} tone="violet" loading={loading} />
        <StatCard label="Today's attendance" value={formatPercent(data?.today_attendance_pct)} icon={CalendarCheck} tone="green" loading={loading} />
        <StatCard label="Pending approvals" value={data?.pending_approvals ?? "—"} icon={UserCheck} tone="amber" loading={loading} />
      </div>
      <div className="mt-6">
        <PendingApprovals pageSize={5} onChanged={reload} />
      </div>
    </>
  );
}
