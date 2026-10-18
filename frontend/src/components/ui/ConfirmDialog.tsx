import { useEffect, useRef, useState, type ReactNode } from "react";
import { Button } from "./Button";

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  description?: ReactNode;
  confirmLabel?: string;
  tone?: "primary" | "danger";
  /** When set, a reason textarea is shown and its value is passed to onConfirm. */
  reasonLabel?: string;
  reasonRequired?: boolean;
  /** Minimum trimmed length of a required reason (default 1). */
  reasonMinLength?: number;
  reasonPlaceholder?: string;
  reasonMaxLength?: number;
  loading?: boolean;
  onConfirm: (reason: string) => void;
  onCancel: () => void;
}

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel = "Confirm",
  tone = "primary",
  reasonLabel,
  reasonRequired,
  reasonMinLength = 1,
  reasonPlaceholder,
  reasonMaxLength = 500,
  loading,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const [reason, setReason] = useState("");

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      setReason("");
      dialog.showModal();
    } else if (!open && dialog.open) {
      dialog.close();
    }
  }, [open]);

  const disabled = reasonRequired && reason.trim().length < reasonMinLength;

  return (
    <dialog
      ref={ref}
      onCancel={(e) => {
        e.preventDefault();
        if (!loading) onCancel();
      }}
      className="m-auto w-[calc(100%-2rem)] max-w-md rounded-xl border border-slate-200 bg-white p-0 text-slate-800 shadow-xl backdrop:bg-slate-900/50 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-200"
    >
      <div className="p-5">
        <h2 className="text-base font-semibold text-slate-900 dark:text-white">{title}</h2>
        {description && <div className="mt-2 text-sm text-slate-600 dark:text-slate-400">{description}</div>}
        {reasonLabel && (
          <div className="mt-4 space-y-1.5">
            <label htmlFor="confirm-reason" className="block text-sm font-medium">
              {reasonLabel}
              {reasonRequired && <span className="text-red-600"> *</span>}
            </label>
            <textarea
              id="confirm-reason"
              rows={3}
              maxLength={reasonMaxLength}
              placeholder={reasonPlaceholder}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              className="block w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20 dark:border-slate-700 dark:bg-slate-950"
            />
          </div>
        )}
      </div>
      <div className="flex justify-end gap-2 border-t border-slate-200 bg-slate-50 px-5 py-3 dark:border-slate-800 dark:bg-slate-900/60">
        <Button variant="secondary" onClick={onCancel} disabled={loading}>
          Cancel
        </Button>
        <Button variant={tone} onClick={() => onConfirm(reason.trim())} loading={loading} disabled={disabled}>
          {confirmLabel}
        </Button>
      </div>
    </dialog>
  );
}
