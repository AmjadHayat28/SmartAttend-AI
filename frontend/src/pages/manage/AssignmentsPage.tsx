import { ClipboardList, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { PlacementFilters, PlacementSelects } from "../../components/academics/PlacementSelects";
import { PageHeader } from "../../components/layout/PageHeader";
import { Button } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";
import { ConfirmDialog } from "../../components/ui/ConfirmDialog";
import { DataTable, type Column } from "../../components/ui/DataTable";
import { Alert, Badge } from "../../components/ui/Feedback";
import { Select } from "../../components/ui/FormField";
import { ListToolbar, SearchBox } from "../../components/ui/ListToolbar";
import { Modal } from "../../components/ui/Modal";
import { useToast } from "../../context/ToastContext";
import { useAsync } from "../../hooks/useAsync";
import { usePagedList } from "../../hooks/usePagedList";
import { EMPTY_PLACEMENT, useStructure, usePlacementNodes, type Placement } from "../../hooks/useStructure";
import { getErrorMessage } from "../../services/api";
import { assignmentApi, courseApi, teacherApi } from "../../services/managementService";
import type { Assignment } from "../../types/api";
import { formatDateTime } from "../../utils/format";

export function AssignmentsPage() {
  const toast = useToast();
  const structure = useStructure();
  const list = usePagedList(assignmentApi.list);
  const [creating, setCreating] = useState(false);
  const [placement, setPlacement] = useState<Placement>(EMPTY_PLACEMENT);
  const [teacherId, setTeacherId] = useState("");
  const [courseId, setCourseId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [removing, setRemoving] = useState<Assignment | null>(null);

  const nodes = usePlacementNodes(structure.departments, placement);
  const deptId = placement.department_id;
  // Teachers and courses offered for the chosen department only.
  const options = useAsync(
    () =>
      deptId
        ? Promise.all([
            teacherApi.list({ department_id: deptId, status: "active", page_size: 200 }),
            courseApi.list({ department_id: deptId, is_active: true, page_size: 200 }),
          ])
        : Promise.resolve(null),
    [deptId],
  );
  const [teachers, courses] = options.data ?? [null, null];
  const semesterNo = nodes.semester?.number;
  const sortedCourses = [...(courses?.items ?? [])].sort((a, b) => Number(b.semester_number === semesterNo) - Number(a.semester_number === semesterNo));

  const f = list.filters;
  const filterPlacement: Placement = { department_id: f.department_id ?? "", batch_id: f.batch_id ?? "", semester_id: f.semester_id ?? "", section_id: f.section_id ?? "" };

  function openCreate() {
    setError(null);
    setPlacement(EMPTY_PLACEMENT);
    setTeacherId("");
    setCourseId("");
    setCreating(true);
  }

  async function create() {
    setSaving(true);
    setError(null);
    try {
      const a = await assignmentApi.create({ teacher_id: Number(teacherId), course_id: Number(courseId), section_id: Number(placement.section_id) });
      toast.success(`${a.teacher_name} assigned to ${a.course_code} (${a.batch_name} · Sem ${a.semester_number} · ${a.section_name}).`);
      setCreating(false);
      list.reload();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  async function remove() {
    if (!removing) return;
    setSaving(true);
    try {
      await assignmentApi.remove(removing.id);
      toast.success(`Removed ${removing.teacher_name} from ${removing.course_code}.`);
      setRemoving(null);
      list.reload();
    } catch (err) {
      toast.error(getErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  const columns: Column<Assignment>[] = [
    {
      header: "Teacher",
      cell: (a) => (
        <div>
          <p className="font-medium text-slate-900 dark:text-white">{a.teacher_name}</p>
          <p className="font-mono text-xs text-slate-500">{a.employee_id}</p>
        </div>
      ),
    },
    {
      header: "Course",
      cell: (a) => (
        <div>
          <p className="flex items-center gap-2">
            <span className="font-mono text-xs font-semibold">{a.course_code}</span>
            {a.is_lab && <Badge tone="blue">Lab</Badge>}
          </p>
          <p className="text-slate-600 dark:text-slate-300">{a.course_title}</p>
        </div>
      ),
    },
    { header: "Class", cell: (a) => `${a.batch_name} · Sem ${a.semester_number} · ${a.section_name}`, className: "whitespace-nowrap" },
    { header: "Assigned", cell: (a) => formatDateTime(a.assigned_at), className: "whitespace-nowrap text-slate-500" },
    {
      header: "Actions",
      className: "text-right",
      cell: (a) => (
        <Button size="sm" variant="ghost" onClick={() => setRemoving(a)} aria-label={`Remove ${a.teacher_name} from ${a.course_code}`}>
          <Trash2 className="h-4 w-4 text-red-600" />
        </Button>
      ),
    },
  ];

  return (
    <>
      <PageHeader
        title="Teacher assignments"
        description="Teacher + course + section. Teachers only see the classes assigned here."
        actions={
          <Button onClick={openCreate}>
            <Plus className="h-4 w-4" /> Assign teacher
          </Button>
        }
      />
      <Card>
        <ListToolbar>
          <SearchBox value={list.search} onChange={list.setSearch} placeholder="Search teacher or course…" />
          <PlacementFilters departments={structure.departments} value={filterPlacement} onChange={(p) => list.setFilters((x) => ({ ...x, ...p }))} hideDepartment />
        </ListToolbar>
        <DataTable columns={columns} data={list.data} loading={list.loading} error={list.error} onRetry={list.reload} onPageChange={list.setPage} rowKey={(a) => a.id} empty={{ icon: ClipboardList, title: "No assignments found", description: "Assign teachers to courses and sections to build their timetable." }} />
      </Card>

      <Modal open={creating} title="Assign teacher to a class" onClose={() => setCreating(false)} onSubmit={create} submitLabel="Assign" submitting={saving} submitDisabled={!teacherId || !courseId || !placement.section_id} size="lg">
        {error && <Alert>{error}</Alert>}
        <PlacementSelects departments={structure.departments} value={placement} onChange={(p) => {
          if (p.department_id !== placement.department_id) {
            setTeacherId("");
            setCourseId("");
          }
          setPlacement(p);
        }} hideDepartment idPrefix="asg" />
        {options.error && <Alert>{options.error}</Alert>}
        <div className="grid gap-4 sm:grid-cols-2">
          <Select label="Teacher" name="asg-teacher" value={teacherId} onChange={(e) => setTeacherId(e.target.value)} placeholder={deptId ? "Select teacher" : "Choose a department first"} disabled={!deptId || options.loading} options={(teachers?.items ?? []).map((t) => ({ value: t.id, label: `${t.full_name} (${t.employee_id})` }))} />
          <Select
            label="Course"
            name="asg-course"
            value={courseId}
            onChange={(e) => setCourseId(e.target.value)}
            placeholder={deptId ? "Select course" : "Choose a department first"}
            disabled={!deptId || options.loading}
            options={sortedCourses.map((c) => ({ value: c.id, label: `${c.code} — ${c.title}${semesterNo && c.semester_number === semesterNo ? " ★" : ""}` }))}
          />
        </div>
        {semesterNo && <p className="text-xs text-slate-500">★ marks courses suggested for semester {semesterNo}.</p>}
      </Modal>

      <ConfirmDialog
        open={!!removing}
        title="Remove assignment?"
        description={removing && `${removing.teacher_name} will no longer see ${removing.course_code} for ${removing.batch_name} · Sem ${removing.semester_number} · ${removing.section_name}. Past attendance is kept.`}
        confirmLabel="Remove"
        tone="danger"
        loading={saving}
        onConfirm={remove}
        onCancel={() => setRemoving(null)}
      />
    </>
  );
}
