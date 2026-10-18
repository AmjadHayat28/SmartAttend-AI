import { ScanFace } from "lucide-react";
import { Link } from "react-router-dom";
import { useAsync } from "../../hooks/useAsync";
import { myEnrollment } from "../../services/faceEnrollmentService";
import { Card } from "../ui/Card";
import { FaceStatusBadge } from "./FaceStatusBadge";

const NEXT_STEP = {
  not_started: "Add your face photos so you can be recognised in classroom attendance photos.",
  incomplete: "Finish adding your front, left and right photos, then submit them for review.",
  pending_review: "Your photos are waiting for review by your department.",
  rejected: "Your department asked for new photos — see their note and retake.",
  approved: "",
} as const;

/** Dashboard prompt shown until the student's face enrollment is approved. */
export function FaceEnrollmentBanner() {
  const { data } = useAsync(() => myEnrollment.get());
  if (!data || data.status === "approved") return null;
  return (
    <Card className="mb-4 flex flex-wrap items-center gap-4 p-4">
      <span className="rounded-lg bg-brand-50 p-2.5 text-brand-700 dark:bg-brand-900/40 dark:text-brand-200">
        <ScanFace className="h-5 w-5" />
      </span>
      <div className="min-w-0 flex-1">
        <p className="flex flex-wrap items-center gap-2 font-medium text-slate-900 dark:text-white">
          Face enrollment <FaceStatusBadge status={data.status} />
        </p>
        <p className="text-sm text-slate-600 dark:text-slate-300">{NEXT_STEP[data.status]}</p>
      </div>
      <Link to="/student/face-enrollment" className="inline-flex h-9 items-center rounded-lg bg-brand-700 px-4 text-sm font-medium text-white hover:bg-brand-800">
        {data.status === "pending_review" ? "View" : "Open"}
      </Link>
    </Card>
  );
}
