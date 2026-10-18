import { Camera, ImagePlus, Trash2 } from "lucide-react";
import { useRef, useState } from "react";
import { useToast } from "../../context/ToastContext";
import { getErrorMessage } from "../../services/api";
import { attendanceApi } from "../../services/attendanceService";
import type { AttendanceSession, SessionImage } from "../../types/attendance";
import { formatDateTime } from "../../utils/format";
import { CameraCapture } from "../face/CameraCapture";
import { AuthedImage } from "../face/AuthedImage";
import { Button } from "../ui/Button";
import { Card, CardHeader } from "../ui/Card";
import { ConfirmDialog } from "../ui/ConfirmDialog";
import { MAX_UPLOAD_BYTES, MAX_UPLOAD_MB } from "../../config/uploads";
import { Modal } from "../ui/Modal";

interface ClassroomPhotosProps {
  session: AttendanceSession;
  editable: boolean;
  onChanged?: (session: AttendanceSession) => void;
}

/**
 * Classroom photos are stored as attendance evidence (and as Phase 6 input).
 * Nothing is detected or recognised here.
 */
export function ClassroomPhotos({ session, editable, onChanged }: ClassroomPhotosProps) {
  const toast = useToast();
  const input = useRef<HTMLInputElement>(null);
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [camera, setCamera] = useState(false);
  const [viewing, setViewing] = useState<SessionImage | null>(null);
  const [removing, setRemoving] = useState<SessionImage | null>(null);
  const full = session.images.length >= session.max_photos;

  async function upload(files: Blob[]) {
    setError(null);
    for (const file of files) {
      if (!["image/jpeg", "image/png"].includes(file.type)) {
        setError("Please choose JPEG or PNG photos.");
        continue;
      }
      if (file.size > MAX_UPLOAD_BYTES) {
        setError(`This photo is larger than ${MAX_UPLOAD_MB} MB. Use the camera's standard photo size.`);
        continue;
      }
      setProgress(0);
      try {
        onChanged?.(await attendanceApi.uploadImage(session.id, file, setProgress));
        toast.success("Classroom photo added.");
      } catch (err) {
        setError(getErrorMessage(err, "Upload failed"));
        break;
      } finally {
        setProgress(null);
      }
    }
  }

  async function remove() {
    if (!removing) return;
    try {
      onChanged?.(await attendanceApi.removeImage(session.id, removing.id));
      toast.success("Photo removed.");
      setRemoving(null);
    } catch (err) {
      toast.error(getErrorMessage(err));
    }
  }

  return (
    <Card>
      <CardHeader title="Classroom photos" description={`${session.images.length} of ${session.max_photos} · stored as evidence`} />
      <div className="space-y-3 p-4">
        {session.images.length === 0 && <p className="text-sm text-slate-500">{editable ? "Add a photo of the class — front, back rows, sides." : "No classroom photos."}</p>}
        <ul className="grid grid-cols-2 gap-2">
          {session.images.map((img, i) => (
            <li key={img.id} className="group relative">
              <button type="button" onClick={() => setViewing(img)} className="block w-full overflow-hidden rounded-lg focus-visible:outline-2 focus-visible:outline-brand-600" aria-label={`View classroom photo ${i + 1}`}>
                <AuthedImage src={img.image_url} alt={`Classroom photo ${i + 1}`} className="aspect-[4/3] w-full rounded-lg" />
              </button>
              {editable && (
                <button type="button" onClick={() => setRemoving(img)} className="absolute right-1.5 top-1.5 rounded-md bg-white/90 p-1.5 text-red-600 shadow hover:bg-white dark:bg-slate-900/90" aria-label={`Remove classroom photo ${i + 1}`}>
                  <Trash2 className="h-4 w-4" />
                </button>
              )}
            </li>
          ))}
        </ul>
        {progress !== null && (
          <div role="progressbar" aria-valuenow={progress} aria-valuemin={0} aria-valuemax={100} aria-label="Upload progress">
            <div className="h-1.5 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-700">
              <div className="h-full rounded-full bg-brand-600 transition-all" style={{ width: `${Math.max(progress, 5)}%` }} />
            </div>
            <p className="mt-1 text-xs text-slate-500">{progress < 100 ? `Uploading… ${progress}%` : "Checking photo…"}</p>
          </div>
        )}
        {error && <p className="text-sm text-red-600 dark:text-red-400" role="alert">{error}</p>}
        {editable && (
          <div className="flex flex-wrap gap-2">
            <input
              ref={input}
              type="file"
              accept="image/jpeg,image/png"
              multiple
              className="hidden"
              onChange={(e) => {
                const files = Array.from(e.target.files ?? []).slice(0, session.max_photos - session.images.length);
                e.target.value = "";
                void upload(files);
              }}
            />
            <Button size="sm" variant="secondary" disabled={full || progress !== null} onClick={() => input.current?.click()}>
              <ImagePlus className="h-4 w-4" /> Upload
            </Button>
            <Button size="sm" variant="secondary" disabled={full || progress !== null} onClick={() => setCamera(true)} aria-label="Take classroom photo with camera">
              <Camera className="h-4 w-4" /> Camera
            </Button>
          </div>
        )}
      </div>

      <CameraCapture open={camera} facing="environment" title="Classroom photo" hint="Capture as much of the class as possible." onClose={() => setCamera(false)} onCapture={(blob) => void upload([blob])} />
      <Modal open={!!viewing} title="Classroom photo" description={viewing ? `${viewing.width}×${viewing.height} · added ${formatDateTime(viewing.uploaded_at)}` : undefined} onClose={() => setViewing(null)} size="xl">
        {viewing && <AuthedImage src={viewing.image_url} alt="Classroom photo" className="w-full rounded-lg object-contain" />}
      </Modal>
      <ConfirmDialog open={!!removing} title="Remove this photo?" confirmLabel="Remove" tone="danger" onConfirm={remove} onCancel={() => setRemoving(null)} />
    </Card>
  );
}
