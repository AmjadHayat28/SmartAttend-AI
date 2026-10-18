import { Pencil, Plus, Users } from "lucide-react";
import { useState } from "react";
import { AccountActions, AccountStatusBadge } from "../../components/accounts/AccountActions";
import { PageHeader } from "../../components/layout/PageHeader";
import { Button } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";
import { DataTable, type Column } from "../../components/ui/DataTable";
import { Alert } from "../../components/ui/Feedback";
import { Input, Select } from "../../components/ui/FormField";
import { FilterSelect, ListToolbar, SearchBox, STATUS_OPTIONS } from "../../components/ui/ListToolbar";
import { Modal } from "../../components/ui/Modal";
import { useToast } from "../../context/ToastContext";
import { usePagedList } from "../../hooks/usePagedList";
import { useRole } from "../../hooks/useRole";
import { useStructure } from "../../hooks/useStructure";
import { getErrorMessage } from "../../services/api";
import { teacherApi } from "../../services/managementService";
import type { Teacher } from "../../types/api";

const EMPTY = { full_name: "", email: "", password: "", employee_id: "", designation: "", phone: "", department_id: "" };

export function TeachersPage() {
  const { isAdmin } = useRole();
  const toast = useToast();
  const { departments } = useStructure();
  const list = usePagedList(teacherApi.list);
  const [editing, setEditing] = useState<Teacher | "new" | null>(null);
  const [form, setForm] = useState(EMPTY);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function open(t: Teacher | "new") {
    setError(null);
    setEditing(t);
    setForm(
      t === "new"
        ? EMPTY
        : { full_name: t.full_name, email: t.email, password: "", employee_id: t.employee_id, designation: t.designation ?? "", phone: t.phone ?? "", department_id: String(t.department_id) },
    );
  }

  async function save() {
    if (!editing) return;
    setSaving(true);
    setError(null);
    const body = { full_name: form.full_name, email: form.email, employee_id: form.employee_id, designation: form.designation.trim() || null, phone: form.phone || null };
    try {
      if (editing === "new") {
        await teacherApi.create({ ...body, password: form.password, department_id: isAdmin ? Number(form.department_id) || undefined : undefined });
        toast.success(`Teacher ${form.full_name.trim()} created.`);
      } else {
        const moved = isAdmin && Number(form.department_id) !== editing.department_id;
        await teacherApi.update(editing.id, { ...body, ...(moved ? { department_id: Number(form.department_id) } : {}) });
        toast.success("Teacher updated.");
      }
      setEditing(null);
      list.reload();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  const columns: Column<Teacher>[] = [
    {
      header: "Teacher",
      cell: (t) => (
        <div>
          <p className="font-medium text-slate-900 dark:text-white">{t.full_name}</p>
          <p className="text-xs text-slate-500">{t.email}</p>
        </div>
      ),
    },
    { header: "Employee ID", cell: (t) => <span className="font-mono text-xs">{t.employee_id}</span> },
    { header: "Designation", cell: (t) => t.designation ?? "—" },
    ...(isAdmin ? [{ header: "Department", cell: (t: Teacher) => t.department_code }] : []),
    { header: "Classes", cell: (t) => t.assignment_count, className: "tabular-nums" },
    { header: "Status", cell: (t) => <AccountStatusBadge status={t.status} /> },
    {
      header: "Actions",
      className: "text-right",
      cell: (t) => (
        <div className="flex justify-end gap-1.5">
          <Button size="sm" variant="ghost" onClick={() => open(t)} aria-label={`Edit ${t.full_name}`}>
            <Pencil className="h-4 w-4" />
          </Button>
          <AccountActions account={t} onChanged={list.reload} />
        </div>
      ),
    },
  ];

  const isNew = editing === "new";
  const valid = form.full_name.trim().length >= 2 && form.email.includes("@") && form.employee_id.trim().length >= 2 && (!isAdmin || !!form.department_id) && (!isNew || form.password.length >= 8);

  return (
    <>
      <PageHeader
        title="Teachers"
        description="Teacher accounts are created here; there is no public teacher registration."
        actions={
          <Button onClick={() => open("new")}>
            <Plus className="h-4 w-4" /> New teacher
          </Button>
        }
      />
      <Card>
        <ListToolbar>
          <SearchBox value={list.search} onChange={list.setSearch} placeholder="Search name, email or employee ID…" />
          {isAdmin && <FilterSelect label="Department" value={list.filters.department_id ?? ""} onChange={(v) => list.setFilter("department_id", v)} options={departments.map((d) => ({ value: d.id, label: d.code }))} />}
          <FilterSelect label="Status" value={list.filters.status ?? ""} onChange={(v) => list.setFilter("status", v)} options={STATUS_OPTIONS.filter((o) => o.value === "active" || o.value === "suspended")} />
        </ListToolbar>
        <DataTable columns={columns} data={list.data} loading={list.loading} error={list.error} onRetry={list.reload} onPageChange={list.setPage} rowKey={(t) => t.id} empty={{ icon: Users, title: "No teachers found" }} />
      </Card>

      <Modal open={editing !== null} title={isNew ? "New teacher" : "Edit teacher"} onClose={() => setEditing(null)} onSubmit={save} submitting={saving} submitDisabled={!valid} size="lg">
        {error && <Alert>{error}</Alert>}
        <div className="grid gap-4 sm:grid-cols-2">
          <Input label="Full name" name="t-name" value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} />
          <Input label="Email" name="t-email" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          <Input label="Employee ID" name="t-emp" value={form.employee_id} onChange={(e) => setForm({ ...form, employee_id: e.target.value.toUpperCase() })} />
          <Input label="Designation" name="t-designation" value={form.designation} onChange={(e) => setForm({ ...form, designation: e.target.value })} placeholder="Lecturer" />
          {isAdmin && (
            <Select label="Department" name="t-dept" value={form.department_id} onChange={(e) => setForm({ ...form, department_id: e.target.value })} placeholder="Select department" options={departments.map((d) => ({ value: d.id, label: `${d.code} — ${d.name}` }))} />
          )}
          <Input label="Phone (optional)" name="t-phone" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} />
          {isNew && <Input label="Initial password" name="t-password" type="password" autoComplete="new-password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} hint="8+ characters with upper-case, lower-case and a digit" />}
        </div>
        {!isNew && isAdmin && <p className="text-xs text-slate-500">Moving a teacher to another department requires their HOD to remove their class assignments first.</p>}
      </Modal>
    </>
  );
}
