export type AttendanceStatus = "present" | "absent" | "late" | "excused";
export type SessionStatus = "draft" | "finalized" | "cancelled";
export type BulkAction = "all_present" | "all_absent" | "unmarked_absent" | "reset";

export interface AttendanceClass {
  assignment_id: number;
  course_id: number;
  course_code: string;
  course_title: string;
  is_lab: boolean;
  batch_id: number;
  batch_name: string;
  semester_id: number;
  semester_number: number;
  semester_name: string;
  section_id: number;
  section_name: string;
  department_code: string;
  enrolled_count: number;
  finalized_sessions: number;
  attendance_percentage: number | null;
  open_draft_session_id: number | null;
  last_session_date: string | null;
}

export interface AttendanceSummary {
  total: number;
  present: number;
  absent: number;
  late: number;
  excused: number;
  unmarked: number;
  percentage: number | null;
}

export interface AttendanceRecord {
  id: number;
  student_id: number;
  registration_no: string;
  full_name: string;
  profile_photo_url: string | null;
  status: AttendanceStatus | null;
  note: string | null;
  method: "face_recognition" | "face_recognition_confirmed" | "manual" | "hod_override";
  recognition_face_id: number | null;
  confidence: number | null;
  updated_at: string;
  corrected: boolean;
}

export interface SessionImage {
  id: number;
  width: number;
  height: number;
  file_size: number;
  uploaded_at: string;
  image_url: string;
}

export interface AttendanceModification {
  id: number;
  record_id: number;
  registration_no: string;
  student_name: string;
  old_status: AttendanceStatus | null;
  new_status: AttendanceStatus | null;
  old_note: string | null;
  new_note: string | null;
  reason: string;
  modified_by_name: string;
  modifier_role: string;
  modified_at: string;
}

export interface AttendanceSession {
  id: number;
  status: SessionStatus;
  version: number;
  assignment_id: number | null;
  teacher_id: number;
  teacher_name: string;
  course_id: number;
  course_code: string;
  course_title: string;
  is_lab: boolean;
  department_id: number;
  department_code: string;
  batch_name: string;
  semester_id: number;
  semester_name: string;
  section_id: number;
  section_name: string;
  session_date: string;
  session_number: number;
  note: string | null;
  created_at: string;
  finalized_at: string | null;
  finalized_by_name: string | null;
  cancelled_at: string | null;
  cancel_reason: string | null;
  summary: AttendanceSummary;
  records: AttendanceRecord[];
  images: SessionImage[];
  max_photos: number;
  can_edit: boolean;
  can_correct: boolean;
  correction_deadline: string | null;
  /** "Delete Attendance": the HOD (own department) or the teacher within the correction window. */
  can_delete: boolean;
  modifications: AttendanceModification[];
}

export interface SessionListItem {
  id: number;
  status: SessionStatus;
  session_date: string;
  session_number: number;
  course_id: number;
  course_code: string;
  course_title: string;
  teacher_id: number;
  teacher_name: string;
  department_code: string;
  batch_name: string;
  semester_name: string;
  section_name: string;
  summary: AttendanceSummary;
  photo_count: number;
  created_at: string;
  finalized_at: string | null;
}

export const STATUS_META: Record<AttendanceStatus, { label: string; short: string; tone: string; active: string }> = {
  present: { label: "Present", short: "P", tone: "text-emerald-700 dark:text-emerald-300", active: "bg-emerald-600 text-white border-emerald-600" },
  absent: { label: "Absent", short: "A", tone: "text-red-700 dark:text-red-300", active: "bg-red-600 text-white border-red-600" },
  late: { label: "Late", short: "L", tone: "text-amber-700 dark:text-amber-300", active: "bg-amber-500 text-white border-amber-500" },
  excused: { label: "Excused", short: "E", tone: "text-sky-700 dark:text-sky-300", active: "bg-sky-600 text-white border-sky-600" },
};

export const STATUSES: AttendanceStatus[] = ["present", "absent", "late", "excused"];
