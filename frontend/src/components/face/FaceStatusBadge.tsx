import type { FaceEnrollmentStatus } from "../../types/face";
import { Badge } from "../ui/Feedback";

const META: Record<FaceEnrollmentStatus, { label: string; tone: "gray" | "amber" | "blue" | "green" | "red" }> = {
  not_started: { label: "Not started", tone: "gray" },
  incomplete: { label: "Incomplete", tone: "amber" },
  pending_review: { label: "Ready for review", tone: "blue" },
  approved: { label: "Approved", tone: "green" },
  rejected: { label: "Retake required", tone: "red" },
};

export function faceStatusLabel(status: FaceEnrollmentStatus) {
  return META[status].label;
}

export function FaceStatusBadge({ status }: { status: FaceEnrollmentStatus }) {
  return <Badge tone={META[status].tone}>{META[status].label}</Badge>;
}
