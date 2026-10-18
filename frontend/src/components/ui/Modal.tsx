import { X } from "lucide-react";
import { useEffect, useRef, type FormEvent, type ReactNode } from "react";
import { cn } from "../../utils/cn";
import { Button } from "./Button";

interface ModalProps {
  open: boolean;
  title: string;
  description?: string;
  onClose: () => void;
  children: ReactNode;
  /** Renders the body as a form with Cancel/submit buttons. */
  onSubmit?: () => void;
  submitLabel?: string;
  submitting?: boolean;
  submitDisabled?: boolean;
  size?: "md" | "lg" | "xl";
}

export function Modal({ open, title, description, onClose, children, onSubmit, submitLabel = "Save", submitting, submitDisabled, size = "md" }: ModalProps) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    else if (!open && dialog.open) dialog.close();
  }, [open]);

  function handleSubmit(e: FormEvent) {
    e.preventDefault();
    onSubmit?.();
  }

  return (
    <dialog
      ref={ref}
      onCancel={(e) => {
        e.preventDefault();
        if (!submitting) onClose();
      }}
      className={cn(
        "m-auto max-h-[calc(100vh-2rem)] w-[calc(100%-2rem)] rounded-xl border border-slate-200 bg-white p-0 text-slate-800 shadow-xl backdrop:bg-slate-900/50 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-200",
        size === "xl" ? "max-w-5xl" : size === "lg" ? "max-w-2xl" : "max-w-lg",
      )}
    >
      {open && (
        <form onSubmit={handleSubmit} noValidate className="flex max-h-[calc(100vh-2rem)] flex-col">
          <div className="flex items-start justify-between gap-4 border-b border-slate-200 px-5 py-4 dark:border-slate-800">
            <div>
              <h2 className="text-base font-semibold text-slate-900 dark:text-white">{title}</h2>
              {description && <p className="mt-0.5 text-sm text-slate-500 dark:text-slate-400">{description}</p>}
            </div>
            <button type="button" onClick={onClose} disabled={submitting} className="rounded p-1 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800" aria-label="Close">
              <X className="h-5 w-5" />
            </button>
          </div>
          <div className="flex-1 space-y-4 overflow-y-auto px-5 py-4">{children}</div>
          {onSubmit && (
            <div className="flex justify-end gap-2 border-t border-slate-200 bg-slate-50 px-5 py-3 dark:border-slate-800 dark:bg-slate-900/60">
              <Button type="button" variant="secondary" onClick={onClose} disabled={submitting}>
                Cancel
              </Button>
              <Button type="submit" loading={submitting} disabled={submitDisabled}>
                {submitLabel}
              </Button>
            </div>
          )}
        </form>
      )}
    </dialog>
  );
}
