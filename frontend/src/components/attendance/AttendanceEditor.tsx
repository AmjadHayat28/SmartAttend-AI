import axios from "axios";
import { AlertTriangle, Check, CheckCheck, CircleSlash, CloudOff, Loader2, MessageSquare, RefreshCw, RotateCcw, Search, Send, Trash2, UserX } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useToast } from "../../context/ToastContext";
import { getErrorMessage } from "../../services/api";
import { attendanceApi, type RecordChange } from "../../services/attendanceService";
import type { AttendanceRecord, AttendanceSession, AttendanceStatus, BulkAction } from "../../types/attendance";
import { STATUS_META } from "../../types/attendance";
import { cn } from "../../utils/cn";
import { initials } from "../../utils/format";
import { AuthedImage } from "../face/AuthedImage";
import { Button } from "../ui/Button";
import { Card } from "../ui/Card";
import { ConfirmDialog } from "../ui/ConfirmDialog";
import { Alert } from "../ui/Feedback";
import { Modal } from "../ui/Modal";
import { localSummary, SessionHeading, StatusToggle, SummaryGrid } from "./AttendanceParts";
import { ClassroomPhotos } from "./ClassroomPhotos";
import { RecognitionPanel } from "./RecognitionPanel";
import type { RecognitionAction } from "../../types/recognition";

type SaveState = "saved" | "pending" | "saving" | "error" | "conflict";
type Filter = "all" | "unmarked" | AttendanceStatus;

const SAVE_DELAY_MS = 600;

export function StudentAvatar({ record }: { record: Pick<AttendanceRecord, "full_name" | "profile_photo_url"> }) {
  return record.profile_photo_url ? (
    <AuthedImage src={record.profile_photo_url} alt="" className="h-10 w-10 shrink-0 rounded-full" />
  ) : (
    <span className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-slate-100 text-sm font-semibold text-slate-600 dark:bg-slate-800 dark:text-slate-300" aria-hidden>
      {initials(record.full_name) || "?"}
    </span>
  );
}

/**
 * Draft attendance editor. Every change is saved automatically (debounced) through a single
 * serial queue so the session `version` always advances in order. If another tab or device
 * changed the session first, the server answers 409 and the editor locks until reloaded —
 * it never silently overwrites newer data.
 */
export function AttendanceEditor({ initial, onDone }: { initial: AttendanceSession; onDone: (s: AttendanceSession) => void }) {
  const toast = useToast();
  const [session, setSession] = useState(initial);
  const [records, setRecords] = useState(initial.records);
  const [note, setNote] = useState(initial.note ?? "");
  const [saveState, setSaveState] = useState<SaveState>("saved");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  const [openNotes, setOpenNotes] = useState<Set<number>>(() => new Set(initial.records.filter((r) => r.note).map((r) => r.id)));
  const [confirmBulk, setConfirmBulk] = useState<BulkAction | null>(null);
  const [reviewing, setReviewing] = useState(false);
  const [discarding, setDiscarding] = useState(false);
  const [busy, setBusy] = useState(false);
  // Face recognition is analysing this session: finalize, discard, bulk changes and photo changes wait.
  const [recognizing, setRecognizing] = useState(false);

  const version = useRef(initial.version);
  const pending = useRef(new Map<number, RecordChange>());
  const noteDirty = useRef(false);
  const queue = useRef<Promise<unknown>>(Promise.resolve());
  const timer = useRef<number | undefined>(undefined);
  const locked = saveState === "conflict";
  const noteRef = useRef(note);
  noteRef.current = note;

  /** Run API calls strictly one after another. */
  const enqueue = useCallback(<T,>(fn: () => Promise<T>): Promise<T> => {
    const next = queue.current.then(fn, fn);
    queue.current = next.catch(() => undefined);
    return next;
  }, []);

  const adopt = useCallback((s: AttendanceSession, replaceRecords: boolean) => {
    version.current = s.version;
    setSession(s);
    if (replaceRecords) {
      // Keep any edit made while the request was in flight.
      setRecords(s.records.map((r) => {
        const local = pending.current.get(r.id);
        return local ? { ...r, ...("status" in local ? { status: local.status ?? null } : {}), ...("note" in local ? { note: local.note ?? null } : {}) } : r;
      }));
    }
  }, []);

  const handleFailure = useCallback((err: unknown) => {
    if (axios.isAxiosError(err) && err.response?.status === 409) {
      setSaveState("conflict");
    } else {
      setSaveState("error");
      toast.error(getErrorMessage(err, "Could not save. Your changes are kept — retrying when you edit again."));
    }
  }, [toast]);

  const flush = useCallback((): Promise<void> => {
    window.clearTimeout(timer.current);
    return enqueue(async () => {
      if (locked) return;
      const changes = [...pending.current.values()];
      const saveNote = noteDirty.current;
      if (!changes.length && !saveNote) return;
      pending.current.clear();
      noteDirty.current = false;
      setSaveState("saving");
      try {
        if (changes.length) adopt(await attendanceApi.updateRecords(session.id, version.current, changes), true);
        if (saveNote) adopt(await attendanceApi.updateNote(session.id, version.current, noteRef.current.trim() || null), false);
        setSaveState(pending.current.size || noteDirty.current ? "pending" : "saved");
      } catch (err) {
        // Put the unsaved changes back (newer local edits win).
        for (const c of changes) pending.current.set(c.record_id, { ...c, ...pending.current.get(c.record_id) });
        if (saveNote) noteDirty.current = true;
        handleFailure(err);
      }
    });
  }, [adopt, enqueue, handleFailure, locked, session.id]);

  const schedule = useCallback(() => {
    setSaveState("pending");
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => void flush(), SAVE_DELAY_MS);
  }, [flush]);

  // Warn before leaving with unsaved work.
  useEffect(() => {
    const handler = (e: BeforeUnloadEvent) => {
      if (pending.current.size || noteDirty.current || saveState === "saving") e.preventDefault();
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [saveState]);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  function change(record: AttendanceRecord, patch: Partial<Pick<RecordChange, "status" | "note">>) {
    if (locked) return;
    setRecords((rs) => rs.map((r) => (r.id === record.id
      ? ({ ...r, ...patch, ...("status" in patch && patch.status !== r.status ? { method: "manual" as const } : {}) } as AttendanceRecord)
      : r)));
    pending.current.set(record.id, { ...pending.current.get(record.id), record_id: record.id, ...patch });
    schedule();
  }

  /** Recognition actions go through the same queue so the version always advances in order. */
  const recognitionRunner = useCallback(
    async (call: (version: number) => Promise<RecognitionAction>): Promise<RecognitionAction | null> => {
      await flush();
      if (locked) return null;
      try {
        const result = await enqueue(() => call(version.current));
        adopt(result.session, true);
        setSaveState(pending.current.size ? "pending" : "saved");
        return result;
      } catch (err) {
        if (axios.isAxiosError(err) && err.response?.status === 409 && String(err.response.data?.detail).includes("another tab")) {
          setSaveState("conflict");
        }
        throw err;
      }
    },
    [adopt, enqueue, flush, locked],
  );

  /** A recognition run finished without this tab getting its response: adopt the server's records
   *  (local unsaved edits are kept and saved on top). */
  const refreshSession = useCallback(() => {
    void enqueue(async () => adopt(await attendanceApi.get(session.id), true)).catch(() => undefined);
  }, [adopt, enqueue, session.id]);

  async function runBulk(action: BulkAction) {
    setConfirmBulk(null);
    await flush();
    setBusy(true);
    try {
      await enqueue(async () => {
        setSaveState("saving");
        adopt(await attendanceApi.bulk(session.id, version.current, action), true);
        setSaveState("saved");
      });
    } catch (err) {
      handleFailure(err);
    } finally {
      setBusy(false);
    }
  }

  async function finalize() {
    setBusy(true);
    try {
      await flush();
      const s = await enqueue(() => attendanceApi.finalize(session.id, version.current));
      toast.success("Attendance finalized.");
      onDone(s);
    } catch (err) {
      setReviewing(false);
      if (axios.isAxiosError(err) && err.response?.status === 409) setSaveState("conflict");
      else toast.error(getErrorMessage(err));
    } finally {
      setBusy(false);
    }
  }

  async function discard(reason: string) {
    setBusy(true);
    try {
      await flush();
      const s = await enqueue(() => attendanceApi.cancel(session.id, version.current, reason || undefined));
      toast.success("Draft discarded.");
      onDone(s);
    } catch (err) {
      setDiscarding(false);
      handleFailure(err);
    } finally {
      setBusy(false);
    }
  }

  async function reload() {
    pending.current.clear();
    noteDirty.current = false;
    const s = await attendanceApi.get(session.id);
    version.current = s.version;
    setSession(s);
    setRecords(s.records);
    setNote(s.note ?? "");
    setSaveState("saved");
    if (!s.can_edit) onDone(s);
  }

  const summary = useMemo(() => localSummary(records.map((r) => r.status)), [records]);
  const q = query.trim().toLowerCase();
  const visible = records.filter(
    (r) =>
      (!q || r.full_name.toLowerCase().includes(q) || r.registration_no.toLowerCase().includes(q)) &&
      (filter === "all" || (filter === "unmarked" ? r.status === null : r.status === filter)),
  );
  const hasMarks = records.some((r) => r.status !== null);

  const bulkCopy: Record<BulkAction, { title: string; text: string; danger: boolean }> = {
    all_present: { title: "Mark everyone present?", text: "This replaces the status of every student on the roster.", danger: false },
    all_absent: { title: "Mark everyone absent?", text: "This replaces the status of every student on the roster.", danger: true },
    unmarked_absent: { title: "Mark the rest absent?", text: `${summary.unmarked} unmarked student(s) will be marked absent.`, danger: false },
    reset: { title: "Clear all marks?", text: "Every student goes back to “not marked”. Notes are kept.", danger: true },
  };

  function bulk(action: BulkAction) {
    // Only ask for confirmation when something already marked would be overwritten.
    if (hasMarks && action !== "unmarked_absent") setConfirmBulk(action);
    else void runBulk(action);
  }

  return (
    <div className="space-y-4">
      <SessionHeading session={session} />

      {/* Sticky status bar: counts, save state, finalize */}
      <div className="sticky top-16 z-10 -mx-4 border-y border-slate-200 bg-white/95 px-4 py-2.5 backdrop-blur sm:mx-0 sm:rounded-xl sm:border dark:border-slate-800 dark:bg-slate-950/95">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <p className="flex flex-wrap gap-x-3 text-sm tabular-nums" aria-label="Attendance counts">
            <span className={STATUS_META.present.tone}>P {summary.present}</span>
            <span className={STATUS_META.absent.tone}>A {summary.absent}</span>
            <span className={STATUS_META.late.tone}>L {summary.late}</span>
            <span className={STATUS_META.excused.tone}>E {summary.excused}</span>
            <span className="text-slate-500">Not marked {summary.unmarked}</span>
          </p>
          <SaveIndicator state={saveState} onRetry={() => void flush()} />
          <Button size="sm" className="ml-auto" disabled={busy || locked || recognizing} title={recognizing ? "Wait for face recognition to finish" : undefined} onClick={() => void flush().then(() => setReviewing(true))}>
            <Send className="h-4 w-4" /> Review &amp; finalize
          </Button>
        </div>
      </div>

      {locked && (
        <Alert tone="warning">
          This attendance was changed in another tab or on another device, so editing here is paused to avoid overwriting it.{" "}
          <button type="button" className="font-semibold underline" onClick={() => void reload()}>
            Reload the latest version
          </button>
        </Alert>
      )}

      {!locked && (
        <RecognitionPanel
          key={session.images.map((i) => i.id).join(",")}
          session={session}
          runner={recognitionRunner}
          onRunningChange={setRecognizing}
          onSessionStale={refreshSession}
        />
      )}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_20rem]">
        {/* Roster */}
        <Card className="min-w-0">
          <div className="space-y-3 border-b border-slate-200 p-4 dark:border-slate-800">
            <div className="flex flex-wrap gap-2">
              <div className="relative min-w-0 flex-1 sm:max-w-xs">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search name or reg. no." aria-label="Search students" className="h-9 w-full rounded-lg border border-slate-300 bg-white pl-8 pr-3 text-sm focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20 dark:border-slate-700 dark:bg-slate-950" />
              </div>
              <select value={filter} onChange={(e) => setFilter(e.target.value as Filter)} aria-label="Show" className="h-9 rounded-lg border border-slate-300 bg-white px-2 text-sm dark:border-slate-700 dark:bg-slate-950">
                <option value="all">All ({records.length})</option>
                <option value="unmarked">Not marked ({summary.unmarked})</option>
                {(["present", "absent", "late", "excused"] as const).map((s) => (
                  <option key={s} value={s}>
                    {STATUS_META[s].label} ({summary[s]})
                  </option>
                ))}
              </select>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button size="sm" variant="secondary" disabled={busy || locked || recognizing} onClick={() => bulk("all_present")}>
                <CheckCheck className="h-4 w-4" /> All present
              </Button>
              <Button size="sm" variant="secondary" disabled={busy || locked || recognizing || !summary.unmarked} onClick={() => bulk("unmarked_absent")}>
                <UserX className="h-4 w-4" /> Rest absent
              </Button>
              <Button size="sm" variant="secondary" disabled={busy || locked || recognizing} onClick={() => bulk("all_absent")}>
                <CircleSlash className="h-4 w-4" /> All absent
              </Button>
              <Button size="sm" variant="ghost" disabled={busy || locked || recognizing || !hasMarks} onClick={() => bulk("reset")}>
                <RotateCcw className="h-4 w-4" /> Clear
              </Button>
            </div>
          </div>
          {visible.length === 0 ? (
            <p className="p-6 text-center text-sm text-slate-500">No students match.</p>
          ) : (
            <ul className="divide-y divide-slate-200 dark:divide-slate-800">
              {visible.map((r) => {
                const noteOpen = openNotes.has(r.id);
                return (
                  <li key={r.id} className={cn("px-4 py-3", r.status === null && "bg-amber-50/40 dark:bg-amber-950/10")}>
                    <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-4">
                      <div className="flex min-w-0 flex-1 items-center gap-3">
                        <StudentAvatar record={r} />
                        <div className="min-w-0">
                          <p className="truncate font-medium text-slate-900 dark:text-white">{r.full_name}</p>
                          <p className="flex items-center gap-1.5 font-mono text-xs text-slate-500">
                            {r.registration_no}
                            <AiBadge record={r} />
                          </p>
                        </div>
                      </div>
                      <div className="flex items-center gap-2">
                        <div className="flex-1 sm:w-48 sm:flex-none">
                          <StatusToggle value={r.status} name={r.full_name} disabled={locked} onChange={(s) => change(r, { status: s })} />
                        </div>
                        <Button
                          size="sm"
                          variant="ghost"
                          aria-label={`${noteOpen ? "Hide" : "Add"} note for ${r.full_name}`}
                          aria-expanded={noteOpen}
                          className={cn(r.note && "text-brand-700 dark:text-brand-200")}
                          onClick={() => setOpenNotes((s) => { const n = new Set(s); if (n.has(r.id)) n.delete(r.id); else n.add(r.id); return n; })}
                        >
                          <MessageSquare className="h-4 w-4" />
                        </Button>
                      </div>
                    </div>
                    {noteOpen && (
                      <input
                        type="text"
                        maxLength={200}
                        value={r.note ?? ""}
                        disabled={locked}
                        onChange={(e) => change(r, { note: e.target.value || null })}
                        placeholder="Note, e.g. Arrived 15 minutes late"
                        aria-label={`Note for ${r.full_name}`}
                        className="mt-2 h-9 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm focus:border-brand-500 focus:outline-none dark:border-slate-700 dark:bg-slate-950"
                      />
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </Card>

        {/* Side panel */}
        <div className="space-y-4">
          <ClassroomPhotos session={session} editable={!locked && !recognizing} onChanged={(s) => setSession((prev) => ({ ...prev, images: s.images }))} />
          <Card className="p-4">
            <label htmlFor="session-note" className="block text-sm font-medium text-slate-700 dark:text-slate-300">
              Session note <span className="font-normal text-slate-500">(optional)</span>
            </label>
            <textarea
              id="session-note"
              rows={2}
              maxLength={300}
              value={note}
              disabled={locked}
              onChange={(e) => {
                setNote(e.target.value);
                noteDirty.current = true;
                schedule();
              }}
              placeholder="e.g. Quiz conducted during the first 20 minutes."
              className="mt-1.5 block w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm focus:border-brand-500 focus:outline-none dark:border-slate-700 dark:bg-slate-950"
            />
          </Card>
          <Button variant="ghost" size="sm" className="w-full text-red-600" disabled={busy || locked || recognizing} onClick={() => setDiscarding(true)}>
            <Trash2 className="h-4 w-4" /> Discard draft
          </Button>
        </div>
      </div>

      {confirmBulk && (
        <ConfirmDialog
          open
          title={bulkCopy[confirmBulk].title}
          description={bulkCopy[confirmBulk].text}
          confirmLabel="Apply"
          tone={bulkCopy[confirmBulk].danger ? "danger" : "primary"}
          onConfirm={() => void runBulk(confirmBulk)}
          onCancel={() => setConfirmBulk(null)}
        />
      )}

      <Modal open={reviewing} title="Review attendance" description={`${session.course_code} · ${session.batch_name} · ${session.semester_name} · Section ${session.section_name}`} onClose={() => setReviewing(false)}>
        <SummaryGrid summary={summary} photos={session.images.length} />
        {summary.unmarked > 0 ? (
          <Alert tone="warning">
            {summary.unmarked} student(s) are not marked yet. Mark them, or{" "}
            <button type="button" className="font-semibold underline" onClick={() => { setReviewing(false); void runBulk("unmarked_absent"); }}>
              mark the rest absent
            </button>
            .
          </Alert>
        ) : (
          <p className="text-sm text-slate-600 dark:text-slate-300">
            Once finalized, this attendance becomes official and counts toward attendance percentages. Changes after that need a correction with a reason.
          </p>
        )}
        <div className="flex justify-end gap-2 pt-2">
          <Button variant="secondary" onClick={() => setReviewing(false)}>
            Keep editing
          </Button>
          <Button onClick={() => void finalize()} loading={busy} disabled={summary.unmarked > 0 || recognizing}>
            <Check className="h-4 w-4" /> Finalize Attendance
          </Button>
        </div>
      </Modal>

      <ConfirmDialog
        open={discarding}
        title="Discard this draft?"
        description="The draft is cancelled (kept in history) and this class/date/session can be started again."
        confirmLabel="Discard draft"
        tone="danger"
        reasonLabel="Reason (optional)"
        loading={busy}
        onConfirm={(reason) => void discard(reason)}
        onCancel={() => setDiscarding(false)}
      />
    </div>
  );
}

function SaveIndicator({ state, onRetry }: { state: SaveState; onRetry: () => void }) {
  const map = {
    saved: { icon: Check, text: "All changes saved", cls: "text-emerald-700 dark:text-emerald-300" },
    pending: { icon: Loader2, text: "Saving…", cls: "text-slate-500" },
    saving: { icon: Loader2, text: "Saving…", cls: "text-slate-500" },
    error: { icon: CloudOff, text: "Not saved", cls: "text-red-600 dark:text-red-400" },
    conflict: { icon: AlertTriangle, text: "Changed elsewhere", cls: "text-amber-700 dark:text-amber-300" },
  }[state];
  return (
    <span className={cn("flex items-center gap-1.5 text-sm", map.cls)} role="status" aria-live="polite">
      <map.icon className={cn("h-4 w-4", (state === "saving" || state === "pending") && "animate-spin")} />
      {map.text}
      {state === "error" && (
        <button type="button" onClick={onRetry} className="ml-1 inline-flex items-center gap-1 underline">
          <RefreshCw className="h-3.5 w-3.5" /> Retry
        </button>
      )}
    </span>
  );
}

/** Shows when a mark came from face recognition (AI) or an AI suggestion the teacher confirmed. */
export function AiBadge({ record }: { record: Pick<AttendanceRecord, "method" | "confidence" | "status"> }) {
  if (record.status === null) return null;
  if (record.method === "face_recognition")
    return (
      <span className="rounded bg-violet-100 px-1.5 font-sans text-[10px] font-semibold uppercase text-violet-800 dark:bg-violet-900/40 dark:text-violet-200" title="Pre-filled by face recognition — please check">
        AI{record.confidence !== null ? ` ${Math.round(record.confidence * 100)}%` : ""}
      </span>
    );
  if (record.method === "face_recognition_confirmed")
    return (
      <span className="rounded bg-emerald-100 px-1.5 font-sans text-[10px] font-semibold uppercase text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-200" title="AI suggestion confirmed by the teacher">
        AI ✓
      </span>
    );
  return null;
}
