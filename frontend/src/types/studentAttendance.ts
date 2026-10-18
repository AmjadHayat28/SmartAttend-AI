import type { AttendanceStatus } from "./attendance";

/** One enrolled subject, counted over FINALIZED sessions only (server-side policy). */
export interface StudentSubjectSummary {
  course_id: number;
  course_code: string;
  course_title: string;
  section_name: string;
  teacher_names: string[];
  total_classes: number;
  present: number;
  absent: number;
  late: number;
  excused: number;
  attended: number;
  conducted: number;
  /** null until the first finalized class. */
  percentage: number | null;
  low_attendance: boolean;
}

export interface StudentAttendanceOverview {
  threshold: number;
  policy: { late_weight: number; excused_policy: string };
  subjects: StudentSubjectSummary[];
}

export interface StudentAttendanceEntry {
  session_date: string;
  session_number: number;
  status: AttendanceStatus;
}

export interface StudentSubjectDetail {
  threshold: number;
  subject: StudentSubjectSummary;
  /** Newest first. */
  records: StudentAttendanceEntry[];
}
