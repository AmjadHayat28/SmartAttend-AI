import axios from "axios";
import { Pencil, Plus, UserCog } from "lucide-react";
import { useState } from "react";
import { AccountActions, AccountStatusBadge } from "../../components/accounts/AccountActions";
import { PageHeader } from "../../components/layout/PageHeader";
import { Button } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";
import { ConfirmDialog } from "../../components/ui/ConfirmDialog";
import { DataTable, type Column } from "../../components/ui/DataTable";
import { Alert, Badge } from "../../components/ui/Feedback";
import { Input, Select } from "../../components/ui/FormField";
import { FilterSelect, ListToolbar, SearchBox, STATUS_OPTIONS } from "../../components/ui/ListToolbar";
import { Modal } from "../../components/ui/Modal";
import { useToast } from "../../context/ToastContext";
import { usePagedList } from "../../hooks/usePagedList";
import { useStructure } from "../../hooks/useStructure";
import { getErrorMessage } from "../../services/api";
import { hodApi } from "../../services/managementService";
import type { Hod } from "../../types/api";

const EMPTY = { full_name: "", email: "", password: "", employee_id: "", department_id: "", phone: "", appointed_on: "" };

function isHandOverConflict(err: unknown) {
  return axios.isAxiosError(err) && err.response?.status === 409 && String(err.response.data?.detail).includes("already has a HOD");
}

export function HodsPage() {
  const toast = useToast();
  const { departments } = useStructure();
  const list = usePagedList(hodApi.list);
  const [editing, setEditing] = useState<Hod | "new" | null>(null);
  const [form, setForm] = useState(EMPTY);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [handOver, setHandOver] = useState<string | null>(null);

  function open(hod: Hod | "new") {
    setError(null);
    setEditing(hod);
    setForm(
      hod === "new"
        ? EMPTY
        : { full_name: hod.full_name, email: hod.email, password: "", employee_id: hod.employee_id, department_id: String(hod.department_id), phone: hod.phone ?? "", appointed_on: hod.appointed_on ?? "" },
    );
  }

  async function save(replace_existing = false) {
    if (!editing) return;
    setSaving(true);
    setError(null);
    const common = {
      full_name: form.full_name,
      email: form.email,
      employee_id: form.employee_id,
      phone: form.phone || null,
      appointed_on: form.appointed_on || null,
      replace_existing,
    };
    try {
      if (editing === "new") {
        await hodApi.create({ ...common, password: form.password, department_id: Number(form.department_id) });
        toast.success(`${form.full_name.trim()} is now HOD.`);
      } else {
        const moving = Number(form.department_id) !== editing.department_id || !editing.is_current;
        await hodApi.update(editing.id, { ...common, ...(moving ? { department_id: Number(form.department_id) } : {}) });
        toast.success("HOD updated.");
      }
      setHandOver(null);
      setEditing(null);
      list.reload();
    } catch (err) {
      if (isHandOverConflict(err) && !replace_existing) setHandOver(getErrorMessage(err));
      else {
        setHandOver(null);
        setError(getErrorMessage(err));
      }
    } finally {
      setSaving(false);
    }
  }

  const columns: Column<Hod>[] = [
    {
      header: "HOD",
      cell: (h) => (
        <div>
          <p className="font-medium text-slate-900 dark:text-white">{h.full_name}</p>
          <p className="text-xs text-slate-500">{h.email}</p>
        </div>
      ),
    },
    { header: "Employee ID", cell: (h) => <span className="font-mono text-xs">{h.employee_id}</span> },
    { header: "Department", cell: (h) => <span title={h.department_name}>{h.department_code}</span> },
    { header: "Post", cell: (h) => (h.is_current ? <Badge tone="blue">Current</Badge> : <Badge>Former</Badge>) },
    { header: "Status", cell: (h) => <AccountStatusBadge status={h.status} /> },
    {
      header: "Actions",
      className: "text-right",
      cell: (h) => (
        <div className="flex justify-end gap-1.5">
          <Button size="sm" variant="ghost" onClick={() => open(h)} aria-label={`Edit ${h.full_name}`}>
            <Pencil className="h-4 w-4" />
          </Button>
          <AccountActions account={h} onChanged={list.reload} allowReactivate={h.is_current} />
        </div>
      ),
    },
  ];

  const isNew = editing === "new";
  const valid = form.full_name.trim().length >= 2 && form.email.includes("@") && form.employee_id.trim().length >= 2 && !!form.department_id && (!isNew || form.password.length >= 8);

  return (
    <>
      <PageHeader
        title="Heads of Department"
        description="Each department has exactly one current HOD. Appointing a new one hands over the post."
        actions={
          <Button onClick={() => open("new")}>
            <Plus className="h-4 w-4" /> New HOD
          </Button>
        }
      />
      <Card>
        <ListToolbar>
          <SearchBox value={list.search} onChange={list.setSearch} placeholder="Search name, email or ID…" />
          <FilterSelect label="Department" value={list.filters.department_id ?? ""} onChange={(v) => list.setFilter("department_id", v)} options={departments.map((d) => ({ value: d.id, label: d.code }))} />
          <FilterSelect label="Status" value={list.filters.status ?? ""} onChange={(v) => list.setFilter("status", v)} options={STATUS_OPTIONS.filter((o) => o.value !== "pending" && o.value !== "rejected")} />
          <FilterSelect label="Post" value={list.filters.is_current ?? ""} onChange={(v) => list.setFilter("is_current", v)} options={[{ value: "true", label: "Current" }, { value: "false", label: "Former" }]} />
        </ListToolbar>
        <DataTable columns={columns} data={list.data} loading={list.loading} error={list.error} onRetry={list.reload} onPageChange={list.setPage} rowKey={(h) => h.id} empty={{ icon: UserCog, title: "No HODs found" }} rowClassName={(h) => (h.is_current ? undefined : "opacity-70")} />
      </Card>

      <Modal open={editing !== null} title={isNew ? "Appoint HOD" : "Edit HOD"} onClose={() => setEditing(null)} onSubmit={() => save(false)} submitting={saving} submitDisabled={!valid} size="lg">
        {error && <Alert>{error}</Alert>}
        <div className="grid gap-4 sm:grid-cols-2">
          <Input label="Full name" name="hod-name" value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} />
          <Input label="Email" name="hod-email" type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          <Input label="Employee ID" name="hod-emp" value={form.employee_id} onChange={(e) => setForm({ ...form, employee_id: e.target.value.toUpperCase() })} />
          <Select label="Department" name="hod-dept" value={form.department_id} onChange={(e) => setForm({ ...form, department_id: e.target.value })} placeholder="Select department" options={departments.map((d) => ({ value: d.id, label: `${d.code} — ${d.name}` }))} />
          {isNew && <Input label="Initial password" name="hod-password" type="password" autoComplete="new-password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} hint="8+ characters with upper-case, lower-case and a digit" />}
          <Input label="Phone (optional)" name="hod-phone" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} />
          <Input label="Appointed on (optional)" name="hod-appointed" type="date" value={form.appointed_on} onChange={(e) => setForm({ ...form, appointed_on: e.target.value })} />
        </div>
        {!isNew && editing && !editing.is_current && <Alert tone="info">This is a former HOD. Saving with a department reinstates them as that department's HOD.</Alert>}
      </Modal>

      <ConfirmDialog
        open={!!handOver}
        title="Replace the current HOD?"
        description={
          <>
            <p>{handOver}</p>
            <p className="mt-2">The current HOD will lose the post and their account will be suspended immediately.</p>
          </>
        }
        confirmLabel="Replace HOD"
        tone="danger"
        loading={saving}
        onConfirm={() => save(true)}
        onCancel={() => setHandOver(null)}
      />
    </>
  );
}
