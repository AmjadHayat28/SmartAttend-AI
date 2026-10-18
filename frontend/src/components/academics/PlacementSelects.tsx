import { useEffect } from "react";
import { updatePlacement, usePlacementNodes, type Placement } from "../../hooks/useStructure";
import type { StructureDepartment } from "../../types/api";
import { Select } from "../ui/FormField";
import { FilterSelect } from "../ui/ListToolbar";

type Level = "department" | "batch" | "semester" | "section";
const DEPTH: Record<Level, number> = { department: 0, batch: 1, semester: 2, section: 3 };

const label = (name: string, active: boolean) => (active ? name : `${name} (inactive)`);

function options(departments: StructureDepartment[], nodes: ReturnType<typeof usePlacementNodes>) {
  return {
    department: departments.map((d) => ({ value: d.id, label: label(`${d.code} — ${d.name}`, d.is_active) })),
    batch: (nodes.department?.batches ?? []).map((b) => ({ value: b.id, label: label(b.name, b.is_active) })),
    semester: (nodes.batch?.semesters ?? []).map((s) => ({ value: s.id, label: label(s.name, s.is_active) })),
    section: (nodes.semester?.sections ?? []).map((s) => ({ value: s.id, label: label(`Section ${s.name}`, s.is_active) })),
  };
}

/** HODs see exactly one department: pick it automatically and hide the selector. */
function useAutoDepartment(departments: StructureDepartment[], value: Placement, onChange: (p: Placement) => void, single: boolean) {
  useEffect(() => {
    if (single && departments.length === 1 && value.department_id !== String(departments[0]!.id)) {
      onChange(updatePlacement(value, "department_id", String(departments[0]!.id)));
    }
  }, [single, departments, value, onChange]);
}

interface PlacementSelectsProps {
  departments: StructureDepartment[];
  value: Placement;
  onChange: (p: Placement) => void;
  depth?: Level;
  hideDepartment?: boolean;
  errors?: Partial<Record<keyof Placement, string>>;
  idPrefix?: string;
}

/** Cascading form selects: department → batch → semester → section. */
export function PlacementSelects({ departments, value, onChange, depth = "section", hideDepartment, errors = {}, idPrefix = "pl" }: PlacementSelectsProps) {
  const nodes = usePlacementNodes(departments, value);
  const opts = options(departments, nodes);
  useAutoDepartment(departments, value, onChange, !!hideDepartment);
  const max = DEPTH[depth];
  const set = (field: keyof Placement) => (e: { target: { value: string } }) => onChange(updatePlacement(value, field, e.target.value));

  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {!hideDepartment && (
        <Select id={`${idPrefix}-dept`} label="Department" name="department_id" value={value.department_id} onChange={set("department_id")} placeholder="Select department" options={opts.department} error={errors.department_id} />
      )}
      {max >= 1 && (
        <Select id={`${idPrefix}-batch`} label="Batch" name="batch_id" value={value.batch_id} onChange={set("batch_id")} placeholder="Select batch" options={opts.batch} disabled={!nodes.department} error={errors.batch_id} />
      )}
      {max >= 2 && (
        <Select id={`${idPrefix}-sem`} label="Semester" name="semester_id" value={value.semester_id} onChange={set("semester_id")} placeholder="Select semester" options={opts.semester} disabled={!nodes.batch} error={errors.semester_id} />
      )}
      {max >= 3 && (
        <Select id={`${idPrefix}-sec`} label="Section" name="section_id" value={value.section_id} onChange={set("section_id")} placeholder="Select section" options={opts.section} disabled={!nodes.semester} error={errors.section_id} />
      )}
    </div>
  );
}

/** The same cascade as compact list filters. Empty values mean "all". */
export function PlacementFilters({ departments, value, onChange, depth = "section", hideDepartment }: Omit<PlacementSelectsProps, "errors" | "idPrefix">) {
  const nodes = usePlacementNodes(departments, value);
  const opts = options(departments, nodes);
  const max = DEPTH[depth];
  const set = (field: keyof Placement) => (v: string) => onChange(updatePlacement(value, field, v));
  const deptForChildren = hideDepartment ? departments[0] : nodes.department;
  const batchOptions = (deptForChildren?.batches ?? []).map((b) => ({ value: b.id, label: label(b.name, b.is_active) }));
  const batch = deptForChildren?.batches.find((b) => String(b.id) === value.batch_id);
  const semesterOptions = (batch?.semesters ?? []).map((s) => ({ value: s.id, label: label(s.name, s.is_active) }));
  const semester = batch?.semesters.find((s) => String(s.id) === value.semester_id);
  const sectionOptions = (semester?.sections ?? []).map((s) => ({ value: s.id, label: label(`Section ${s.name}`, s.is_active) }));

  return (
    <>
      {!hideDepartment && <FilterSelect label="Department" value={value.department_id} onChange={set("department_id")} options={opts.department} />}
      {max >= 1 && <FilterSelect label="Batch" value={value.batch_id} onChange={set("batch_id")} options={batchOptions} disabled={!deptForChildren} />}
      {max >= 2 && <FilterSelect label="Semester" value={value.semester_id} onChange={set("semester_id")} options={semesterOptions} disabled={!batch} />}
      {max >= 3 && <FilterSelect label="Section" value={value.section_id} onChange={set("section_id")} options={sectionOptions} disabled={!semester} />}
    </>
  );
}
