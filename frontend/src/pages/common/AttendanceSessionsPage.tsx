import { ClipboardCheck, Eye, PencilLine, Plus } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { SessionStatusBadge } from "../../components/attendance/AttendanceParts";
import { PageHeader } from "../../components/layout/PageHeader";
import { Button } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";
import { DataTable, type Column } from "../../components/ui/DataTable";
import { FilterSelect, ListToolbar, SearchBox } from "../../components/ui/ListToolbar";
import { usePagedList } from "../../hooks/usePagedList";
import { attendanceApi, formatSessionDate } from "../../services/attendanceService";
import type { SessionListItem } from "../../types/attendance";
import { STATUS_META } from "../../types/attendance";
import { formatPercent } from "../../utils/format";

const STATUS_OPTIONS = [
  { value: "finalized", label: "Finalized" },
  { value: "draft", label: "Draft" },
];

const dateInput = "h-9 rounded-lg border border-slate-300 bg-white px-2 text-sm dark:border-slate-700 dark:bg-slate-950";

/**
 * The teacher's own attendance history (Resume drafts / View finalized sessions).
 * Attendance sessions are teacher-only: HODs and the super admin have no access (API: 403).
 */
export function AttendanceSessionsPage() {
  const navigate = useNavigate();
  const list = usePagedList(attendanceApi.list);
  const f = list.filters;
  // The API already excludes cancelled sessions; this guard keeps them out even if one slips through.
  const data = list.data && { ...list.data, items: list.data.items.filter((s) => s.status !== "cancelled") };

  const counts = (s: SessionListItem) => (
    <span className="whitespace-nowrap text-xs tabular-nums">
      <span className={STATUS_META.present.tone}>P {s.summary.present}</span> · <span className={STATUS_META.absent.tone}>A {s.summary.absent}</span> ·{" "}
      <span className={STATUS_META.late.tone}>L {s.summary.late}</span> · <span className={STATUS_META.excused.tone}>E {s.summary.excused}</span>
      {s.summary.unmarked > 0 && <span className="text-slate-500"> · {s.summary.unmarked} unmarked</span>}
    </span>
  );

  const columns: Column<SessionListItem>[] = [
    { header: "Date", cell: (s) => <span className="whitespace-nowrap">{formatSessionDate(s.session_date)}</span> },
    {
      header: "Course",
      cell: (s) => (
        <div>
          <p className="font-medium text-slate-900 dark:text-white">{s.course_title}</p>
          <p className="font-mono text-xs text-slate-500">{s.course_code}</p>
        </div>
      ),
    },
    { header: "Class", cell: (s) => `${s.batch_name} · ${s.semester_name} · ${s.section_name}`, className: "whitespace-nowrap" },
    { header: "Session", cell: (s) => s.session_number, className: "tabular-nums" },
    { header: "Attendance", cell: counts },
    { header: "%", cell: (s) => (s.status === "finalized" ? formatPercent(s.summary.percentage) : "—"), className: "tabular-nums" },
    { header: "Status", cell: (s) => <SessionStatusBadge status={s.status} /> },
    {
      header: "Actions",
      className: "text-right",
      cell: (s) => (
        <Button size="sm" variant={s.status === "draft" ? "primary" : "secondary"} onClick={() => navigate(`/teacher/attendance/${s.id}`)}>
          {s.status === "draft" ? <PencilLine className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
          {s.status === "draft" ? "Resume" : "View"}
        </Button>
      ),
    },
  ];

  return (
    <>
      <PageHeader
        title="Attendance History"
        description="Your attendance sessions. Drafts can be resumed; finalized sessions are read-only."
        actions={
          <Link to="/teacher/attendance/new" className="inline-flex h-10 items-center gap-2 rounded-lg bg-brand-700 px-4 text-sm font-medium text-white hover:bg-brand-800">
            <Plus className="h-4 w-4" /> Take Attendance
          </Link>
        }
      />
      <Card>
        <ListToolbar>
          <SearchBox value={list.search} onChange={list.setSearch} placeholder="Search course…" />
          <FilterSelect label="Status" value={f.status ?? ""} onChange={(v) => list.setFilter("status", v)} options={STATUS_OPTIONS} />
          <label className="flex items-center gap-1.5 text-xs text-slate-500">
            From <input type="date" value={f.date_from ?? ""} onChange={(e) => list.setFilter("date_from", e.target.value)} className={dateInput} aria-label="From date" />
          </label>
          <label className="flex items-center gap-1.5 text-xs text-slate-500">
            To <input type="date" value={f.date_to ?? ""} onChange={(e) => list.setFilter("date_to", e.target.value)} className={dateInput} aria-label="To date" />
          </label>
        </ListToolbar>
        <DataTable
          columns={columns}
          data={data}
          loading={list.loading}
          error={list.error}
          onRetry={list.reload}
          onPageChange={list.setPage}
          rowKey={(s) => s.id}
          empty={{ icon: ClipboardCheck, title: "No attendance sessions found", description: "Start one from Take Attendance." }}
        />
      </Card>
    </>
  );
}
