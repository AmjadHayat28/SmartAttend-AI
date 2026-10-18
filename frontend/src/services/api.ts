import axios, { AxiosError, type InternalAxiosRequestConfig } from "axios";
import type { TokenResponse } from "../types/auth";
import { tokenStorage } from "./tokenStorage";

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL ?? "/api/v1",
  timeout: 30_000,
  // Lets the browser store/send the HttpOnly refresh cookie also when the API is on another origin.
  withCredentials: true,
});

/** Required by the API when refreshing with the cookie (a cross-site page cannot add it). */
const REFRESH_HEADERS = { "X-Requested-With": "SmartClass" };

api.interceptors.request.use((config) => {
  const token = tokenStorage.getAccess();
  if (token) config.headers.Authorization = `Bearer ${token}`;
  return config;
});

/** Called when refresh fails, so the auth context can drop the user to /login. */
let onSessionExpired: () => void = () => {};
export function setSessionExpiredHandler(handler: () => void) {
  onSessionExpired = handler;
}

// Single in-flight refresh shared by all requests that 401 at the same time.
let refreshPromise: Promise<string> | null = null;

async function refreshAccessToken(): Promise<string> {
  // The refresh cookie travels automatically; a token left in localStorage by an older version is
  // handed over once (the API then sets the cookie) and deleted.
  const legacy = tokenStorage.takeLegacyRefresh();
  const { data } = await axios.post<TokenResponse>(`${api.defaults.baseURL}/auth/refresh`, legacy ? { refresh_token: legacy } : {}, {
    withCredentials: true,
    headers: REFRESH_HEADERS,
  });
  tokenStorage.setAccess(data.access_token);
  return data.access_token;
}

/** On page load: get an access token from the refresh cookie. False = not signed in. */
export async function restoreSession(): Promise<boolean> {
  try {
    refreshPromise ??= refreshAccessToken().finally(() => (refreshPromise = null));
    await refreshPromise;
    return true;
  } catch {
    tokenStorage.clear();
    return false;
  }
}

/** Forget the session in this browser: the API removes the refresh cookie. */
export async function endSession(): Promise<void> {
  try {
    await axios.post(`${api.defaults.baseURL}/auth/logout`, null, { withCredentials: true });
  } finally {
    tokenStorage.clear();
  }
}

api.interceptors.response.use(
  (response) => response,
  async (error: AxiosError) => {
    const original = error.config as (InternalAxiosRequestConfig & { _retried?: boolean }) | undefined;
    const isAuthCall = ["/auth/login", "/auth/refresh", "/auth/onboarding-token"].some((p) => original?.url?.startsWith(p));
    if (error.response?.status !== 401 || !original || original._retried || isAuthCall) {
      throw error;
    }
    original._retried = true;
    try {
      refreshPromise ??= refreshAccessToken().finally(() => (refreshPromise = null));
      const token = await refreshPromise;
      original.headers.Authorization = `Bearer ${token}`;
      return api(original);
    } catch {
      tokenStorage.clear();
      onSessionExpired();
      throw error;
    }
  },
);

/** Turn any API error into a human-readable message. */
export function getErrorMessage(error: unknown, fallback = "Something went wrong. Please try again."): string {
  if (axios.isAxiosError(error)) {
    if (!error.response) return "Cannot reach the server. Check that the backend is running.";
    const detail = (error.response.data as { detail?: unknown } | undefined)?.detail;
    if (typeof detail === "string") return detail;
    // FastAPI validation errors: [{ loc, msg }]
    if (Array.isArray(detail) && detail.length) {
      return detail
        .map((d: { loc?: (string | number)[]; msg?: string }) => {
          const field = d.loc?.filter((p) => p !== "body").join(".");
          return field ? `${field}: ${d.msg}` : d.msg;
        })
        .join("; ");
    }
  }
  return fallback;
}
