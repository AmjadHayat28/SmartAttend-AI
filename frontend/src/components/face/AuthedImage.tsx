import type { AxiosInstance } from "axios";
import { ImageOff } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../../services/api";
import { cn } from "../../utils/cn";

/**
 * Student images are served only to authorised users, so a plain <img src> (which cannot send
 * the Authorization header) won't work. Fetch the bytes with the API client and show a
 * short-lived object URL instead; it is revoked when the image changes or unmounts.
 */
export function AuthedImage({ src, alt, className, http = api }: { src: string | null; alt: string; className?: string; http?: AxiosInstance }) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!src) return;
    let objectUrl: string | null = null;
    let cancelled = false;
    setFailed(false);
    setUrl(null);
    http
      .get<Blob>(src, { responseType: "blob" })
      .then((res) => {
        if (cancelled) return;
        objectUrl = URL.createObjectURL(res.data);
        setUrl(objectUrl);
      })
      .catch(() => !cancelled && setFailed(true));
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [src, http]);

  if (!src || failed) {
    return (
      <div className={cn("grid place-items-center bg-slate-100 text-slate-400 dark:bg-slate-800", className)} role="img" aria-label={failed ? `${alt} (unavailable)` : alt}>
        <ImageOff className="h-6 w-6" />
      </div>
    );
  }
  if (!url) return <div className={cn("animate-pulse bg-slate-200 dark:bg-slate-800", className)} aria-label={`Loading ${alt}`} />;
  return <img src={url} alt={alt} className={cn("object-cover", className)} draggable={false} />;
}
