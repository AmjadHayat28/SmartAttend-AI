import type { StudentAttendanceOverview, StudentSubjectDetail } from "../types/studentAttendance";
import { api } from "./api";

/** The signed-in student's own attendance — no student id is ever sent. */
export const studentAttendanceApi = {
  overview: () => api.get<StudentAttendanceOverview>("/student/attendance").then((r) => r.data),
  subject: (courseId: number | string) => api.get<StudentSubjectDetail>(`/student/attendance/subjects/${courseId}`).then((r) => r.data),
};
