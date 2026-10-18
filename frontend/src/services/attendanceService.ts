import type { ListParams, Page } from "../types/api";
import type {
  AttendanceClass,
  AttendanceSession,
  AttendanceStatus,
  BulkAction,
  SessionListItem,
} from "../types/attendance";
import type { Recognition, RecognitionAction } from "../types/recognition";
import { api } from "./api";

export interface RecordChange {
  record_id: number;
  status?: AttendanceStatus | null;
  note?: string | null;
}

const clean = (params: ListParams = {}) =>
  Object.fromEntries(Object.entries(params).filter(([, v]) => v !== "" && v !== undefined && v !== null));

export const attendanceApi = {
  classes: () => api.get<AttendanceClass[]>("/attendance/classes").then((r) => r.data),
  start: (assignment_id: number, session_date: string, session_number: number) =>
    api
      .post<{ resumed: boolean; added_to_roster: number; session: AttendanceSession }>("/attendance/sessions", {
        assignment_id,
        session_date,
        session_number,
      })
      .then((r) => r.data),
  get: (id: number) => api.get<AttendanceSession>(`/attendance/sessions/${id}`).then((r) => r.data),
  list: (params?: ListParams) => api.get<Page<SessionListItem>>("/attendance/sessions", { params: clean(params) }).then((r) => r.data),
  updateRecords: (id: number, version: number, changes: RecordChange[]) =>
    api.patch<AttendanceSession>(`/attendance/sessions/${id}/records`, { version, changes }).then((r) => r.data),
  bulk: (id: number, version: number, action: BulkAction) =>
    api.post<AttendanceSession>(`/attendance/sessions/${id}/bulk`, { version, action }).then((r) => r.data),
  updateNote: (id: number, version: number, note: string | null) =>
    api.patch<AttendanceSession>(`/attendance/sessions/${id}`, { version, note }).then((r) => r.data),
  uploadImage: (id: number, file: Blob, onProgress?: (p: number) => void) => {
    const data = new FormData();
    data.append("file", file, file.type === "image/png" ? "photo.png" : "photo.jpg"); // server ignores the name
    return api
      .post<AttendanceSession>(`/attendance/sessions/${id}/images`, data, {
        timeout: 120_000,
        onUploadProgress: (e) => onProgress?.(e.total ? Math.round((e.loaded / e.total) * 100) : 0),
      })
      .then((r) => r.data);
  },
  removeImage: (id: number, imageId: number) =>
    api.delete<AttendanceSession>(`/attendance/sessions/${id}/images/${imageId}`).then((r) => r.data),
  finalize: (id: number, version: number) =>
    api.post<AttendanceSession>(`/attendance/sessions/${id}/finalize`, { version }).then((r) => r.data),
  cancel: (id: number, version: number, reason?: string) =>
    api.post<AttendanceSession>(`/attendance/sessions/${id}/cancel`, { version, reason }).then((r) => r.data),
  /** Delete Attendance: permanently delete this one finalized session (reason required). */
  remove: (id: number, reason: string, version?: number) =>
    api.post<void>(`/attendance/sessions/${id}/delete`, { reason, version }).then(() => undefined),
  correct: (recordId: number, status: AttendanceStatus, reason: string, note?: string | null) =>
    api
      .post<AttendanceSession>(`/attendance/records/${recordId}/correct`, { status, reason, ...(note !== undefined ? { note } : {}) })
      .then((r) => r.data),
};

/** Local date as YYYY-MM-DD (not UTC — "today" means today where the teacher is). */
export function localToday() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function formatSessionDate(iso: string) {
  const [y, m, d] = iso.split("-").map(Number);
  return new Intl.DateTimeFormat(undefined, { weekday: "short", day: "numeric", month: "short", year: "numeric" }).format(
    new Date(y!, m! - 1, d!),
  );
}


export const recognitionApi = {
  get: (sessionId: number) => api.get<Recognition>(`/attendance/sessions/${sessionId}/recognition`).then((r) => r.data),
  run: (sessionId: number, version: number) =>
    api.post<RecognitionAction>(`/attendance/sessions/${sessionId}/recognition`, { version }, { timeout: 300_000 }).then((r) => r.data),
  accept: (faceId: number, version: number) =>
    api.post<RecognitionAction>(`/attendance/recognition/faces/${faceId}/accept`, { version }).then((r) => r.data),
  assign: (faceId: number, version: number, studentId: number, replace = false) =>
    api
      .post<RecognitionAction>(`/attendance/recognition/faces/${faceId}/assign`, { version, student_id: studentId, replace })
      .then((r) => r.data),
  reject: (faceId: number, version: number) =>
    api.post<RecognitionAction>(`/attendance/recognition/faces/${faceId}/reject`, { version }).then((r) => r.data),
};
