import { CalendarDays, Pencil, Plus } from "lucide-react";
import { useState } from "react";
import { PlacementFilters, PlacementSelects } from "../../components/academics/PlacementSelects";
import { PageHeader } from "../../components/layout/PageHeader";
import { ActiveBadge } from "../../components/ui/ActiveBadge";
import { Button } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";
import { DataTable, type Column } from "../../components/ui/DataTable";
import { Alert, Badge } from "../../components/ui/Feedback";
import { Checkbox, Input } from "../../components/ui/FormField";
import { ACTIVE_OPTIONS, FilterSelect, ListToolbar, SearchBox } from "../../components/ui/ListToolbar";
import { Modal } from "../../components/ui/Modal";
import { useToast } from "../../context/ToastContext";
import { usePagedList } from "../../hooks/usePagedList";
import { useRole } from "../../hooks/useRole";
import { EMPTY_PLACEMENT, useStructure, type Placement } from "../../hooks/useStructure";
import { getErrorMessage } from "../../services/api";
import { semesterApi } from "../../services/managementService";
import type { Semester } from "../../types/api";

const EMPTY = { number: "", name: "", start_date: "", end_date: "", is_current: false, is_active: true };

export function SemestersPage() {
  const { isAdmin } = useRole();
  const toast = useToast();
  const structure = useStructure();
  const list = usePagedList(semesterApi.list);
  const [editing, setEditing] = useState<Semester | "new" | null>(null);
  const [placement, setPlacement] = useState<Placement>(EMPTY_PLACEMENT);
  const [form, setForm] = useState(EMPTY);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const filterPlacement = { ...EMPTY_PLACEMENT, department_id: list.filters.department_id ?? "", batch_id: list.filters.batch_id ?? "" };

  function open(sem: Semester | "new") {
    setError(null);
    setEditing(sem);
    setPlacement(EMPTY_PLACEMENT);
    setForm(
      sem === "new"
        ? EMPTY
        : { number: String(sem.number), name: sem.name, start_date: sem.start_date ?? "", end_date: sem.end_date ?? "", is_current: sem.is_current, is_active: sem.is_active },
    );
  }

  async function save() {
    setSaving(true);
    setError(null);
    const body = {
      number: Number(form.number),
      name: form.name.trim() || null,
      start_date: form.start_date || null,
      end_date: form.end_date || null,
      is_current: form.is_current,
      is_active: form.is_active,
    };
    try {
      if (editing === "new") {
        const created = await semesterApi.create({ ...body, batch_id: Number(placement.batch_id) });
        toast.success(`${created.name} created.`);
      } else if (editing) {
        await semesterApi.update(editing.id, { ...body, name: body.name ?? editing.name });
        toast.success("Semester updated.");
      }
      setEditing(null);
      list.reload();
      structure.reload();
    } catch (err) {
      setError(getErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  const columns: Column<Semester>[] = [
    {
      header: "Semester",
      cell: (s) => (
        <div>
          <p className="font-medium text-slate-900 dark:text-white">{s.name}</p>
          <p className="text-xs text-slate-500">No. {s.number}</p>
        </div>
      ),
    },
    { header: "Batch", cell: (s) => (isAdmin ? `${s.department_code} · ${s.batch_name}` : s.batch_name) },
    { header: "Dates", cell: (s) => (s.start_date ? `${s.start_date} → ${s.end_date ?? "…"}` : "—"), className: "whitespace-nowrap text-slate-500" },
    { header: "Sections", cell: (s) => s.section_count, className: "tabular-nums" },
    {
      header: "Status",
      cell: (s) => (
        <div className="flex gap-1.5">
          <ActiveBadge active={s.is_active} />
          {s.is_current && <Badge tone="blue">Current</Badge>}
        </div>
      ),
    },
    {
      header: "Actions",
      className: "text-right",
      cell: (s) => (
        <Button size="sm" variant="ghost" onClick={() => open(s)} aria-label={`Edit ${s.name}`}>
          <Pencil className="h-4 w-4" />
        </Button>
      ),
    },
  ];

  return (
    <>
      <PageHeader
        title="Semesters"
        description="Each batch progresses through numbered semesters; sections and enrollments belong to a semester."
        actions={
          <Button onClick={() => open("new")}>
            <Plus className="h-4 w-4" /> New semester
          </Button>
        }
      />
      <Card>
        <ListToolbar>
          <SearchBox value={list.search} onChange={list.setSearch} placeholder="Search semesters or batches…" />
          <PlacementFilters
            departments={structure.departments}
            value={filterPlacement}
            onChange={(p) => list.setFilters((f) => ({ ...f, department_id: p.department_id, batch_id: p.batch_id }))}
            depth="batch"
            hideDepartment={!isAdmin}
          />
          <FilterSelect label="Status" value={list.filters.is_active ?? ""} onChange={(v) => list.setFilter("is_active", v)} options={ACTIVE_OPTIONS} />
        </ListToolbar>
        <DataTable columns={columns} data={list.data} loading={list.loading} error={list.error} onRetry={list.reload} onPageChange={list.setPage} rowKey={(s) => s.id} empty={{ icon: CalendarDays, title: "No semesters found" }} />
      </Card>

      <Modal
        open={editing !== null}
        title={editing === "new" ? "New semester" : editing ? `Edit ${editing.batch_name} · ${editing.name}` : ""}
        onClose={() => setEditing(null)}
        onSubmit={save}
        submitting={saving}
        submitDisabled={!form.number || (editing === "new" && !placement.batch_id)}
      >
        {error && <Alert>{error}</Alert>}
        {editing === "new" && <PlacementSelects departments={structure.departments} value={placement} onChange={setPlacement} depth="batch" hideDepartment={!isAdmin} idPrefix="sem" />}
        <div className="grid gap-4 sm:grid-cols-2">
          <Input label="Number" name="sem-number" type="number" min={1} max={12} value={form.number} onChange={(e) => setForm({ ...form, number: e.target.value })} />
          <Input label="Name" name="sem-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder={form.number ? `Semester ${form.number}` : "Semester N"} hint="Leave blank to use “Semester N”." />
          <Input label="Start date" name="sem-start" type="date" value={form.start_date} onChange={(e) => setForm({ ...form, start_date: e.target.value })} />
          <Input label="End date" name="sem-end" type="date" value={form.end_date} onChange={(e) => setForm({ ...form, end_date: e.target.value })} />
        </div>
        <Checkbox name="sem-current" label="Current semester for this batch" checked={form.is_current} onChange={(v) => setForm({ ...form, is_current: v })} hint="Marking this current clears the flag on the batch's other semesters." />
        <Checkbox name="sem-active" label="Active" checked={form.is_active} onChange={(v) => setForm({ ...form, is_active: v })} />
      </Modal>
    </>
  );
}
