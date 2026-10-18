import { LayoutGrid, Pencil, Plus } from "lucide-react";
import { useState } from "react";
import { PlacementFilters, PlacementSelects } from "../../components/academics/PlacementSelects";
import { PageHeader } from "../../components/layout/PageHeader";
import { ActiveBadge } from "../../components/ui/ActiveBadge";
import { Button } from "../../components/ui/Button";
import { Card } from "../../components/ui/Card";
import { DataTable, type Column } from "../../components/ui/DataTable";
import { Alert } from "../../components/ui/Feedback";
import { Checkbox, Input } from "../../components/ui/FormField";
import { ACTIVE_OPTIONS, FilterSelect, ListToolbar, SearchBox } from "../../components/ui/ListToolbar";
import { Modal } from "../../components/ui/Modal";
import { useToast } from "../../context/ToastContext";
import { usePagedList } from "../../hooks/usePagedList";
import { useRole } from "../../hooks/useRole";
import { EMPTY_PLACEMENT, useStructure, type Placement } from "../../hooks/useStructure";
import { getErrorMessage } from "../../services/api";
import { sectionApi } from "../../services/managementService";
import type { Section } from "../../types/api";

const EMPTY = { name: "", capacity: "", is_active: true };

export function SectionsPage() {
  const { isAdmin } = useRole();
  const toast = useToast();
  const structure = useStructure();
  const list = usePagedList(sectionApi.list);
  const [editing, setEditing] = useState<Section | "new" | null>(null);
  const [placement, setPlacement] = useState<Placement>(EMPTY_PLACEMENT);
  const [form, setForm] = useState(EMPTY);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const f = list.filters;
  const filterPlacement = { ...EMPTY_PLACEMENT, department_id: f.department_id ?? "", batch_id: f.batch_id ?? "", semester_id: f.semester_id ?? "" };

  function open(section: Section | "new") {
    setError(null);
    setEditing(section);
    setPlacement(EMPTY_PLACEMENT);
    setForm(section === "new" ? EMPTY : { name: section.name, capacity: section.capacity ? String(section.capacity) : "", is_active: section.is_active });
  }

  async function save() {
    setSaving(true);
    setError(null);
    const body = { name: form.name, capacity: form.capacity ? Number(form.capacity) : null, is_active: form.is_active };
    try {
      if (editing === "new") {
        await sectionApi.create({ ...body, semester_id: Number(placement.semester_id), batch_id: Number(placement.batch_id) });
        toast.success(`Section ${form.name.trim().toUpperCase()} created.`);
      } else if (editing) {
        await sectionApi.update(editing.id, body);
        toast.success("Section updated.");
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

  const columns: Column<Section>[] = [
    { header: "Section", cell: (s) => <span className="font-medium text-slate-900 dark:text-white">Section {s.name}</span> },
    { header: "Batch · Semester", cell: (s) => `${isAdmin ? `${s.department_code} · ` : ""}${s.batch_name} · ${s.semester_name}` },
    { header: "Capacity", cell: (s) => s.capacity ?? "—", className: "tabular-nums" },
    { header: "Students", cell: (s) => s.student_count, className: "tabular-nums" },
    { header: "Status", cell: (s) => <ActiveBadge active={s.is_active} /> },
    {
      header: "Actions",
      className: "text-right",
      cell: (s) => (
        <Button size="sm" variant="ghost" onClick={() => open(s)} aria-label={`Edit section ${s.name}`}>
          <Pencil className="h-4 w-4" />
        </Button>
      ),
    },
  ];

  return (
    <>
      <PageHeader
        title="Sections"
        description="Class groups within a batch and semester, e.g. F23 · Semester 6 · Section A."
        actions={
          <Button onClick={() => open("new")}>
            <Plus className="h-4 w-4" /> New section
          </Button>
        }
      />
      <Card>
        <ListToolbar>
          <SearchBox value={list.search} onChange={list.setSearch} placeholder="Search sections…" />
          <PlacementFilters departments={structure.departments} value={filterPlacement} onChange={(p) => list.setFilters((x) => ({ ...x, department_id: p.department_id, batch_id: p.batch_id, semester_id: p.semester_id }))} depth="semester" hideDepartment={!isAdmin} />
          <FilterSelect label="Status" value={f.is_active ?? ""} onChange={(v) => list.setFilter("is_active", v)} options={ACTIVE_OPTIONS} />
        </ListToolbar>
        <DataTable columns={columns} data={list.data} loading={list.loading} error={list.error} onRetry={list.reload} onPageChange={list.setPage} rowKey={(s) => s.id} empty={{ icon: LayoutGrid, title: "No sections found" }} />
      </Card>

      <Modal
        open={editing !== null}
        title={editing === "new" ? "New section" : editing ? `Edit ${editing.batch_name} · ${editing.semester_name} · Section ${editing.name}` : ""}
        onClose={() => setEditing(null)}
        onSubmit={save}
        submitting={saving}
        submitDisabled={!form.name.trim() || (editing === "new" && !placement.semester_id)}
      >
        {error && <Alert>{error}</Alert>}
        {editing === "new" && <PlacementSelects departments={structure.departments} value={placement} onChange={setPlacement} depth="semester" hideDepartment={!isAdmin} idPrefix="sec" />}
        <div className="grid gap-4 sm:grid-cols-2">
          <Input label="Section name" name="sec-name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="A" />
          <Input label="Capacity (optional)" name="sec-capacity" type="number" min={1} max={1000} value={form.capacity} onChange={(e) => setForm({ ...form, capacity: e.target.value })} />
        </div>
        <Checkbox name="sec-active" label="Active" checked={form.is_active} onChange={(v) => setForm({ ...form, is_active: v })} />
      </Modal>
    </>
  );
}
