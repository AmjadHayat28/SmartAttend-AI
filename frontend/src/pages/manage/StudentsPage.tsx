import { GraduationCap, Pencil, Plus } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";
import { AccountActions, AccountStatusBadge } from "../../components/accounts/AccountActions";
import { FaceStatusBadge } from "../../components/face/FaceStatusBadge";
import { PlacementFilters, PlacementSelects } from "../../components/academics/PlacementSelects";
import { PageHeader } from "../../components/layout/PageHeader";
import { Button } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";
import { DataTable, type Column } from "../../components/ui/DataTable";
import { Alert } from "../../components/ui/Feedback";
import { Input } from "../../components/ui/FormField";
import { FilterSelect, ListToolbar, SearchBox, STATUS_OPTIONS } from "../../components/ui/ListToolbar";
import { Modal } from "../../components/ui/Modal";
import { useToast } from "../../context/ToastContext";
import { usePagedList } from "../../hooks/usePagedList";
import { useRole } from "../../hooks/useRole";
import { EMPTY_PLACEMENT, useStructure, type Placement } from "../../hooks/useStructure";
import { getErrorMessage } from "../../services/api";
import { studentApi } from "../../services/managementService";
import type { Student } from "../../types/api";

const EMPTY = { full_name: "", email: "", password: "", registration_no: "" };

export function StudentsPage() {
  const { isAdmin } = useRole();
  const toast = useToast();
  const structure = useStructure();
  const [params] = useSearchParams();
  const list = usePagedList(studentApi.list, { initialFilters: params.get("status") ? { status: params.get("status")! } : {} });
  const [editing, setEditing] = useState<Student | "new" | null>(null);
  const [form, setForm] = useState(EMPTY);
  const [placement, setPlacement] = useState<Placement>(EMPTY_PLACEMENT);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const f = list.filters;
  const filterPlacement: Placement = { department_id: f.department_id ?? "", batch_id: f.batch_id ?? "", semester_id: f.semester_id ?? "", section_id: f.section_id ?? "" };

  function open(s: Student | "new") {
    setError(null);
    setEditing(s);
    if (s === "new") {
      setForm(EMPTY);
      setPlacement(EMPTY_PLACEMENT);
    } else {
      setForm({ full_name: s.full_name, email: s.email, password: "", registration_no: s.registration_no });
      setPlacement({ department_id: String(s.department_id), batch_id: String(s.batch_id), semester_id: String(s.semester_id), section_id: String(s.section_id) });
    }
  }

  async function save() {
    if (!editing) return;
    setSaving(true);
    setError(null);
    const academic = { batch_id: Number(placement.batch_id), semester_id: Number(placement.semester_id), section_id: Number(placement.section_id) };
    const body = { full_name: form.full_name, email: form.email, registration_no: form.registration_no };
    try {
      if (editing === "new") {
        await studentApi.create({ ...body, ...academic, password: form.password, department_id: isAdmin ? Number(placement.department_id) : undefined });
        toast.success(`Student ${form.registration_no.trim().toUpperCase()} created.`);
      } else {
        const placementChanged =
          academic.section_id !== editing.section_id || academic.semester_id !== editing.semester_id || academic.batch_id !== editing.batch_id || Number(placement.department_id) !== editing.department_id;
        const deptChanged = isAdmin && Number(placement.department_id) !== editing.department_id;
        await studentApi.update(editing.id, { ...body, ...(placementChanged ? academic : {}), ...(deptChanged ? { department_id: Number(placement.department_id) } : {}) });
        toast.success("Student updated.");
      }
      setEditing(null);
      list.reload();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  const columns: Column<Student>[] = [
    { header: "Reg. no.", cell: (s) => <span className="font-mono text-xs font-semibold">{s.registration_no}</span>, className: "whitespace-nowrap" },
    {
      header: "Student",
      cell: (s) => (
        <div>
          <p className="font-medium text-slate-900 dark:text-white">{s.full_name}</p>
          <p className="text-xs text-slate-500">{s.email}</p>
        </div>
      ),
    },
    { header: "Class", cell: (s) => `${isAdmin ? `${s.department_code} · ` : ""}${s.batch_name} · ${s.semester_name} · ${s.section_name}`, className: "whitespace-nowrap" },
    { header: "Courses", cell: (s) => s.enrollment_count, className: "tabular-nums" },
    { header: "Account", cell: (s) => <AccountStatusBadge status={s.status} /> },
    { header: "Face", cell: (s) => <FaceStatusBadge status={s.face_enrollment_status} /> },
    {
      header: "Actions",
      className: "text-right",
      cell: (s) => (
        <div className="flex justify-end gap-1.5">
          <Button size="sm" variant="ghost" onClick={() => open(s)} aria-label={`Edit ${s.full_name}`}>
            <Pencil className="h-4 w-4" />
          </Button>
          <AccountActions account={s} onChanged={list.reload} />
        </div>
      ),
    },
  ];

  const isNew = editing === "new";
  const valid = form.full_name.trim().length >= 2 && form.email.includes("@") && form.registration_no.trim().length >= 3 && !!placement.section_id && (!isNew || form.password.length >= 8);

  return (
    <>
      <PageHeader
        title="Students"
        description="Approve registrations, manage accounts and adjust academic placement."
        actions={
          <Button onClick={() => open("new")}>
            <Plus className="h-4 w-4" /> New student
          </Button>
        }
      />
      <Card>
        <ListToolbar>
          <SearchBox value={list.search} onChange={list.setSearch} placeholder="Search name, reg. no. or email…" />
          <FilterSelect label="Status" value={f.status ?? ""} onChange={(v) => list.setFilter("status", v)} options={STATUS_OPTIONS} />
          <PlacementFilters departments={structure.departments} value={filterPlacement} onChange={(p) => list.setFilters((x) => ({ ...x, ...p }))} hideDepartment={!isAdmin} />
        </ListToolbar>
        <DataTable
          columns={columns}
          data={list.data}
          loading={list.loading}
          error={list.error}
          onRetry={list.reload}
          onPageChange={list.setPage}
          rowKey={(s) => s.id}
          empty={{ icon: GraduationCap, title: "No students found", description: "Students appear here after they register or are created by an administrator." }}
        />
      </Card>

      <Modal open={editing !== null} title={isNew ? "New student" : "Edit student"} description={isNew ? "Accounts created here are active immediately." : undefined} onClose={() => setEditing(null)} onSubmit={save} submitting={saving} submitDisabled={!valid} size="lg">
        {error && <Alert>{error}</Alert>}
        <div className="grid gap-4 sm:grid-cols-2">
          <Input label="Full name" name="s-name" value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} />
          <Input label="Registration no." name="s-reg" value={form.registration_no} onChange={(e) => setForm({ ...form, registration_no: e.target.value.toUpperCase() })} placeholder="F23CSE01" />
          <Input label="Email" name="s-email" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          {isNew && <Input label="Initial password" name="s-password" type="password" autoComplete="new-password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} hint="8+ characters with upper-case, lower-case and a digit" />}
        </div>
        <div>
          <h3 className="mb-3 text-sm font-semibold text-slate-900 dark:text-white">Academic placement</h3>
          <PlacementSelects departments={structure.departments} value={placement} onChange={setPlacement} hideDepartment={!isAdmin} idPrefix="s" />
          {!isNew && <p className="mt-2 text-xs text-slate-500">Changing section within the same semester moves the student's course enrollments too. Moving to a new semester closes the old semester's enrollments.</p>}
        </div>
      </Modal>
    </>
  );
}
