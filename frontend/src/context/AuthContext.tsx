import { createContext, useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { endSession, restoreSession, setSessionExpiredHandler } from "../services/api";
import { authService } from "../services/authService";
import { tokenStorage } from "../services/tokenStorage";
import type { LoginPayload, UserProfile } from "../types/auth";

export interface AuthContextValue {
  user: UserProfile | null;
  /** True while the stored session is being restored on first load. */
  initializing: boolean;
  login: (payload: LoginPayload) => Promise<UserProfile>;
  logout: () => void;
}

export const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<UserProfile | null>(null);
  const [initializing, setInitializing] = useState(true);

  const logout = useCallback(() => {
    setUser(null);
    void endSession().catch(() => undefined);
  }, []);

  useEffect(() => {
    setSessionExpiredHandler(() => setUser(null));
    // The refresh cookie (if any) is exchanged for an access token; no cookie = signed out.
    restoreSession()
      .then((ok) => (ok ? authService.me().then(setUser) : undefined))
      .catch(() => tokenStorage.clear())
      .finally(() => setInitializing(false));
  }, []);

  const login = useCallback(async (payload: LoginPayload) => {
    const data = await authService.login(payload);
    tokenStorage.setAccess(data.access_token);
    setUser(data.user);
    return data.user;
  }, []);

  const value = useMemo(() => ({ user, initializing, login, logout }), [user, initializing, login, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
