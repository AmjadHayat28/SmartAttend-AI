import type { AccountStatus } from "./auth";
import type { FaceEnrollmentStatus } from "./face";

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface Option {
  id: number;
  label: string;
}

export interface SemesterOption extends Option {
  number: number;
  sections: Option[];
}

export interface BatchOption extends Option {
  semesters: SemesterOption[];
}

export interface DepartmentTree extends Option {
  code: string;
  batches: BatchOption[];
}

export interface Department {
  id: number;
  name: string;
  code: string;
  description: string | null;
  is_active: boolean;
}

export interface PendingStudent {
  user_id: number;
  full_name: string;
  email: string;
  registration_no: string;
  department_id: number;
  batch: string;
  semester: number;
  section: string;
  registered_at: string;
  face_enrollment_status: FaceEnrollmentStatus;
}

/** System administration only: departments and staff — no students or attendance. */
export interface AdminSummary {
  departments: number;
  active_departments: number;
  hods: number;
  active_hods: number;
  teachers: number;
  active_teachers: number;
  suspended_staff: number;
  departments_without_hod: number;
  recent_activity: { id: number; action: string; entity: string; entity_id: string | null; timestamp: string; actor_name: string | null }[];
}

export interface HodSummary {
  department_name: string;
  teachers: number;
  students: number;
  subjects: number;
  pending_approvals: number;
  today_attendance_pct: number | null;
}

export interface TeacherClass {
  assignment_id: number;
  course_id: number;
  course_code: string;
  course_title: string;
  is_lab: boolean;
  section_id: number;
  section: string;
  semester: number;
  semester_name: string;
}

export interface SubjectAttendance {
  course_id: number;
  course_code: string;
  course_title: string;
  attended: number;
  conducted: number;
  percentage: number | null;
  low_attendance: boolean;
}

export interface StudentSubjects {
  threshold: number;
  subjects: SubjectAttendance[];
}

// ── Phase 3: management ────────────────────────────────────────────────────


export interface ListParams {
  page?: number;
  page_size?: number;
  q?: string;
  [filter: string]: string | number | boolean | undefined | null;
}

export interface StructureSection {
  id: number;
  name: string;
  is_active: boolean;
}
export interface StructureSemester {
  id: number;
  number: number;
  name: string;
  is_active: boolean;
  is_current: boolean;
  sections: StructureSection[];
}
export interface StructureBatch {
  id: number;
  name: string;
  is_active: boolean;
  semesters: StructureSemester[];
}
export interface StructureDepartment {
  id: number;
  name: string;
  code: string;
  is_active: boolean;
  batches: StructureBatch[];
}

export interface Batch {
  id: number;
  department_id: number;
  department_code: string;
  name: string;
  start_year: number;
  end_year: number | null;
  is_active: boolean;
  semester_count: number;
  student_count: number;
}

export interface Semester {
  id: number;
  batch_id: number;
  batch_name: string;
  department_id: number;
  department_code: string;
  number: number;
  name: string;
  start_date: string | null;
  end_date: string | null;
  is_current: boolean;
  is_active: boolean;
  section_count: number;
}

export interface Section {
  id: number;
  name: string;
  capacity: number | null;
  is_active: boolean;
  semester_id: number;
  semester_number: number;
  semester_name: string;
  batch_id: number;
  batch_name: string;
  department_id: number;
  department_code: string;
  student_count: number;
}

export interface Course {
  id: number;
  department_id: number;
  department_code: string;
  code: string;
  title: string;
  credit_hours: number;
  is_lab: boolean;
  semester_number: number | null;
  is_active: boolean;
}

interface AccountBase {
  id: number;
  user_id: number;
  full_name: string;
  email: string;
  status: AccountStatus;
  status_reason: string | null;
  department_id: number;
  department_name: string;
  department_code: string;
  last_login_at: string | null;
  created_at: string;
}

export interface Hod extends AccountBase {
  employee_id: string;
  phone: string | null;
  appointed_on: string | null;
  is_current: boolean;
}

export interface Teacher extends AccountBase {
  employee_id: string;
  designation: string | null;
  phone: string | null;
  assignment_count: number;
}

export interface Student extends AccountBase {
  registration_no: string;
  batch_id: number;
  batch_name: string;
  semester_id: number;
  semester_number: number;
  semester_name: string;
  section_id: number;
  section_name: string;
  enrollment_count: number;
  face_enrollment_status: FaceEnrollmentStatus;
}

export interface Assignment {
  id: number;
  teacher_id: number;
  teacher_name: string;
  employee_id: string;
  course_id: number;
  course_code: string;
  course_title: string;
  is_lab: boolean;
  section_id: number;
  section_name: string;
  semester_id: number;
  semester_number: number;
  batch_id: number;
  batch_name: string;
  department_id: number;
  department_code: string;
  is_active: boolean;
  assigned_at: string;
}

export interface Enrollment {
  id: number;
  student_id: number;
  student_name: string;
  registration_no: string;
  course_id: number;
  course_code: string;
  course_title: string;
  section_id: number;
  section_name: string;
  semester_id: number;
  semester_number: number;
  batch_name: string;
  department_id: number;
  is_active: boolean;
  created_at: string;
}

/** A student of the class's section who is not yet enrolled in its course. */
export interface EnrollmentCandidate {
  student_id: number;
  student_name: string;
  registration_no: string;
  status: AccountStatus;
}

export interface BulkEnrollResult {
  assignment_id: number;
  course_id: number;
  course_code: string;
  section_id: number;
  dry_run: boolean;
  students_in_section: number;
  students_eligible: number;
  newly_enrolled: number;
  already_enrolled: number;
  /** Rejected or suspended accounts. */
  skipped: number;
  errors: string[];
}
