import { CalendarRange, Pencil, Plus } from "lucide-react";
import { useState } from "react";
import { PageHeader } from "../../components/layout/PageHeader";
import { Button } from "../../components/ui/Button";
import { ActiveBadge } from "../../components/ui/ActiveBadge";
import { Card } from "../../components/ui/Card";
import { DataTable, type Column } from "../../components/ui/DataTable";
import { Alert } from "../../components/ui/Feedback";
import { Checkbox, Input, Select } from "../../components/ui/FormField";
import { ACTIVE_OPTIONS, FilterSelect, ListToolbar, SearchBox } from "../../components/ui/ListToolbar";
import { Modal } from "../../components/ui/Modal";
import { useToast } from "../../context/ToastContext";
import { usePagedList } from "../../hooks/usePagedList";
import { useRole } from "../../hooks/useRole";
import { useStructure } from "../../hooks/useStructure";
import { getErrorMessage } from "../../services/api";
import { batchApi } from "../../services/managementService";
import type { Batch } from "../../types/api";

const EMPTY = { name: "", start_year: String(new Date().getFullYear()), end_year: "", department_id: "", is_active: true };

export function BatchesPage() {
  const { isAdmin } = useRole();
  const toast = useToast();
  const { departments } = useStructure();
  const list = usePagedList(batchApi.list);
  const [editing, setEditing] = useState<Batch | "new" | null>(null);
  const [form, setForm] = useState(EMPTY);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function open(batch: Batch | "new") {
    setError(null);
    setEditing(batch);
    setForm(
      batch === "new"
        ? EMPTY
        : { name: batch.name, start_year: String(batch.start_year), end_year: batch.end_year ? String(batch.end_year) : "", department_id: String(batch.department_id), is_active: batch.is_active },
    );
  }

  async function save() {
    setSaving(true);
    setError(null);
    const body = {
      name: form.name,
      start_year: Number(form.start_year),
      end_year: form.end_year ? Number(form.end_year) : null,
      is_active: form.is_active,
    };
    try {
      if (editing === "new") {
        await batchApi.create({ ...body, department_id: isAdmin ? Number(form.department_id) || undefined : undefined });
        toast.success(`Batch "${form.name.trim()}" created.`);
      } else if (editing) {
        await batchApi.update(editing.id, body);
        toast.success("Batch updated.");
      }
      setEditing(null);
      list.reload();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  const columns: Column<Batch>[] = [
    { header: "Batch", cell: (b) => <span className="font-medium text-slate-900 dark:text-white">{b.name}</span> },
    ...(isAdmin ? [{ header: "Department", cell: (b: Batch) => b.department_code }] : []),
    { header: "Years", cell: (b) => `${b.start_year} – ${b.end_year ?? "…"}`, className: "whitespace-nowrap" },
    { header: "Semesters", cell: (b) => b.semester_count, className: "tabular-nums" },
    { header: "Students", cell: (b) => b.student_count, className: "tabular-nums" },
    { header: "Status", cell: (b) => <ActiveBadge active={b.is_active} /> },
    {
      header: "Actions",
      className: "text-right",
      cell: (b) => (
        <Button size="sm" variant="ghost" onClick={() => open(b)} aria-label={`Edit ${b.name}`}>
          <Pencil className="h-4 w-4" />
        </Button>
      ),
    },
  ];

  return (
    <>
      <PageHeader
        title="Batches"
        description="Intake cohorts, e.g. Fall 2023. Batch names are unique within a department."
        actions={
          <Button onClick={() => open("new")}>
            <Plus className="h-4 w-4" /> New batch
          </Button>
        }
      />
      <Card>
        <ListToolbar>
          <SearchBox value={list.search} onChange={list.setSearch} placeholder="Search batches…" />
          {isAdmin && (
            <FilterSelect label="Department" value={list.filters.department_id ?? ""} onChange={(v) => list.setFilter("department_id", v)} options={departments.map((d) => ({ value: d.id, label: d.code }))} />
          )}
          <FilterSelect label="Status" value={list.filters.is_active ?? ""} onChange={(v) => list.setFilter("is_active", v)} options={ACTIVE_OPTIONS} />
        </ListToolbar>
        <DataTable
          columns={columns}
          data={list.data}
          loading={list.loading}
          error={list.error}
          onRetry={list.reload}
          onPageChange={list.setPage}
          rowKey={(b) => b.id}
          empty={{ icon: CalendarRange, title: "No batches found", description: "Create a batch to start building semesters and sections." }}
        />
      </Card>

      <Modal open={editing !== null} title={editing === "new" ? "New batch" : "Edit batch"} onClose={() => setEditing(null)} onSubmit={save} submitting={saving} submitDisabled={form.name.trim().length < 2 || !form.start_year || (isAdmin && editing === "new" && !form.department_id)}>
        {error && <Alert>{error}</Alert>}
        {isAdmin && editing === "new" && (
          <Select label="Department" name="batch-dept" value={form.department_id} onChange={(e) => setForm({ ...form, department_id: e.target.value })} placeholder="Select department" options={departments.map((d) => ({ value: d.id, label: `${d.code} — ${d.name}` }))} />
        )}
        <Input label="Name" name="batch-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Fall 2023" />
        <div className="grid gap-4 sm:grid-cols-2">
          <Input label="Start year" name="batch-start" type="number" min={1990} max={2100} value={form.start_year} onChange={(e) => setForm({ ...form, start_year: e.target.value })} />
          <Input label="End year (optional)" name="batch-end" type="number" min={1990} max={2100} value={form.end_year} onChange={(e) => setForm({ ...form, end_year: e.target.value })} />
        </div>
        <Checkbox name="batch-active" label="Active" checked={form.is_active} onChange={(v) => setForm({ ...form, is_active: v })} hint="Inactive batches stay in history but are hidden from new registrations." />
      </Modal>
    </>
  );
}
