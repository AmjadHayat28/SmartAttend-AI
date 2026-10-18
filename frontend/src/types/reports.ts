import type { AttendanceStatus } from "./attendance";

/** Teacher attendance reports. Every percentage / low flag comes from the API (shared policy). */
export interface ReportClass {
  assignment_id: number;
  course_id: number;
  course_code: string;
  course_title: string;
  section_id: number;
  section_name: string;
  semester_number: number;
  batch_name: string;
  teacher_name: string;
}

export interface StudentReportRow {
  student_id: number;
  registration_no: string;
  student_name: string;
  currently_enrolled: boolean;
  total_classes: number;
  present: number;
  absent: number;
  late: number;
  excused: number;
  attended: number;
  conducted: number;
  percentage: number | null;
  low_attendance: boolean;
}

export interface ClassReport {
  report_class: ReportClass;
  threshold: number;
  date_from: string | null;
  date_to: string | null;
  finalized_sessions: number;
  enrolled_students: number;
  class_percentage: number | null;
  low_attendance_students: number;
  students: StudentReportRow[];
}

export interface DailySession {
  session_number: number;
  present: number;
  absent: number;
  late: number;
  excused: number;
  percentage: number | null;
  records: { student_id: number; registration_no: string; student_name: string; status: AttendanceStatus }[];
}

export interface DailyReport {
  report_class: ReportClass;
  report_date: string;
  sessions: DailySession[];
}

export interface StudentReport {
  report_class: ReportClass;
  threshold: number;
  date_from: string | null;
  date_to: string | null;
  student: StudentReportRow;
  records: { session_date: string; session_number: number; status: AttendanceStatus }[];
}

export type ReportType = "summary" | "daily" | "monthly" | "student";
