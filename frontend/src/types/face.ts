import type { AccountStatus } from "./auth";

export type FacePose = "front" | "left" | "right" | "extra";
export type FaceEnrollmentStatus = "not_started" | "incomplete" | "pending_review" | "approved" | "rejected";
export type CheckStatus = "pass" | "warning" | "fail";

export interface QualityCheck {
  check: string;
  status: CheckStatus;
  message: string | null;
  value: number;
}

export interface FacePhoto {
  id: number;
  pose: FacePose;
  validation_status: CheckStatus;
  validation_message: string | null;
  checks: QualityCheck[];
  width: number | null;
  height: number | null;
  file_size: number | null;
  uploaded_at: string;
  updated_at: string;
  reviewed_at: string | null;
  /** API-relative; must be fetched with the Authorization header. */
  image_url: string;
}

export interface FaceEnrollment {
  student_id: number;
  status: FaceEnrollmentStatus;
  requirements_met: boolean;
  missing_poses: FacePose[];
  photo_count: number;
  max_photos: number;
  max_extra_photos: number;
  can_edit: boolean;
  can_submit: boolean;
  photos: FacePhoto[];
  profile_photo_url: string | null;
  profile_photo_updated_at: string | null;
  submitted_at: string | null;
  reviewed_at: string | null;
  reviewed_by_name: string | null;
  review_note: string | null;
}

export interface FaceEnrollmentDetail extends FaceEnrollment {
  user_id: number;
  full_name: string;
  email: string;
  registration_no: string;
  account_status: AccountStatus;
  department_id: number;
  department_name: string;
  department_code: string;
  batch_name: string;
  semester_name: string;
  section_name: string;
}

export interface FaceEnrollmentListItem {
  student_id: number;
  user_id: number;
  full_name: string;
  registration_no: string;
  account_status: AccountStatus;
  department_id: number;
  department_code: string;
  batch_name: string;
  semester_name: string;
  section_name: string;
  status: FaceEnrollmentStatus;
  photo_count: number;
  requirements_met: boolean;
  has_profile_photo: boolean;
  submitted_at: string | null;
  reviewed_at: string | null;
}

export const POSE_LABELS: Record<FacePose, string> = {
  front: "Front",
  left: "Slight left",
  right: "Slight right",
  extra: "Extra",
};

export const POSE_HINTS: Record<FacePose, string> = {
  front: "Look straight at the camera, face fully visible.",
  left: "Turn your head slightly to your left (about 15–20°).",
  right: "Turn your head slightly to your right (about 15–20°).",
  extra: "Optional: another front photo in different lighting, or another angle.",
};
