import { useMemo } from "react";
import { structureApi } from "../services/managementService";
import type { StructureBatch, StructureDepartment, StructureSemester } from "../types/api";
import { useAsync } from "./useAsync";

/** Department → batch → semester → section tree for the signed-in admin/HOD.
 *  Pass `enabled = false` on pages also used by roles without access (e.g. teachers). */
export function useStructure(enabled = true) {
  const { data, loading, error, reload } = useAsync(() => (enabled ? structureApi.get() : Promise.resolve([])), [enabled]);
  return { departments: data ?? [], loading, error, reload };
}

export interface Placement {
  department_id: string;
  batch_id: string;
  semester_id: string;
  section_id: string;
}

export const EMPTY_PLACEMENT: Placement = { department_id: "", batch_id: "", semester_id: "", section_id: "" };

/** Resolve the selected nodes of a placement against the tree. */
export function usePlacementNodes(departments: StructureDepartment[], p: Placement) {
  return useMemo(() => {
    const department = departments.find((d) => String(d.id) === p.department_id);
    const batch: StructureBatch | undefined = department?.batches.find((b) => String(b.id) === p.batch_id);
    const semester: StructureSemester | undefined = batch?.semesters.find((s) => String(s.id) === p.semester_id);
    const section = semester?.sections.find((s) => String(s.id) === p.section_id);
    return { department, batch, semester, section };
  }, [departments, p.department_id, p.batch_id, p.semester_id, p.section_id]);
}

/** Changing a level clears every level below it. */
export function updatePlacement(p: Placement, field: keyof Placement, value: string): Placement {
  const order: (keyof Placement)[] = ["department_id", "batch_id", "semester_id", "section_id"];
  const next = { ...p, [field]: value };
  for (const key of order.slice(order.indexOf(field) + 1)) next[key] = "";
  return next;
}
