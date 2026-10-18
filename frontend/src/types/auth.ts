export type UserRole = "super_admin" | "hod" | "teacher" | "student";
export type AccountStatus = "pending" | "active" | "suspended" | "rejected";

export interface UserProfile {
  id: number;
  email: string;
  full_name: string;
  role: UserRole;
  status: AccountStatus;
  department_id: number | null;
  department_name: string | null;
  last_login_at: string | null;
  employee_id: string | null;
  registration_no: string | null;
}

export interface TokenResponse {
  access_token: string;
  /** Always null: the refresh token is an HttpOnly cookie the page never sees. */
  refresh_token: string | null;
  token_type: "bearer";
  expires_in: number;
  user: UserProfile;
}

export interface LoginPayload {
  email: string;
  password: string;
}

export interface StudentRegisterPayload {
  full_name: string;
  registration_no: string;
  email: string;
  password: string;
  department_id: number;
  batch_id: number;
  semester_id: number;
  section_id: number;
}

export const ROLE_LABELS: Record<UserRole, string> = {
  super_admin: "Super Admin",
  hod: "Head of Department",
  teacher: "Teacher",
  student: "Student",
};

/** Landing route for each role after login. */
export const ROLE_HOME: Record<UserRole, string> = {
  super_admin: "/admin",
  hod: "/hod",
  teacher: "/teacher",
  student: "/student",
};
