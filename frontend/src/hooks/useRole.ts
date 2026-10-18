import { useAuth } from "./useAuth";

/** Convenience flags for role-dependent UI. The API enforces the real rules. */
export function useRole() {
  const { user } = useAuth();
  return { isAdmin: user?.role === "super_admin", isHod: user?.role === "hod", user };
}
