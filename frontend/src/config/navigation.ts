import {
  BarChart3,
  BookOpen,
  Building2,
  CalendarCheck,
  CalendarDays,
  CalendarRange,
  ClipboardList,
  GraduationCap,
  History,
  LayoutDashboard,
  LayoutGrid,
  ListChecks,
  ScanFace,
  UserCheck,
  UserCog,
  Users,
  type LucideIcon,
} from "lucide-react";
import type { UserRole } from "../types/auth";

export interface NavItem {
  label: string;
  to: string;
  icon: LucideIcon;
  /** Sidebar group heading; items without a group are listed first. */
  group?: string;
}

/**
 * Who does what:
 * - Super admin = system administrator: departments → HODs → teacher accounts.
 *   No teacher assignments, students or attendance — the API refuses those too.
 * - HOD = department authority: teachers, students, approvals, face review, academics,
 *   teacher assignments. Course enrollments belong to the class's teacher.
 *   No attendance sessions, reports or exports — the API refuses those too.
 * - Teacher = assigned classes: their student enrollments, attendance sessions and attendance
 *   reports / Excel export (the only role with access to any of these).
 * - Student = own enrollment and attendance.
 */
export const NAVIGATION: Record<UserRole, NavItem[]> = {
  super_admin: [
    { label: "Dashboard", to: "/admin", icon: LayoutDashboard },
    { label: "Departments", to: "/admin/departments", icon: Building2 },
    { label: "HODs", to: "/admin/hods", icon: UserCog, group: "Staff" },
    { label: "Teachers", to: "/admin/teachers", icon: Users, group: "Staff" },
  ],
  hod: [
    { label: "Dashboard", to: "/hod", icon: LayoutDashboard },
    { label: "Teachers", to: "/hod/teachers", icon: Users, group: "People" },
    { label: "Students", to: "/hod/students", icon: GraduationCap, group: "People" },
    { label: "Student Approvals", to: "/hod/approvals", icon: UserCheck, group: "People" },
    { label: "Face Review", to: "/hod/face-review", icon: ScanFace, group: "People" },
    { label: "Batches", to: "/hod/batches", icon: CalendarRange, group: "Academics" },
    { label: "Semesters", to: "/hod/semesters", icon: CalendarDays, group: "Academics" },
    { label: "Sections", to: "/hod/sections", icon: LayoutGrid, group: "Academics" },
    { label: "Courses", to: "/hod/courses", icon: BookOpen, group: "Academics" },
    { label: "Teacher Assignments", to: "/hod/assignments", icon: ClipboardList, group: "Classes" },
  ],
  teacher: [
    { label: "Dashboard", to: "/teacher", icon: LayoutDashboard },
    { label: "My Class Enrollments", to: "/teacher/enrollments", icon: ListChecks },
    { label: "Take Attendance", to: "/teacher/attendance/new", icon: CalendarCheck },
    { label: "Attendance History", to: "/teacher/history", icon: History },
    { label: "Attendance Reports", to: "/teacher/reports", icon: BarChart3 },
  ],
  student: [
    { label: "Dashboard", to: "/student", icon: LayoutDashboard },
    { label: "Face Enrollment", to: "/student/face-enrollment", icon: ScanFace },
    { label: "My Attendance", to: "/student/history", icon: ClipboardList },
  ],
};
