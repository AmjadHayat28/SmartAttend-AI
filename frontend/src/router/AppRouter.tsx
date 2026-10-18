import { Navigate, Route, Routes } from "react-router-dom";
import { GuestRoute, ProtectedRoute } from "../components/auth/RouteGuards";
import { useAuth } from "../hooks/useAuth";
import { AuthLayout } from "../layouts/AuthLayout";
import { DashboardLayout } from "../layouts/DashboardLayout";
import { AdminDashboard } from "../pages/admin/AdminDashboard";
import { DepartmentsPage } from "../pages/admin/DepartmentsPage";
import { LoginPage } from "../pages/auth/LoginPage";
import { OnboardingPage } from "../pages/auth/OnboardingPage";
import { RegisterStudentPage } from "../pages/auth/RegisterStudentPage";
import { ApprovalsPage } from "../pages/common/ApprovalsPage";
import { AttendanceSessionPage } from "../pages/common/AttendanceSessionPage";
import { AttendanceSessionsPage } from "../pages/common/AttendanceSessionsPage";
import { AssignmentsPage } from "../pages/manage/AssignmentsPage";
import { BatchesPage } from "../pages/manage/BatchesPage";
import { CoursesPage } from "../pages/manage/CoursesPage";
import { FaceReviewPage } from "../pages/manage/FaceReviewPage";
import { HodsPage } from "../pages/manage/HodsPage";
import { SectionsPage } from "../pages/manage/SectionsPage";
import { SemestersPage } from "../pages/manage/SemestersPage";
import { StudentsPage } from "../pages/manage/StudentsPage";
import { TeachersPage } from "../pages/manage/TeachersPage";
import { NotFoundPage, UnauthorizedPage } from "../pages/common/StatusPages";
import { HodDashboard } from "../pages/hod/HodDashboard";
import { FaceEnrollmentPage } from "../pages/student/FaceEnrollmentPage";
import { MyAttendancePage } from "../pages/student/MyAttendancePage";
import { MySubjectAttendancePage } from "../pages/student/MySubjectAttendancePage";
import { StudentDashboard } from "../pages/student/StudentDashboard";
import { ClassEnrollmentsPage } from "../pages/teacher/ClassEnrollmentsPage";
import { TakeAttendancePage } from "../pages/teacher/TakeAttendancePage";
import { TeacherReportsPage } from "../pages/teacher/TeacherReportsPage";
import { TeacherDashboard } from "../pages/teacher/TeacherDashboard";
import { ROLE_HOME } from "../types/auth";

/** The HOD's department management pages (/hod/...). Attendance sessions are teacher-only. */
function hodRoutes(base: string) {
  const pages = [
    ["teachers", <TeachersPage />],
    ["students", <StudentsPage />],
    ["batches", <BatchesPage />],
    ["semesters", <SemestersPage />],
    ["sections", <SectionsPage />],
    ["courses", <CoursesPage />],
    ["assignments", <AssignmentsPage />],
    ["face-review", <FaceReviewPage />],
  ] as const;
  return pages.map(([path, element]) => <Route key={path} path={`${base}/${path}`} element={element} />);
}

function RootRedirect() {
  const { user, initializing } = useAuth();
  if (initializing) return null;
  return <Navigate to={user ? ROLE_HOME[user.role] : "/login"} replace />;
}

export function AppRouter() {
  return (
    <Routes>
      <Route path="/" element={<RootRedirect />} />

      <Route element={<GuestRoute />}>
        <Route element={<AuthLayout />}>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/register" element={<RegisterStudentPage />} />
        </Route>
        {/* Registration step 2 (pending students, onboarding token) — full-width layout */}
        <Route path="/register/photos" element={<OnboardingPage />} />
      </Route>

      <Route element={<ProtectedRoute roles={["super_admin"]} />}>
        <Route element={<DashboardLayout />}>
          <Route path="/admin" element={<AdminDashboard />} />
          <Route path="/admin/departments" element={<DepartmentsPage />} />
          <Route path="/admin/hods" element={<HodsPage />} />
          {/* System administration only: staff accounts — no assignments, students or attendance. */}
          <Route path="/admin/teachers" element={<TeachersPage />} />
        </Route>
      </Route>

      <Route element={<ProtectedRoute roles={["hod"]} />}>
        <Route element={<DashboardLayout />}>
          <Route path="/hod" element={<HodDashboard />} />
          <Route path="/hod/approvals" element={<ApprovalsPage />} />
          {hodRoutes("/hod")}
        </Route>
      </Route>

      <Route element={<ProtectedRoute roles={["teacher"]} />}>
        <Route element={<DashboardLayout />}>
          <Route path="/teacher" element={<TeacherDashboard />} />
          <Route path="/teacher/attendance/new" element={<TakeAttendancePage />} />
          <Route path="/teacher/attendance/:id" element={<AttendanceSessionPage />} />
          <Route path="/teacher/history" element={<AttendanceSessionsPage />} />
          <Route path="/teacher/enrollments" element={<ClassEnrollmentsPage />} />
          <Route path="/teacher/reports" element={<TeacherReportsPage />} />
        </Route>
      </Route>

      <Route element={<ProtectedRoute roles={["student"]} />}>
        <Route element={<DashboardLayout />}>
          <Route path="/student" element={<StudentDashboard />} />
          <Route path="/student/face-enrollment" element={<FaceEnrollmentPage />} />
          <Route path="/student/history" element={<MyAttendancePage />} />
          <Route path="/student/history/:courseId" element={<MySubjectAttendancePage />} />
        </Route>
      </Route>

      <Route path="/unauthorized" element={<UnauthorizedPage />} />
      <Route path="*" element={<NotFoundPage />} />
    </Routes>
  );
}
