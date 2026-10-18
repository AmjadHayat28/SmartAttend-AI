import type {
  AdminSummary,
  Department,
  HodSummary,
  Page,
  PendingStudent,
  StudentSubjects,
  TeacherClass,
} from "../types/api";
import type { AccountStatus } from "../types/auth";
import { api } from "./api";

export const dashboardService = {
  admin: () => api.get<AdminSummary>("/dashboard/admin").then((r) => r.data),
  hod: () => api.get<HodSummary>("/dashboard/hod").then((r) => r.data),
  teacherClasses: () => api.get<TeacherClass[]>("/dashboard/teacher/classes").then((r) => r.data),
  studentSubjects: () => api.get<StudentSubjects>("/dashboard/student/subjects").then((r) => r.data),
};

export const accountService = {
  pendingStudents: (page = 1, pageSize = 10) =>
    api
      .get<Page<PendingStudent>>("/accounts/pending-students", { params: { page, page_size: pageSize } })
      .then((r) => r.data),
  setStatus: (userId: number, status: AccountStatus, reason?: string) =>
    api.patch(`/accounts/${userId}/status`, { status, reason }).then((r) => r.data),
};

export const departmentService = {
  list: () => api.get<Department[]>("/departments").then((r) => r.data),
  create: (payload: { name: string; code: string; description?: string }) =>
    api.post<Department>("/departments", payload).then((r) => r.data),
};
