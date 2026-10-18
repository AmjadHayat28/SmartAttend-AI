import { Building2, Plus } from "lucide-react";
import { useState, type FormEvent } from "react";
import { PageHeader } from "../../components/layout/PageHeader";
import { Button } from "../../components/ui/Button";
import { Card, CardHeader } from "../../components/ui/Card";
import { Alert, Badge, EmptyState, ErrorState, Spinner } from "../../components/ui/Feedback";
import { Input } from "../../components/ui/FormField";
import { useToast } from "../../context/ToastContext";
import { useAsync } from "../../hooks/useAsync";
import { getErrorMessage } from "../../services/api";
import { departmentService } from "../../services/dashboardService";

export function DepartmentsPage() {
  const toast = useToast();
  const { data, loading, error, reload } = useAsync(() => departmentService.list());
  const [form, setForm] = useState({ name: "", code: "", description: "" });
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  async function handleCreate(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setFormError(null);
    try {
      const dept = await departmentService.create({
        name: form.name.trim(),
        code: form.code.trim(),
        description: form.description.trim() || undefined,
      });
      toast.success(`Department "${dept.name}" created.`);
      setForm({ name: "", code: "", description: "" });
      reload();
    } catch (err) {
      setFormError(getErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  const q = search.trim().toLowerCase();
  const rows = (data ?? []).filter((d) => !q || d.name.toLowerCase().includes(q) || d.code.toLowerCase().includes(q));

  return (
    <>
      <PageHeader title="Departments" description="Every HOD, teacher, student and course belongs to exactly one department." />
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <Card>
          <CardHeader
            title="All departments"
            action={
              <input
                type="search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search…"
                aria-label="Search departments"
                className="h-9 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm focus:border-brand-500 focus:outline-none sm:w-56 dark:border-slate-700 dark:bg-slate-950"
              />
            }
          />
          {loading ? (
            <Spinner />
          ) : error ? (
            <ErrorState message={error} onRetry={reload} />
          ) : !rows.length ? (
            <EmptyState icon={Building2} title={q ? "No matches" : "No departments yet"} description={q ? undefined : "Create the first department using the form."} />
          ) : (
            <ul className="divide-y divide-slate-200 dark:divide-slate-800">
              {rows.map((d) => (
                <li key={d.id} className="flex items-center gap-4 px-5 py-3">
                  <span className="grid h-10 w-14 place-items-center rounded-lg bg-brand-50 text-xs font-bold text-brand-800 dark:bg-brand-900/40 dark:text-brand-200">{d.code}</span>
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-medium text-slate-900 dark:text-white">{d.name}</p>
                    {d.description && <p className="truncate text-sm text-slate-500">{d.description}</p>}
                  </div>
                  <Badge tone={d.is_active ? "green" : "gray"}>{d.is_active ? "Active" : "Inactive"}</Badge>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card className="h-fit">
          <CardHeader title="New department" />
          <form onSubmit={handleCreate} className="space-y-4 p-5">
            {formError && <Alert>{formError}</Alert>}
            <Input label="Name" name="name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Computer Systems Engineering" required />
            <Input label="Code" name="code" value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value.toUpperCase() })} placeholder="CSE" hint="2–20 letters, digits, '-' or '_'" required />
            <Input label="Description" name="description" value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} />
            <Button type="submit" className="w-full" loading={saving} disabled={form.name.trim().length < 2 || form.code.trim().length < 2}>
              <Plus className="h-4 w-4" /> Create department
            </Button>
          </form>
        </Card>
      </div>
    </>
  );
}
