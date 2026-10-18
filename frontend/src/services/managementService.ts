import type {
  Assignment,
  Batch,
  BulkEnrollResult,
  Course,
  Enrollment,
  EnrollmentCandidate,
  Hod,
  ListParams,
  Page,
  Section,
  Semester,
  StructureDepartment,
  Student,
  Teacher,
} from "../types/api";
import type { AccountStatus } from "../types/auth";
import { api } from "./api";

/** Drop empty filters so the API applies only what the user chose. */
function clean(params: ListParams = {}) {
  return Object.fromEntries(Object.entries(params).filter(([, v]) => v !== "" && v !== undefined && v !== null));
}

/** list / get / create / update for one REST resource. */
function resource<T>(path: string) {
  return {
    list: (params?: ListParams) => api.get<Page<T>>(path, { params: clean(params) }).then((r) => r.data),
    get: (id: number) => api.get<T>(`${path}/${id}`).then((r) => r.data),
    create: (body: object) => api.post<T>(path, body).then((r) => r.data),
    update: (id: number, body: object) => api.patch<T>(`${path}/${id}`, body).then((r) => r.data),
  };
}

export const batchApi = resource<Batch>("/batches");
export const semesterApi = resource<Semester>("/semesters");
export const sectionApi = resource<Section>("/sections");
export const courseApi = resource<Course>("/courses");
export const hodApi = resource<Hod>("/hods");
export const teacherApi = resource<Teacher>("/teachers");
export const studentApi = resource<Student>("/students");

export const assignmentApi = {
  list: (params?: ListParams) => api.get<Page<Assignment>>("/assignments", { params: clean(params) }).then((r) => r.data),
  create: (body: { teacher_id: number; course_id: number; section_id: number }) =>
    api.post<Assignment>("/assignments", body).then((r) => r.data),
  remove: (id: number) => api.delete(`/assignments/${id}`),
};

/** Course enrollments — the class's own teacher, through one of their active assignments. */
export const enrollmentApi = {
  classes: () => api.get<Assignment[]>("/enrollments/classes").then((r) => r.data),
  list: (params: ListParams) => api.get<Page<Enrollment>>("/enrollments", { params: clean(params) }).then((r) => r.data),
  candidates: (params: ListParams) =>
    api.get<Page<EnrollmentCandidate>>("/enrollments/candidates", { params: clean(params) }).then((r) => r.data),
  create: (body: { assignment_id: number; student_id: number }) => api.post<Enrollment>("/enrollments", body).then((r) => r.data),
  remove: (id: number) => api.delete(`/enrollments/${id}`),
  bulk: (body: { assignment_id: number; dry_run?: boolean }) =>
    api.post<BulkEnrollResult>("/enrollments/bulk", body).then((r) => r.data),
};

export const accountApi = {
  setStatus: (userId: number, status: AccountStatus, reason?: string) =>
    api.patch(`/accounts/${userId}/status`, { status, reason }).then((r) => r.data),
  resetPassword: (userId: number, new_password: string) =>
    api.post<{ message: string }>(`/accounts/${userId}/reset-password`, { new_password }).then((r) => r.data),
};

export const structureApi = {
  get: () => api.get<StructureDepartment[]>("/academics/structure").then((r) => r.data),
};
