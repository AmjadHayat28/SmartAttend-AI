import type { AttendanceSession } from "./attendance";

export type RecognitionCategory = "confident" | "low_confidence" | "ambiguous" | "duplicate" | "no_match";
export type FaceDecision = "applied" | "manual_kept" | "pending" | "accepted" | "assigned" | "rejected" | "none";
export type RunStatus = "processing" | "completed" | "completed_with_warnings" | "failed";
/** The step a processing run is really on, as reported by the server. */
export type RunStage = "detecting" | "matching" | "saving";

export interface StudentRef {
  student_id: number;
  registration_no: string;
  full_name: string;
}

export interface RecognitionFace {
  id: number;
  image_id: number;
  image_width: number;
  image_height: number;
  face_index: number;
  bbox: { x: number; y: number; width: number; height: number };
  det_score: number;
  category: RecognitionCategory;
  suggested: StudentRef | null;
  similarity: number | null;
  second: StudentRef | null;
  second_similarity: number | null;
  is_primary: boolean;
  decision: FaceDecision;
  assigned: StudentRef | null;
}

export interface RecognitionRun {
  id: number;
  status: RunStatus;
  /** While processing: the server's current step and photos already analysed (null when finished). */
  stage: RunStage | null;
  images_processed: number;
  started_at: string;
  finished_at: string | null;
  started_by_name: string | null;
  model_name: string;
  model_version: string;
  thresholds: { confident: number; low: number; margin: number } | null;
  image_count: number;
  faces_detected: number;
  confident_count: number;
  low_confidence_count: number;
  ambiguous_count: number;
  duplicate_count: number;
  unknown_count: number;
  students_recognized: number;
  roster_size: number;
  eligible_count: number;
  applied_count: number;
  preserved_count: number;
  missing_students: StudentRef[];
  warnings: string[];
  /** Model/detector actually used (incl. fallback) and timings — never biometric data. */
  diagnostics: RecognitionDiagnostics | null;
  error_message: string | null;
}

export interface RecognitionDiagnostics {
  model: string;
  configured_model: string;
  fallback_from: string | null;
  detector: string;
  prepare_ms?: number;
  decode_ms?: number;
  detection_ms: number;
  detection_stages_ms?: { orient: number; full: number; tiles: number };
  recognition_ms: number;
  matching_ms: number;
  total_ms: number;
  images: { image_id: number; faces: number; rotation?: number; tiles?: number; merged_duplicates?: number }[];
}

export interface Recognition {
  run: RecognitionRun | null;
  faces: RecognitionFace[];
  can_run: boolean;
  can_decide: boolean;
}

export interface RecognitionAction {
  recognition: Recognition;
  session: AttendanceSession;
}

/**
 * Visual grouping of a face for overlays and lists:
 * matched = confident match / teacher-confirmed; review = waits for the teacher;
 * manual = the teacher had already marked this student, so their mark was kept;
 * unknown = no roster student matched (never shown as a student).
 */
export type FaceGroup = "matched" | "review" | "manual" | "unknown" | "dismissed";

export function faceGroup(f: RecognitionFace): FaceGroup {
  if (f.decision === "rejected") return "dismissed";
  if (f.decision === "manual_kept") return "manual";
  if (["applied", "accepted", "assigned"].includes(f.decision)) return "matched";
  if (f.decision === "pending") return "review";
  if (f.category === "confident") return "matched"; // secondary sighting of a matched student
  return "unknown";
}

export const GROUP_STYLE: Record<FaceGroup, { label: string; box: string; swatch: string; badge: "green" | "amber" | "gray" | "red" | "blue" }> = {
  matched: { label: "Confident match", box: "border-emerald-500", swatch: "border-emerald-500", badge: "green" },
  review: { label: "Needs review", box: "border-amber-400", swatch: "border-amber-400", badge: "amber" },
  manual: { label: "Marked by you", box: "border-sky-500", swatch: "border-sky-500", badge: "blue" },
  unknown: { label: "Unknown", box: "border-white/90 border-dashed", swatch: "border-slate-400 border-dashed", badge: "gray" },
  dismissed: { label: "Dismissed", box: "border-red-400 border-dashed opacity-70", swatch: "border-red-400 border-dashed", badge: "red" },
};

/** Truthful label for a processing run (no invented percentages). */
export function stageLabel(run: Pick<RecognitionRun, "stage" | "images_processed" | "image_count"> | null): string {
  if (!run || !run.stage) return "Preparing recognition…";
  if (run.stage === "detecting") {
    const current = Math.min(run.images_processed + 1, run.image_count);
    return run.image_count > 1 ? `Detecting faces — photo ${current} of ${run.image_count}…` : "Detecting faces…";
  }
  if (run.stage === "matching") return "Matching students…";
  return "Saving results…";
}
