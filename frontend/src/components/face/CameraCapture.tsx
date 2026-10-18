import { Camera, RefreshCw, Video, VideoOff } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "../ui/Button";
import { Alert } from "../ui/Feedback";
import { Modal } from "../ui/Modal";

type Phase = "starting" | "live" | "captured" | "error";

function cameraErrorMessage(err: unknown): string {
  const name = err instanceof DOMException ? err.name : "";
  switch (name) {
    case "NotAllowedError":
    case "SecurityError":
      return "Camera access was blocked. Allow the camera for this site in your browser settings, or upload a photo instead.";
    case "NotFoundError":
    case "OverconstrainedError":
      return "No camera was found on this device. Upload a photo instead.";
    case "NotReadableError":
    case "AbortError":
      return "The camera is being used by another app. Close it and try again, or upload a photo instead.";
    default:
      return "The camera could not be started. Upload a photo instead.";
  }
}

interface CameraCaptureProps {
  open: boolean;
  title: string;
  hint?: string;
  onClose: () => void;
  onCapture: (photo: Blob) => void;
  /** "user" = selfie camera (mirrored preview); "environment" = rear camera, e.g. classroom photos. */
  facing?: "user" | "environment";
}

/**
 * Still-photo capture for enrollment. The camera is requested only when this dialog opens
 * (i.e. after the user clicks "Camera"), and every track is stopped when it closes.
 * No recognition happens here — the captured image goes to the same validated upload endpoint.
 */
export function CameraCapture({ open, title, hint, onClose, onCapture, facing = "user" }: CameraCaptureProps) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [phase, setPhase] = useState<Phase>("starting");
  const [error, setError] = useState<string | null>(null);
  const [shot, setShot] = useState<{ blob: Blob; url: string } | null>(null);

  const stop = useCallback(() => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
  }, []);

  const start = useCallback(async () => {
    setError(null);
    setPhase("starting");
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
      setError("Camera capture needs a secure connection (HTTPS or localhost). Upload a photo instead.");
      setPhase("error");
      return;
    }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: facing, width: { ideal: facing === "user" ? 1280 : 1920 }, height: { ideal: facing === "user" ? 960 : 1080 } },
        audio: false,
      });
      streamRef.current = stream;
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        await videoRef.current.play().catch(() => undefined);
      }
      setPhase("live");
    } catch (err) {
      stop();
      setError(cameraErrorMessage(err));
      setPhase("error");
    }
  }, [stop, facing]);

  useEffect(() => {
    if (!open) return;
    void start();
    return () => stop();
  }, [open, start, stop]);

  // Release the preview URL whenever the shot changes or the dialog closes.
  useEffect(() => () => {
    if (shot) URL.revokeObjectURL(shot.url);
  }, [shot]);

  function capture() {
    const video = videoRef.current;
    if (!video || !video.videoWidth) return;
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    canvas.getContext("2d")?.drawImage(video, 0, 0); // un-mirrored: the real orientation
    canvas.toBlob(
      (blob) => {
        if (!blob) return;
        setShot({ blob, url: URL.createObjectURL(blob) });
        setPhase("captured");
        stop(); // camera light off while reviewing the shot
      },
      "image/jpeg",
      0.92,
    );
  }

  function retake() {
    setShot(null);
    void start();
  }

  function close() {
    stop();
    setShot(null);
    onClose();
  }

  return (
    <Modal open={open} title={title} description={hint} onClose={close} size="lg">
      <div className="relative overflow-hidden rounded-lg bg-slate-900">
        {/* The live preview is mirrored like a selfie camera; the saved photo is not. */}
        <video ref={videoRef} playsInline muted aria-label="Camera preview" className={phase === "live" ? `block aspect-[4/3] w-full object-cover ${facing === "user" ? "-scale-x-100" : ""}` : "hidden"} />
        {phase === "captured" && shot && <img src={shot.url} alt="Captured photo" className="block aspect-[4/3] w-full object-cover" />}
        {phase === "starting" && (
          <div className="grid aspect-[4/3] place-items-center text-sm text-slate-300">
            <span className="flex items-center gap-2">
              <Video className="h-5 w-5 animate-pulse" /> Waiting for camera permission…
            </span>
          </div>
        )}
        {phase === "error" && (
          <div className="grid aspect-[4/3] place-items-center text-slate-400">
            <VideoOff className="h-10 w-10" />
          </div>
        )}
        {phase === "live" && facing === "user" && <div className="pointer-events-none absolute inset-[18%_25%] rounded-[50%] border-2 border-dashed border-white/60" aria-hidden />}
      </div>
      {error && <Alert>{error}</Alert>}
      <div className="flex flex-wrap justify-end gap-2">
        <Button type="button" variant="secondary" onClick={close}>
          Cancel
        </Button>
        {phase === "live" && (
          <Button type="button" onClick={capture}>
            <Camera className="h-4 w-4" /> Capture
          </Button>
        )}
        {phase === "captured" && (
          <>
            <Button type="button" variant="secondary" onClick={retake}>
              <RefreshCw className="h-4 w-4" /> Retake
            </Button>
            <Button
              type="button"
              onClick={() => {
                if (shot) onCapture(shot.blob);
                close();
              }}
            >
              Use this photo
            </Button>
          </>
        )}
        {phase === "error" && (
          <Button type="button" variant="secondary" onClick={() => void start()}>
            <RefreshCw className="h-4 w-4" /> Try again
          </Button>
        )}
      </div>
    </Modal>
  );
}
