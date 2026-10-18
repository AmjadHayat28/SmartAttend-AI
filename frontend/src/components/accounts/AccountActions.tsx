import { Check, KeyRound, Pause, Play, X } from "lucide-react";
import { useState } from "react";
import { useToast } from "../../context/ToastContext";
import { getErrorMessage } from "../../services/api";
import { accountApi } from "../../services/managementService";
import type { AccountStatus } from "../../types/auth";
import { Button } from "../ui/Button";
import { ConfirmDialog } from "../ui/ConfirmDialog";
import { Badge } from "../ui/Feedback";
import { Input } from "../ui/FormField";
import { Modal } from "../ui/Modal";

const STATUS_TONE = { active: "green", pending: "amber", suspended: "red", rejected: "gray" } as const;

export function AccountStatusBadge({ status }: { status: AccountStatus }) {
  return <Badge tone={STATUS_TONE[status]}>{status[0]!.toUpperCase() + status.slice(1)}</Badge>;
}

interface Account {
  user_id: number;
  full_name: string;
  status: AccountStatus;
}

type Action = { status: AccountStatus; verb: string; reason: boolean; tone: "primary" | "danger" };

const ACTIONS: Record<string, Action> = {
  approve: { status: "active", verb: "Approve", reason: false, tone: "primary" },
  reject: { status: "rejected", verb: "Reject", reason: true, tone: "danger" },
  suspend: { status: "suspended", verb: "Suspend", reason: true, tone: "danger" },
  reactivate: { status: "active", verb: "Reactivate", reason: false, tone: "primary" },
};

/** Status changes + password reset for any managed account. The API enforces who may do what. */
export function AccountActions({ account, onChanged, allowReactivate = true }: { account: Account; onChanged: () => void; allowReactivate?: boolean }) {
  const toast = useToast();
  const [action, setAction] = useState<Action | null>(null);
  const [saving, setSaving] = useState(false);
  const [resetOpen, setResetOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");

  async function applyStatus(reason: string) {
    if (!action) return;
    setSaving(true);
    try {
      await accountApi.setStatus(account.user_id, action.status, reason || undefined);
      toast.success(`${account.full_name}: ${action.verb.toLowerCase()}${action.verb.endsWith("e") ? "d" : "ed"}.`);
      setAction(null);
      onChanged();
    } catch (err) {
      toast.error(getErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  async function resetPassword() {
    setSaving(true);
    try {
      await accountApi.resetPassword(account.user_id, password);
      toast.success(`Password reset for ${account.full_name}. Their active sessions were signed out.`);
      setResetOpen(false);
    } catch (err) {
      toast.error(getErrorMessage(err));
    } finally {
      setSaving(false);
    }
  }

  const weak = password.length < 8 || !/[a-z]/.test(password) || !/[A-Z]/.test(password) || !/\d/.test(password);

  return (
    <div className="flex flex-wrap justify-end gap-1.5">
      {account.status === "pending" && (
        <>
          <Button size="sm" onClick={() => setAction(ACTIONS.approve!)} title="Approve">
            <Check className="h-4 w-4" />
            <span className="sr-only sm:not-sr-only">Approve</span>
          </Button>
          <Button size="sm" variant="secondary" onClick={() => setAction(ACTIONS.reject!)} title="Reject">
            <X className="h-4 w-4" />
            <span className="sr-only sm:not-sr-only">Reject</span>
          </Button>
        </>
      )}
      {account.status === "active" && (
        <Button size="sm" variant="secondary" onClick={() => setAction(ACTIONS.suspend!)} title="Suspend">
          <Pause className="h-4 w-4" />
          <span className="sr-only sm:not-sr-only">Suspend</span>
        </Button>
      )}
      {allowReactivate && (account.status === "suspended" || account.status === "rejected") && (
        <Button size="sm" variant="secondary" onClick={() => setAction(ACTIONS.reactivate!)} title="Reactivate">
          <Play className="h-4 w-4" />
          <span className="sr-only sm:not-sr-only">Reactivate</span>
        </Button>
      )}
      <Button
        size="sm"
        variant="ghost"
        title="Reset password"
        aria-label={`Reset password for ${account.full_name}`}
        onClick={() => {
          setPassword("");
          setConfirm("");
          setResetOpen(true);
        }}
      >
        <KeyRound className="h-4 w-4" />
      </Button>

      <ConfirmDialog
        open={!!action}
        title={action ? `${action.verb} ${account.full_name}?` : ""}
        description={
          action?.status === "suspended"
            ? "They will be signed out immediately and cannot sign in until reactivated."
            : action?.status === "rejected"
              ? "The registration will be rejected and the student cannot sign in."
              : "They will be able to sign in."
        }
        confirmLabel={action?.verb}
        tone={action?.tone}
        reasonLabel={action?.reason ? "Reason" : undefined}
        reasonRequired={action?.reason}
        loading={saving}
        onConfirm={applyStatus}
        onCancel={() => setAction(null)}
      />

      <Modal
        open={resetOpen}
        title={`Reset password — ${account.full_name}`}
        description="Share the new password with the user through a secure channel. All their sessions will be signed out."
        onClose={() => setResetOpen(false)}
        onSubmit={resetPassword}
        submitLabel="Reset password"
        submitting={saving}
        submitDisabled={weak || password !== confirm}
      >
        <Input label="New password" name={`reset-${account.user_id}`} type="password" autoComplete="new-password" value={password} onChange={(e) => setPassword(e.target.value)} hint="At least 8 characters with upper-case, lower-case and a digit" error={password && weak ? "Too weak" : undefined} />
        <Input label="Confirm password" name={`reset-confirm-${account.user_id}`} type="password" autoComplete="new-password" value={confirm} onChange={(e) => setConfirm(e.target.value)} error={confirm && confirm !== password ? "Passwords do not match" : undefined} />
      </Modal>
    </div>
  );
}
