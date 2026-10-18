import { BookOpen, Pencil, Plus } from "lucide-react";
import { useState } from "react";
import { PageHeader } from "../../components/layout/PageHeader";
import { ActiveBadge } from "../../components/ui/ActiveBadge";
import { Button } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";
import { DataTable, type Column } from "../../components/ui/DataTable";
import { Alert, Badge } from "../../components/ui/Feedback";
import { Checkbox, Input, Select } from "../../components/ui/FormField";
import { ACTIVE_OPTIONS, FilterSelect, ListToolbar, SearchBox } from "../../components/ui/ListToolbar";
import { Modal } from "../../components/ui/Modal";
import { useToast } from "../../context/ToastContext";
import { usePagedList } from "../../hooks/usePagedList";
import { useRole } from "../../hooks/useRole";
import { useStructure } from "../../hooks/useStructure";
import { getErrorMessage } from "../../services/api";
import { courseApi } from "../../services/managementService";
import type { Course } from "../../types/api";

const EMPTY = { code: "", title: "", credit_hours: "3", semester_number: "", is_lab: false, is_active: true, department_id: "" };

export function CoursesPage() {
  const { isAdmin } = useRole();
  const toast = useToast();
  const { departments } = useStructure();
  const list = usePagedList(courseApi.list);
  const [editing, setEditing] = useState<Course | "new" | null>(null);
  const [form, setForm] = useState(EMPTY);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function open(course: Course | "new") {
    setError(null);
    setEditing(course);
    setForm(
      course === "new"
        ? EMPTY
        : {
            code: course.code,
            title: course.title,
            credit_hours: String(course.credit_hours),
            semester_number: course.semester_number ? String(course.semester_number) : "",
            is_lab: course.is_lab,
            is_active: course.is_active,
            department_id: String(course.department_id),
          },
    );
  }

  async function save() {
    setSaving(true);
    setError(null);
    const body = {
      code: form.code,
      title: form.title,
      credit_hours: Number(form.credit_hours),
      semester_number: form.semester_number ? Number(form.semester_number) : null,
      is_lab: form.is_lab,
      is_active: form.is_active,
    };
    try {
      if (editing === "new") {
        const created = await courseApi.create({ ...body, department_id: isAdmin ? Number(form.department_id) || undefined : undefined });
        toast.success(`${created.code} created.`);
      } else if (editing) {
        await courseApi.update(editing.id, body);
        toast.success("Course updated.");
      }
      setEditing(null);
      list.reload();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  const columns: Column<Course>[] = [
    { header: "Code", cell: (c) => <span className="font-mono text-xs font-semibold">{c.code}</span>, className: "whitespace-nowrap" },
    {
      header: "Course",
      cell: (c) => (
        <span className="flex items-center gap-2 font-medium text-slate-900 dark:text-white">
          {c.title}
          {c.is_lab && <Badge tone="blue">Lab</Badge>}
        </span>
      ),
    },
    ...(isAdmin ? [{ header: "Department", cell: (c: Course) => c.department_code }] : []),
    { header: "Credits", cell: (c) => c.credit_hours, className: "tabular-nums" },
    { header: "Semester", cell: (c) => c.semester_number ?? "—", className: "tabular-nums" },
    { header: "Status", cell: (c) => <ActiveBadge active={c.is_active} /> },
    {
      header: "Actions",
      className: "text-right",
      cell: (c) => (
        <Button size="sm" variant="ghost" onClick={() => open(c)} aria-label={`Edit ${c.code}`}>
          <Pencil className="h-4 w-4" />
        </Button>
      ),
    },
  ];

  return (
    <>
      <PageHeader
        title="Courses"
        description="Course codes are unique within a department."
        actions={
          <Button onClick={() => open("new")}>
            <Plus className="h-4 w-4" /> New course
          </Button>
        }
      />
      <Card>
        <ListToolbar>
          <SearchBox value={list.search} onChange={list.setSearch} placeholder="Search code or title…" />
          {isAdmin && <FilterSelect label="Department" value={list.filters.department_id ?? ""} onChange={(v) => list.setFilter("department_id", v)} options={departments.map((d) => ({ value: d.id, label: d.code }))} />}
          <FilterSelect label="Status" value={list.filters.is_active ?? ""} onChange={(v) => list.setFilter("is_active", v)} options={ACTIVE_OPTIONS} />
        </ListToolbar>
        <DataTable columns={columns} data={list.data} loading={list.loading} error={list.error} onRetry={list.reload} onPageChange={list.setPage} rowKey={(c) => c.id} empty={{ icon: BookOpen, title: "No courses found" }} />
      </Card>

      <Modal
        open={editing !== null}
        title={editing === "new" ? "New course" : "Edit course"}
        onClose={() => setEditing(null)}
        onSubmit={save}
        submitting={saving}
        submitDisabled={form.code.trim().length < 2 || form.title.trim().length < 2 || (isAdmin && editing === "new" && !form.department_id)}
      >
        {error && <Alert>{error}</Alert>}
        {isAdmin && editing === "new" && (
          <Select label="Department" name="course-dept" value={form.department_id} onChange={(e) => setForm({ ...form, department_id: e.target.value })} placeholder="Select department" options={departments.map((d) => ({ value: d.id, label: `${d.code} — ${d.name}` }))} />
        )}
        <div className="grid gap-4 sm:grid-cols-[10rem_1fr]">
          <Input label="Code" name="course-code" value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value.toUpperCase() })} placeholder="COMP-02735" />
          <Input label="Course name" name="course-title" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} placeholder="Digital System Design" />
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <Input label="Credit hours" name="course-credits" type="number" min={0} max={10} value={form.credit_hours} onChange={(e) => setForm({ ...form, credit_hours: e.target.value })} />
          <Input label="Suggested semester (optional)" name="course-sem" type="number" min={1} max={12} value={form.semester_number} onChange={(e) => setForm({ ...form, semester_number: e.target.value })} />
        </div>
        <Checkbox name="course-lab" label="Lab course" checked={form.is_lab} onChange={(v) => setForm({ ...form, is_lab: v })} />
        <Checkbox name="course-active" label="Active" checked={form.is_active} onChange={(v) => setForm({ ...form, is_active: v })} hint="Inactive courses cannot receive new assignments or enrollments." />
      </Modal>
    </>
  );
}
