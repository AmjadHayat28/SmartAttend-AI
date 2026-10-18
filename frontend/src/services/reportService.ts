import type { Assignment } from "../types/api";
import type { ClassReport, DailyReport, ReportType, StudentReport } from "../types/reports";
import { api } from "./api";

type Params = Record<string, string | number | undefined>;

function clean(params: Params) {
  return Object.fromEntries(Object.entries(params).filter(([, v]) => v !== "" && v !== undefined));
}

/** Teacher-only attendance reports for the caller's own active classes. */
export const reportApi = {
  classes: () => api.get<Assignment[]>("/reports/classes").then((r) => r.data),
  summary: (assignmentId: number, params: Params) =>
    api.get<ClassReport>(`/reports/class/${assignmentId}`, { params: clean(params) }).then((r) => r.data),
  daily: (assignmentId: number, params: Params) =>
    api.get<DailyReport>(`/reports/class/${assignmentId}/daily`, { params: clean(params) }).then((r) => r.data),
  monthly: (assignmentId: number, params: Params) =>
    api.get<ClassReport>(`/reports/class/${assignmentId}/monthly`, { params: clean(params) }).then((r) => r.data),
  student: (assignmentId: number, studentId: number, params: Params) =>
    api.get<StudentReport>(`/reports/class/${assignmentId}/students/${studentId}`, { params: clean(params) }).then((r) => r.data),

  /** Download the .xlsx and hand it to the browser under the server's filename. */
  async exportExcel(assignmentId: number, type: ReportType, params: Params) {
    let res;
    try {
      res = await api.get<Blob>(`/reports/class/${assignmentId}/export`, { params: clean({ type, ...params }), responseType: "blob" });
    } catch (err) {
      // Error bodies arrive as a Blob too; surface the API's message.
      const data = (err as { response?: { data?: unknown } }).response?.data;
      if (data instanceof Blob) {
        const detail = await data.text().then((t) => (JSON.parse(t) as { detail?: unknown }).detail).catch(() => null);
        if (typeof detail === "string") throw new Error(detail);
      }
      throw err;
    }
    const disposition = String(res.headers["content-disposition"] ?? "");
    const name = /filename="?([^";]+)"?/i.exec(disposition)?.[1] ?? "Attendance_Report.xlsx";
    const url = URL.createObjectURL(res.data);
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    return name;
  },
};
