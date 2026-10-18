import { Camera, CheckCircle2, CircleAlert, Clock, Lock, ScanFace, Send, Trash2, UserRound } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { useToast } from "../../context/ToastContext";
import { getErrorMessage } from "../../services/api";
import type { EnrollmentClient } from "../../services/faceEnrollmentService";
import { POSE_HINTS, POSE_LABELS, type FaceEnrollment, type FacePhoto, type FacePose } from "../../types/face";
import { cn } from "../../utils/cn";
import { formatDateTime } from "../../utils/format";
import { Button } from "../ui/Button";
import { Card, CardHeader } from "../ui/Card";
import { ConfirmDialog } from "../ui/ConfirmDialog";
import { Alert, Badge, ErrorState, Spinner } from "../ui/Feedback";
import { AuthedImage } from "./AuthedImage";
import { CameraCapture } from "./CameraCapture";
import { MAX_UPLOAD_MB } from "../../config/uploads";
import { FaceStatusBadge } from "./FaceStatusBadge";

const MAX_MB = MAX_UPLOAD_MB;
const ACCEPT = "image/jpeg,image/png";

/** Client-side pre-check for fast feedback only — the server validates everything again. */
function precheck(file: Blob): string | null {
  if (!["image/jpeg", "image/png"].includes(file.type)) return "Please choose a JPEG or PNG photo.";
  if (file.size > MAX_MB * 1024 * 1024) return `The photo is larger than ${MAX_MB} MB.`;
  return null;
}

interface Slot {
  key: string;
  pose: FacePose;
  photo: FacePhoto | null;
  required: boolean;
}

function buildSlots(data: FaceEnrollment): Slot[] {
  const byPose = (pose: FacePose) => data.photos.filter((p) => p.pose === pose);
  const extras = byPose("extra");
  return [
    ...(["front", "left", "right"] as const).map((pose) => ({ key: pose, pose, photo: byPose(pose)[0] ?? null, required: true })),
    ...Array.from({ length: data.max_extra_photos }, (_, i) => ({ key: `extra-${i}`, pose: "extra" as const, photo: extras[i] ?? null, required: false })),
  ];
}

const STATUS_COPY = {
  not_started: { icon: ScanFace, tone: "info", text: "Add a front, slight-left and slight-right photo of your face, then submit them for review." },
  incomplete: { icon: CircleAlert, tone: "warning", text: "" },
  pending_review: { icon: Clock, tone: "info", text: "Your photos are waiting for review by your department. Changing a photo now withdraws the submission." },
  approved: { icon: CheckCircle2, tone: "info", text: "Your face enrollment is approved. Photos are locked; ask your department if they need to change." },
  rejected: { icon: CircleAlert, tone: "error", text: "" },
} as const;

/** The student's profile photo + face-enrollment workspace. Works with either API client. */
export function FaceEnrollmentPanel({ client, onSubmitted }: { client: EnrollmentClient; onSubmitted?: () => void }) {
  const toast = useToast();
  const [data, setData] = useState<FaceEnrollment | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [busy, setBusy] = useState<Record<string, number>>({}); // slot key → upload %
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [camera, setCamera] = useState<{ key: string; title: string; hint: string; onShot: (b: Blob) => void } | null>(null);
  const [deleting, setDeleting] = useState<FacePhoto | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [confirmSubmit, setConfirmSubmit] = useState(false);

  const load = useCallback(() => {
    setLoadError(null);
    client.get().then(setData).catch((err) => setLoadError(getErrorMessage(err)));
  }, [client]);

  useEffect(load, [load]);

  async function run(key: string, file: Blob, action: (onProgress: (p: number) => void) => Promise<unknown>, success: string) {
    const problem = precheck(file);
    setErrors((e) => ({ ...e, [key]: problem ?? "" }));
    if (problem) return;
    setBusy((b) => ({ ...b, [key]: 0 }));
    try {
      await action((p) => setBusy((b) => ({ ...b, [key]: p })));
      toast.success(success);
      load();
    } catch (err) {
      setErrors((e) => ({ ...e, [key]: getErrorMessage(err, "Upload failed") }));
    } finally {
      setBusy((b) => {
        const { [key]: _done, ...rest } = b;
        void _done;
        return rest;
      });
    }
  }

  function uploadSlot(slot: Slot, file: Blob) {
    const label = POSE_LABELS[slot.pose].toLowerCase();
    return slot.photo
      ? run(slot.key, file, (p) => client.replaceFace(slot.photo!.id, file, p), `Your ${label} photo was replaced.`)
      : run(slot.key, file, (p) => client.uploadFace(slot.pose, file, p), `Your ${label} photo was added.`);
  }

  async function remove() {
    if (!deleting) return;
    try {
      setData(await client.deleteFace(deleting.id));
      toast.success(`${POSE_LABELS[deleting.pose]} photo deleted.`);
      setDeleting(null);
    } catch (err) {
      toast.error(getErrorMessage(err));
    }
  }

  async function submit() {
    setSubmitting(true);
    try {
      setData(await client.submit());
      toast.success("Submitted for review. You'll see the result here.");
      setConfirmSubmit(false);
      onSubmitted?.();
    } catch (err) {
      toast.error(getErrorMessage(err));
    } finally {
      setSubmitting(false);
    }
  }

  if (loadError) return <Card><ErrorState message={loadError} onRetry={load} /></Card>;
  if (!data) return <Spinner label="Loading your enrollment…" />;

  const slots = buildSlots(data);
  const copy = STATUS_COPY[data.status];
  const missingText = data.missing_poses.length
    ? `Still needed: ${data.missing_poses.map((p) => POSE_LABELS[p].toLowerCase()).join(", ")}.`
    : "All required photos are in place — submit them for review.";

  return (
    <div className="space-y-6">
      {/* Status */}
      <Card className="p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex min-w-0 items-start gap-3">
            <copy.icon className={cn("mt-0.5 h-5 w-5 shrink-0", data.status === "rejected" ? "text-red-600" : data.status === "approved" ? "text-emerald-600" : "text-brand-700 dark:text-brand-200")} />
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="font-semibold text-slate-900 dark:text-white">Face enrollment</h2>
                <FaceStatusBadge status={data.status} />
              </div>
              <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">{copy.text || missingText}</p>
              {data.status === "rejected" && data.review_note && (
                <div className="mt-3">
                  <Alert>
                    <span className="font-medium">Retake requested{data.reviewed_by_name ? ` by ${data.reviewed_by_name}` : ""}:</span> {data.review_note}
                  </Alert>
                </div>
              )}
              {data.status === "rejected" && <p className="mt-2 text-sm text-slate-500">Replace the photos mentioned, then submit again. {missingText}</p>}
              {data.submitted_at && data.status === "pending_review" && <p className="mt-1 text-xs text-slate-500">Submitted {formatDateTime(data.submitted_at)}</p>}
            </div>
          </div>
          {data.can_edit && data.status !== "pending_review" && (
            <Button onClick={() => setConfirmSubmit(true)} disabled={!data.can_submit} title={data.can_submit ? undefined : missingText}>
              <Send className="h-4 w-4" /> Submit for review
            </Button>
          )}
        </div>
        <ol className="mt-4 grid grid-cols-3 gap-2" aria-label="Required photos">
          {(["front", "left", "right"] as const).map((pose) => {
            const done = !data.missing_poses.includes(pose);
            return (
              <li key={pose} className={cn("flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-xs font-medium sm:text-sm", done ? "bg-emerald-50 text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300" : "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300")}>
                {done ? <CheckCircle2 className="h-4 w-4 shrink-0" /> : <CircleAlert className="h-4 w-4 shrink-0" />}
                <span className="truncate">{pose === "front" ? "Front" : pose === "left" ? "Left" : "Right"}</span>
                <span className="sr-only">{done ? "uploaded" : "missing"}</span>
              </li>
            );
          })}
        </ol>
      </Card>

      <div className="grid gap-6 lg:grid-cols-[18rem_minmax(0,1fr)]">
        {/* Profile photo */}
        <Card className="h-fit">
          <CardHeader title="Profile photo" description="Shown to your department and teachers." />
          <div className="space-y-3 p-5">
            <div className="mx-auto w-40">
              {data.profile_photo_url ? (
                <AuthedImage src={data.profile_photo_url} http={client.http} alt="Your profile photo" className="aspect-square w-40 rounded-full" />
              ) : (
                <div className="grid aspect-square w-40 place-items-center rounded-full bg-slate-100 text-slate-400 dark:bg-slate-800">
                  <UserRound className="h-16 w-16" />
                </div>
              )}
            </div>
            <SlotProgress percent={busy.profile} />
            {errors.profile && <Alert>{errors.profile}</Alert>}
            <PhotoSourceButtons
              label={data.profile_photo_url ? "Change photo" : "Add photo"}
              disabled={"profile" in busy}
              onFile={(f) => run("profile", f, (p) => client.uploadProfile(f, p), "Profile photo saved.")}
              onCamera={() => setCamera({ key: "profile", title: "Profile photo", hint: "Centre your face and shoulders.", onShot: (b) => run("profile", b, (p) => client.uploadProfile(b, p), "Profile photo saved.") })}
            />
          </div>
        </Card>

        {/* Face photos */}
        <Card>
          <CardHeader title="Face registration photos" description={`${data.photo_count} of ${data.max_photos} used · one face only, good light, no sunglasses or masks`} />
          <ul className="grid gap-4 p-5 sm:grid-cols-2 xl:grid-cols-3">
            {slots.map((slot) => (
              <li key={slot.key} className={cn("flex flex-col rounded-xl border p-3", slot.photo ? "border-slate-200 dark:border-slate-700" : slot.required ? "border-dashed border-amber-300 dark:border-amber-800" : "border-dashed border-slate-300 dark:border-slate-700")}>
                <div className="mb-2 flex items-center justify-between gap-2">
                  <span className="font-medium text-slate-900 dark:text-white">{POSE_LABELS[slot.pose]}</span>
                  {slot.photo ? (
                    <Badge tone={slot.photo.validation_status === "pass" ? "green" : "amber"}>{slot.photo.validation_status === "pass" ? "Uploaded" : "Uploaded · check"}</Badge>
                  ) : (
                    <Badge tone={slot.required ? "amber" : "gray"}>{slot.required ? "Missing" : "Optional"}</Badge>
                  )}
                </div>
                {slot.photo ? (
                  <AuthedImage src={slot.photo.image_url} http={client.http} alt={`${POSE_LABELS[slot.pose]} face photo`} className="aspect-[4/3] w-full rounded-lg" />
                ) : (
                  <div className="grid aspect-[4/3] place-items-center rounded-lg bg-slate-50 px-4 text-center text-xs text-slate-500 dark:bg-slate-800/50 dark:text-slate-400">
                    {POSE_HINTS[slot.pose]}
                  </div>
                )}
                {slot.photo?.validation_message && <p className="mt-2 text-xs text-amber-700 dark:text-amber-300">{slot.photo.validation_message}</p>}
                {slot.photo && <p className="mt-1 text-xs text-slate-500">Uploaded {formatDateTime(slot.photo.updated_at)}</p>}
                <SlotProgress percent={busy[slot.key]} />
                {errors[slot.key] && <p className="mt-2 text-sm text-red-600 dark:text-red-400" role="alert">{errors[slot.key]}</p>}
                <div className="mt-auto pt-3">
                  {data.can_edit ? (
                    <div className="flex items-center gap-2">
                      <PhotoSourceButtons
                        label={slot.photo ? "Replace" : "Upload"}
                        compact
                        disabled={slot.key in busy || (!slot.photo && data.photo_count >= data.max_photos)}
                        onFile={(f) => uploadSlot(slot, f)}
                        onCamera={() => setCamera({ key: slot.key, title: `${POSE_LABELS[slot.pose]} photo`, hint: POSE_HINTS[slot.pose], onShot: (b) => uploadSlot(slot, b) })}
                      />
                      {slot.photo && (
                        <Button size="sm" variant="ghost" onClick={() => setDeleting(slot.photo)} aria-label={`Delete ${POSE_LABELS[slot.pose]} photo`} disabled={slot.key in busy}>
                          <Trash2 className="h-4 w-4 text-red-600" />
                        </Button>
                      )}
                    </div>
                  ) : (
                    <p className="flex items-center gap-1.5 text-xs text-slate-500">
                      <Lock className="h-3.5 w-3.5" /> Locked after approval
                    </p>
                  )}
                </div>
              </li>
            ))}
          </ul>
        </Card>
      </div>

      <CameraCapture
        open={!!camera}
        title={camera?.title ?? ""}
        hint={camera?.hint}
        onClose={() => setCamera(null)}
        onCapture={(blob) => camera?.onShot(blob)}
      />
      <ConfirmDialog
        open={!!deleting}
        title={`Delete ${deleting ? POSE_LABELS[deleting.pose].toLowerCase() : ""} photo?`}
        description={data.status === "pending_review" ? "This withdraws your submission; you'll need to submit again." : "You can upload a new one afterwards."}
        confirmLabel="Delete"
        tone="danger"
        onConfirm={remove}
        onCancel={() => setDeleting(null)}
      />
      <ConfirmDialog
        open={confirmSubmit}
        title="Submit photos for review?"
        description="Your department will check that the photos clearly show you. You can still change them until they are reviewed."
        confirmLabel="Submit"
        loading={submitting}
        onConfirm={submit}
        onCancel={() => setConfirmSubmit(false)}
      />
    </div>
  );
}

function SlotProgress({ percent }: { percent: number | undefined }) {
  if (percent === undefined) return null;
  return (
    <div className="mt-2" role="progressbar" aria-valuenow={percent} aria-valuemin={0} aria-valuemax={100} aria-label="Upload progress">
      <div className="h-1.5 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700">
        <div className="h-full rounded-full bg-brand-600 transition-all" style={{ width: `${Math.max(percent, 5)}%` }} />
      </div>
      <p className="mt-1 text-xs text-slate-500">{percent < 100 ? `Uploading… ${percent}%` : "Checking photo…"}</p>
    </div>
  );
}

function PhotoSourceButtons({ label, onFile, onCamera, disabled, compact }: { label: string; onFile: (f: File) => void; onCamera: () => void; disabled?: boolean; compact?: boolean }) {
  const input = useRef<HTMLInputElement>(null);
  return (
    <div className={cn("flex gap-2", compact ? "" : "justify-center")}>
      <input
        ref={input}
        type="file"
        accept={ACCEPT}
        className="hidden"
        onChange={(e) => {
          const file = e.target.files?.[0];
          e.target.value = ""; // allow picking the same file again after an error
          if (file) onFile(file);
        }}
      />
      <Button type="button" size="sm" variant="secondary" disabled={disabled} onClick={() => input.current?.click()}>
        {label}
      </Button>
      <Button type="button" size="sm" variant="secondary" disabled={disabled} onClick={onCamera} aria-label={`${label} with camera`}>
        <Camera className="h-4 w-4" /> Camera
      </Button>
    </div>
  );
}
