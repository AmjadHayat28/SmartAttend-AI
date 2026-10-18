import type { LoginPayload, StudentRegisterPayload, TokenResponse, UserProfile } from "../types/auth";
import type { DepartmentTree } from "../types/api";
import { api } from "./api";

export const authService = {
  async login(payload: LoginPayload) {
    const { data } = await api.post<TokenResponse>("/auth/login", payload);
    return data;
  },
  async me() {
    const { data } = await api.get<UserProfile>("/auth/me");
    return data;
  },
  async registerStudent(payload: StudentRegisterPayload) {
    const { data } = await api.post<{ message: string; onboarding_token: string; expires_in: number }>("/auth/register/student", payload);
    return data;
  },
  async changePassword(current_password: string, new_password: string) {
    const { data } = await api.post<{ message: string }>("/auth/change-password", {
      current_password,
      new_password,
    });
    return data;
  },
  async academicStructure() {
    const { data } = await api.get<DepartmentTree[]>("/public/academic-structure");
    return data;
  },
};
