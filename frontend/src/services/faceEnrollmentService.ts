import axios, { type AxiosInstance, type AxiosProgressEvent } from "axios";
import type { ListParams, Page } from "../types/api";
import type { FaceEnrollment, FaceEnrollmentDetail, FaceEnrollmentListItem, FacePhoto, FacePose } from "../types/face";
import { api } from "./api";

type Progress = (percent: number) => void;

function form(file: Blob, extra: Record<string, string> = {}) {
  const data = new FormData();
  // The filename is ignored by the server (it stores a random UUID name); send a neutral one.
  data.append("file", file, file.type === "image/png" ? "photo.png" : "photo.jpg");
  for (const [k, v] of Object.entries(extra)) data.append(k, v);
  return data;
}

const progress = (cb?: Progress) => (e: AxiosProgressEvent) => cb?.(e.total ? Math.round((e.loaded / e.total) * 100) : 0);

/**
 * The student's own enrollment API. `http` is the normal signed-in client, or the onboarding
 * client for a newly registered (pending) student — the endpoints are the same.
 */
export function createEnrollmentClient(http: AxiosInstance) {
  return {
    http,
    get: () => http.get<FaceEnrollment>("/me/face-enrollment").then((r) => r.data),
    uploadProfile: (file: Blob, onProgress?: Progress) =>
      http.put<FaceEnrollment>("/me/profile-photo", form(file), { onUploadProgress: progress(onProgress) }).then((r) => r.data),
    uploadFace: (pose: FacePose, file: Blob, onProgress?: Progress) =>
      http.post<FacePhoto>("/me/face-photos", form(file, { pose }), { onUploadProgress: progress(onProgress) }).then((r) => r.data),
    replaceFace: (photoId: number, file: Blob, onProgress?: Progress) =>
      http.put<FacePhoto>(`/me/face-photos/${photoId}`, form(file), { onUploadProgress: progress(onProgress) }).then((r) => r.data),
    deleteFace: (photoId: number) => http.delete<FaceEnrollment>(`/me/face-photos/${photoId}`).then((r) => r.data),
    submit: () => http.post<FaceEnrollment>("/me/face-enrollment/submit").then((r) => r.data),
  };
}

export type EnrollmentClient = ReturnType<typeof createEnrollmentClient>;

export const myEnrollment = createEnrollmentClient(api);

/** Reviewer API (super admin / HOD). */
export const faceReviewApi = {
  list: (params?: ListParams) =>
    api
      .get<Page<FaceEnrollmentListItem>>("/face-enrollments", {
        params: Object.fromEntries(Object.entries(params ?? {}).filter(([, v]) => v !== "" && v !== undefined && v !== null)),
      })
      .then((r) => r.data),
  get: (studentId: number) => api.get<FaceEnrollmentDetail>(`/face-enrollments/${studentId}`).then((r) => r.data),
  approve: (studentId: number) => api.post<FaceEnrollmentDetail>(`/face-enrollments/${studentId}/approve`).then((r) => r.data),
  reject: (studentId: number, reason: string) =>
    api.post<FaceEnrollmentDetail>(`/face-enrollments/${studentId}/reject`, { reason }).then((r) => r.data),
};

// ── Onboarding (pending students) ──────────────────────────────────────────

const ONBOARDING_KEY = "sc_onboarding";

export const onboardingToken = {
  get: () => {
    try {
      return sessionStorage.getItem(ONBOARDING_KEY);
    } catch {
      return null;
    }
  },
  set: (token: string) => {
    try {
      sessionStorage.setItem(ONBOARDING_KEY, token);
    } catch {
      /* storage unavailable: the token lives only for this page */
    }
  },
  clear: () => {
    try {
      sessionStorage.removeItem(ONBOARDING_KEY);
    } catch {
      /* ignore */
    }
  },
};

/** Axios client authenticated with the short-lived onboarding token (no refresh). */
export function createOnboardingHttp(token: string) {
  const http = axios.create({ baseURL: import.meta.env.VITE_API_BASE_URL ?? "/api/v1", timeout: 60_000 });
  http.interceptors.request.use((config) => {
    config.headers.Authorization = `Bearer ${token}`;
    return config;
  });
  return http;
}

export async function requestOnboardingToken(email: string, password: string) {
  const { data } = await api.post<{ onboarding_token: string }>("/auth/onboarding-token", { email, password });
  return data.onboarding_token;
}
