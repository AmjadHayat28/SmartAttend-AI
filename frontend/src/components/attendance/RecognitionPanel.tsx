import axios from "axios";
import { AlertTriangle, Check, CheckCircle2, ChevronDown, Circle, HelpCircle, Loader2, ScanFace, Sparkles, UserCheck, UserPlus, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useToast } from "../../context/ToastContext";
import { useAuthedBlobUrls } from "../../hooks/useAuthedBlobUrl";
import { getErrorMessage } from "../../services/api";
import { recognitionApi } from "../../services/attendanceService";
import type { AttendanceSession } from "../../types/attendance";
import { faceGroup, GROUP_STYLE, stageLabel, type FaceGroup, type Recognition, type RecognitionAction, type RecognitionFace, type RecognitionRun } from "../../types/recognition";
import { cn } from "../../utils/cn";
import { formatDateTime } from "../../utils/format";
import { Button } from "../ui/Button";
import { Card } from "../ui/Card";
import { ConfirmDialog } from "../ui/ConfirmDialog";
import { Alert, Badge } from "../ui/Feedback";

const pct = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${Math.round(v * 100)}%`);
const secs = (ms: number | undefined) => `${((ms ?? 0) / 1000).toFixed(1)} s`;
const POLL_MS = 1500;
const STATUS_WORD: Record<string, string> = { present: "Present", absent: "Absent", late: "Late", excused: "Excused" };

type Runner = (call: (version: number) => Promise<RecognitionAction>) => Promise<RecognitionAction | null>;

interface RecognitionPanelProps {
  session: AttendanceSession;
  /** Editor mode: runs API calls through the editor's save queue (current version, adopt result). */
  runner?: Runner;
  /** Tells the editor while recognition is running (it pauses finalize/discard/photo changes). */
  onRunningChange?: (running: boolean) => void;
  /** A run finished without this tab receiving its result (lost connection, another tab): reload the session. */
  onSessionStale?: () => void;
}

/** Steps a run goes through. "Preparing" is everything before the server opens the run
 *  (saving pending edits, checking the roster, student profiles); the rest is reported by the server. */
const STEPS = [
  { key: "preparing", label: "Preparing recognition" },
  { key: "detecting", label: "Detecting faces" },
  { key: "matching", label: "Matching students" },
  { key: "saving", label: "Saving results" },
] as const;

/**
 * AI assistance for a draft: run recognition, review suggestions, fix mistakes. It only ever
 * pre-fills students who are not marked yet; it never marks anyone absent and never finalizes.
 */
export function RecognitionPanel({ session, runner, onRunningChange, onSessionStale }: RecognitionPanelProps) {
  const toast = useToast();
  const [rec, setRec] = useState<Recognition | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [requesting, setRequesting] = useState(false); // this tab's run request is in flight
  const [watching, setWatching] = useState(false); // waiting for a run whose response this tab won't get
  const [progress, setProgress] = useState<RecognitionRun | null>(null); // server-reported processing run
  const [notice, setNotice] = useState<string | null>(null);
  const [justFinished, setJustFinished] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [busyFace, setBusyFace] = useState<number | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [moveConfirm, setMoveConfirm] = useState<{ face: RecognitionFace; studentId: number } | null>(null);
  const [showMatched, setShowMatched] = useState(false);
  const runLock = useRef(false); // blocks a second click before React re-renders
  const baseRunId = useRef(0); // latest run id before this tab started a run
  const serverRunning = rec?.run?.status === "processing";
  const running = requesting || watching || serverRunning;
  const editable = !!runner && !!rec?.can_decide && !running;

  const load = useCallback(() => {
    recognitionApi.get(session.id).then(setRec).catch((err) => setLoadError(getErrorMessage(err)));
  }, [session.id]);
  useEffect(load, [load]);

  useEffect(() => onRunningChange?.(running), [running, onRunningChange]);
  useEffect(() => () => onRunningChange?.(false), [onRunningChange]);

  // Elapsed-time counter: proof of life without inventing a percentage.
  useEffect(() => {
    if (!running) return;
    const started = Date.now();
    setElapsed(0);
    const id = window.setInterval(() => setElapsed(Math.round((Date.now() - started) / 1000)), 1000);
    return () => window.clearInterval(id);
  }, [running]);

  // Poll the server's committed progress while a run is going on.
  useEffect(() => {
    if (!running) return;
    let cancelled = false;
    const tick = async () => {
      try {
        const latest = await recognitionApi.get(session.id);
        if (cancelled) return;
        const r = latest.run;
        if (r && r.status === "processing") {
          if (r.id > baseRunId.current || !requesting) setProgress(r);
          return;
        }
        if (!requesting && (watching || serverRunning)) {
          // Finished without our request returning (connection lost, or started in another tab).
          setRec(latest);
          setProgress(null);
          setWatching(false);
          if (r && r.id > baseRunId.current) {
            setNotice(r.status === "failed" ? null : "Recognition finished. Results and attendance were reloaded.");
            onSessionStale?.();
          } else {
            setNotice("Recognition did not start because the server could not be reached. Check the connection and try again.");
          }
        }
      } catch {
        /* keep polling; the request's own error handling reports failures */
      }
    };
    void tick();
    const id = window.setInterval(() => void tick(), POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [running, requesting, watching, serverRunning, session.id, onSessionStale]);

  const imageUrls = useAuthedBlobUrls(session.images.map((i) => i.image_url));
  const urlFor = (imageId: number) => imageUrls[session.images.find((i) => i.id === imageId)?.image_url ?? ""];

  async function act(call: (version: number) => Promise<RecognitionAction>, faceId: number, success?: string) {
    if (!runner) return;
    setBusyFace(faceId);
    try {
      const result = await runner(call);
      if (result) {
        setRec(result.recognition);
        if (success) toast.success(success);
      }
    } catch (err) {
      if (axios.isAxiosError(err) && err.response?.status === 409 && String(err.response.data?.detail).includes("already matched")) {
        throw err;
      }
      toast.error(getErrorMessage(err));
      load();
    } finally {
      setBusyFace(null);
    }
  }

  async function run() {
    if (!runner || runLock.current || running) return;
    runLock.current = true;
    baseRunId.current = rec?.run?.id ?? 0;
    setRequesting(true);
    setProgress(null);
    setNotice(null);
    setJustFinished(false);
    try {
      const result = await runner((v) => recognitionApi.run(session.id, v));
      if (result) {
        setRec(result.recognition);
        setShowMatched(false);
        setJustFinished(true);
      }
    } catch (err) {
      const detail = axios.isAxiosError(err) ? String(err.response?.data?.detail ?? "") : "";
      if (axios.isAxiosError(err) && !err.response) {
        // The server may still be working: keep showing progress and pick up the result when it is done.
        setNotice("The connection was interrupted. Checking whether recognition finished…");
        setWatching(true);
      } else if (axios.isAxiosError(err) && err.response?.status === 409 && detail.includes("already running")) {
        setNotice("Recognition is already running for this attendance (another tab or device). Showing its progress…");
        setWatching(true);
      } else {
        toast.error(getErrorMessage(err));
        load();
      }
    } finally {
      setRequesting(false);
      setProgress(null);
      runLock.current = false;
    }
  }

  async function assign(face: RecognitionFace, studentId: number, replace = false) {
    try {
      await act((v) => recognitionApi.assign(face.id, v, studentId, replace), face.id, "Face linked to student.");
    } catch {
      setMoveConfirm({ face, studentId });
    }
  }

  const faces = rec?.faces ?? [];
  const groups = useMemo(() => {
    const g: Record<Exclude<FaceGroup, "dismissed">, RecognitionFace[]> = { matched: [], review: [], unknown: [], manual: [] };
    for (const f of faces) {
      const group = faceGroup(f);
      if (group !== "dismissed") g[group].push(f);
    }
    return g;
  }, [faces]);
  const run_ = rec?.run;
  const roster = [...session.records].sort((a, b) => a.registration_no.localeCompare(b.registration_no));
  const statusOf = new Map(session.records.map((r) => [r.student_id, r.status]));
  const linked = new Set(faces.filter((f) => ["applied", "accepted", "assigned"].includes(f.decision)).map((f) => f.assigned?.student_id));
  const finished = !!run_ && run_.status !== "processing";

  if (loadError) return <Alert>{loadError}</Alert>;
  if (!rec) return null;
  if (!run_ && !runner) return null; // read-only views: nothing to show before a run

  const shown = progress ?? (serverRunning ? (run_ ?? null) : null);
  const stepIndex = shown?.stage ? STEPS.findIndex((s) => s.key === shown.stage) : 0;

  return (
    <Card className="overflow-hidden">
      <div className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-200 px-4 py-3 dark:border-slate-800">
        <div className="min-w-0">
          <h2 className="flex items-center gap-2 font-semibold text-slate-900 dark:text-white">
            <ScanFace className="h-5 w-5 text-brand-700 dark:text-brand-200" /> Face recognition
          </h2>
          <p className="mt-0.5 text-xs text-slate-500">
            Suggestions only fill students who aren’t marked yet. Nobody is marked absent automatically, and you finalize.
          </p>
        </div>
        {runner && (rec.can_run || running) && (
          <Button size="sm" onClick={() => void run()} loading={running} disabled={running || session.images.length === 0} title={session.images.length ? undefined : "Add a classroom photo first"}>
            <Sparkles className="h-4 w-4" /> {running ? "Recognizing…" : run_ ? "Run again" : "Run Face Recognition"}
          </Button>
        )}
      </div>

      <div className="space-y-4 p-4">
        {running && (
          <div className="rounded-lg border border-brand-200 bg-brand-50/60 p-3 dark:border-brand-900 dark:bg-brand-950/20" role="status" aria-live="polite" aria-label="Recognition progress">
            <p className="flex items-center gap-2 text-sm font-medium text-slate-800 dark:text-slate-100">
              <Loader2 className="h-4 w-4 shrink-0 animate-spin text-brand-700 dark:text-brand-200" />
              <span className="min-w-0">{stageLabel(shown)}</span>
              <span className="ml-auto shrink-0 tabular-nums text-xs font-normal text-slate-500">{elapsed} s</span>
            </p>
            <ol className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-xs sm:grid-cols-4" aria-label="Recognition steps">
              {STEPS.map((s, i) => {
                const state = i < stepIndex ? "done" : i === stepIndex ? "current" : "todo";
                return (
                  <li key={s.key} className={cn("flex items-center gap-1.5", state === "todo" ? "text-slate-400" : "text-slate-700 dark:text-slate-200", state === "current" && "font-semibold")} aria-current={state === "current" ? "step" : undefined}>
                    {state === "done" ? <Check className="h-3.5 w-3.5 text-emerald-600" /> : state === "current" ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Circle className="h-3.5 w-3.5" />}
                    {s.label}
                  </li>
                );
              })}
            </ol>
            <p className="mt-2 text-xs text-slate-500">
              Large group photos can take up to a minute. You can keep marking students; finalizing and photo changes wait until this finishes.
            </p>
          </div>
        )}
        {notice && <Alert tone="info">{notice}</Alert>}
        {!run_ && !running && (
          <p className="text-sm text-slate-500">
            {session.images.length ? "Run recognition to pre-fill students found in the classroom photos." : "Add at least one classroom photo, then run recognition."}
          </p>
        )}

        {run_ && finished && !running && (
          <>
            {run_.status === "failed" ? (
              <Alert>
                <p className="font-medium">Recognition failed</p>
                <p>{run_.error_message ?? "Attendance was not changed."}</p>
                {rec.can_run && <p className="mt-1">You can run it again, or mark students manually.</p>}
              </Alert>
            ) : (
              <>
                {justFinished && (
                  <p className="flex items-center gap-2 text-sm font-medium text-emerald-700 dark:text-emerald-300" role="status">
                    <CheckCircle2 className="h-4 w-4" /> Recognition complete
                    {groups.review.length > 0 && <span className="font-normal text-slate-600 dark:text-slate-300">— {groups.review.length} face(s) need your review</span>}
                  </p>
                )}
                <dl className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6" aria-label="Recognition summary">
                  {(
                    [
                      ["Faces detected", run_.faces_detected],
                      ["Matched", groups.matched.length],
                      ["Needs review", groups.review.length],
                      ["Unknown", groups.unknown.length],
                      ["Marked by you", groups.manual.length],
                      ["Recognized", `${run_.students_recognized} / ${run_.roster_size}`],
                    ] as const
                  ).map(([k, v]) => (
                    <div key={k} className="rounded-lg border border-slate-200 px-3 py-2 dark:border-slate-800">
                      <dt className="text-xs text-slate-500">{k}</dt>
                      <dd className="text-lg font-semibold tabular-nums">{v}</dd>
                    </div>
                  ))}
                </dl>
              </>
            )}
            <p className="text-xs text-slate-500">
              Run {formatDateTime(run_.finished_at ?? run_.started_at)}
              {run_.started_by_name ? ` by ${run_.started_by_name}` : ""} · {run_.applied_count} pre-filled · {run_.preserved_count} teacher decision(s) kept
              {run_.thresholds && ` · thresholds ${pct(run_.thresholds.confident)} / ${pct(run_.thresholds.low)}`}
            </p>
            {run_.diagnostics && <Diagnostics run={run_} />}
            {run_.warnings.length > 0 && (
              <Alert tone="warning">
                <ul className="list-disc space-y-0.5 pl-4">
                  {run_.warnings.map((w) => <li key={w}>{w}</li>)}
                </ul>
                {run_.missing_students.length > 0 && (
                  <p className="mt-1">
                    Not recognisable automatically: {run_.missing_students.map((s) => `${s.registration_no} (${s.full_name})`).join(", ")}
                  </p>
                )}
              </Alert>
            )}

            {/* Classroom photos with face boxes */}
            {faces.length > 0 && (
              <>
                <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-600 dark:text-slate-300" aria-label="Face box colours">
                  {(["matched", "review", "unknown", "manual"] as const).map((g) => (
                    <li key={g} className="flex items-center gap-1.5">
                      <span className={cn("inline-block h-3 w-3 rounded-sm border-2", GROUP_STYLE[g].swatch)} aria-hidden /> {GROUP_STYLE[g].label}
                    </li>
                  ))}
                </ul>
                {/* items-start: each figure is exactly its photo's height, so %-positioned boxes line up */}
                <div className="grid items-start gap-3 sm:grid-cols-2">
                  {session.images.map((img, i) => {
                    const own = faces.filter((f) => f.image_id === img.id);
                    const url = imageUrls[img.image_url];
                    return (
                      <figure key={img.id} className="relative overflow-hidden rounded-lg bg-slate-100 dark:bg-slate-800">
                        {url ? <img src={url} alt={`Classroom photo ${i + 1} with detected faces`} className="block h-auto w-full" /> : <div className="aspect-[4/3]" />}
                        {own.map((f) => {
                          const g = faceGroup(f);
                          const who = g === "matched" || g === "manual" ? (f.assigned ?? f.suggested) : null;
                          return (
                            <button
                              key={f.id}
                              type="button"
                              onClick={() => setSelected(f.id)}
                              aria-label={`Face ${f.face_index + 1}: ${GROUP_STYLE[g].label}${who ? ` — ${who.full_name}` : ""}`}
                              className={cn("absolute rounded border-2 shadow-[0_0_0_1px_rgba(0,0,0,0.35)]", GROUP_STYLE[g].box, selected === f.id && "ring-2 ring-brand-500 ring-offset-1")}
                              style={{
                                left: `${(f.bbox.x / f.image_width) * 100}%`,
                                top: `${(f.bbox.y / f.image_height) * 100}%`,
                                width: `${(f.bbox.width / f.image_width) * 100}%`,
                                height: `${(f.bbox.height / f.image_height) * 100}%`,
                              }}
                            />
                          );
                        })}
                        <figcaption className="absolute bottom-1 left-1 rounded bg-black/60 px-1.5 text-[11px] text-white">
                          Photo {i + 1} · {own.length} face(s)
                        </figcaption>
                      </figure>
                    );
                  })}
                </div>
              </>
            )}

            {groups.matched.length > 0 && (
              <section aria-labelledby="rec-matched">
                <button id="rec-matched" type="button" onClick={() => setShowMatched((s) => !s)} aria-expanded={showMatched} className="mb-2 flex items-center gap-1.5 text-sm font-semibold">
                  <Check className="h-4 w-4 text-emerald-600" /> Confident matches ({groups.matched.length})
                  <ChevronDown className={cn("h-4 w-4 transition-transform", showMatched && "rotate-180")} />
                </button>
                {showMatched && (
                  <ul className="grid gap-2 sm:grid-cols-2">
                    {groups.matched.map((f) => (
                      <FaceRow key={f.id} face={f} url={urlFor(f.image_id)} selected={selected === f.id} busy={busyFace === f.id}>
                        <p className="text-sm">
                          <strong>{(f.assigned ?? f.suggested)?.registration_no}</strong> {(f.assigned ?? f.suggested)?.full_name}
                        </p>
                        <p className="text-xs text-slate-500">
                          {pct(f.similarity)} ·{" "}
                          {f.decision === "applied" ? "Pre-filled Present by AI" : f.decision === "none" ? "Also seen in another photo" : "Confirmed by you"}
                        </p>
                        {editable && ["applied", "accepted", "assigned"].includes(f.decision) && (
                          <Button size="sm" variant="ghost" className="mt-1" onClick={() => void act((v) => recognitionApi.reject(f.id, v), f.id, "Match removed.")}>
                            <X className="h-4 w-4" /> Not this student
                          </Button>
                        )}
                      </FaceRow>
                    ))}
                  </ul>
                )}
              </section>
            )}

            {groups.review.length > 0 && (
              <section aria-labelledby="rec-review">
                <h3 id="rec-review" className="mb-1 flex items-center gap-2 text-sm font-semibold">
                  <AlertTriangle className="h-4 w-4 text-amber-500" /> Needs review ({groups.review.length})
                </h3>
                <p className="mb-2 text-xs text-slate-500">Not marked until you accept. Accept the suggestion, choose the right student, or reject it.</p>
                <ul className="space-y-2">
                  {groups.review.map((f) => (
                    <FaceRow key={f.id} face={f} url={urlFor(f.image_id)} selected={selected === f.id} busy={busyFace === f.id}>
                      <p className="text-sm">
                        {f.category === "ambiguous" ? "Two students look similar: " : f.category === "duplicate" ? "Possible duplicate of " : "Possible match: "}
                        <strong>{f.suggested?.registration_no} {f.suggested?.full_name}</strong> ({pct(f.similarity)})
                        {f.category === "ambiguous" && f.second && <> or <strong>{f.second.registration_no} {f.second.full_name}</strong> ({pct(f.second_similarity)})</>}
                      </p>
                      {editable && (
                        <div className="mt-2 flex flex-wrap items-center gap-2">
                          {f.suggested && (
                            <Button size="sm" onClick={() => void act((v) => recognitionApi.accept(f.id, v), f.id, `Marked ${f.suggested!.full_name} present.`)}>
                              <Check className="h-4 w-4" /> Accept {f.suggested.registration_no}
                            </Button>
                          )}
                          {f.category === "ambiguous" && f.second && (
                            <Button size="sm" variant="secondary" onClick={() => void assign(f, f.second!.student_id)}>
                              <Check className="h-4 w-4" /> It’s {f.second.registration_no}
                            </Button>
                          )}
                          <StudentPicker roster={roster} linked={linked} onPick={(sid) => void assign(f, sid)} />
                          <Button size="sm" variant="ghost" aria-label={`Reject suggestion for face ${f.face_index + 1} (keep unknown)`} onClick={() => void act((v) => recognitionApi.reject(f.id, v), f.id)}>
                            <X className="h-4 w-4" /> Reject
                          </Button>
                        </div>
                      )}
                    </FaceRow>
                  ))}
                </ul>
              </section>
            )}

            {groups.unknown.length > 0 && (
              <section aria-labelledby="rec-unknown">
                <h3 id="rec-unknown" className="mb-1 flex items-center gap-2 text-sm font-semibold">
                  <HelpCircle className="h-4 w-4 text-slate-400" /> Unknown faces ({groups.unknown.length})
                </h3>
                <p className="mb-2 text-xs text-slate-500">No roster student matched — nobody was marked. Covered faces and visitors stay here unless you choose a student.</p>
                <ul className="grid gap-2 sm:grid-cols-2">
                  {groups.unknown.map((f) => (
                    <FaceRow key={f.id} face={f} url={urlFor(f.image_id)} selected={selected === f.id} busy={busyFace === f.id}>
                      <p className="text-sm text-slate-500">Not identified</p>
                      {editable && (
                        <div className="mt-2">
                          <StudentPicker roster={roster} linked={linked} onPick={(sid) => void assign(f, sid)} />
                        </div>
                      )}
                    </FaceRow>
                  ))}
                </ul>
              </section>
            )}

            {groups.manual.length > 0 && (
              <section aria-labelledby="rec-manual">
                <h3 id="rec-manual" className="mb-1 flex items-center gap-2 text-sm font-semibold">
                  <UserCheck className="h-4 w-4 text-sky-600" /> Manually marked students ({groups.manual.length})
                </h3>
                <p className="mb-2 text-xs text-slate-500">You had already marked these students, so recognition left your marks unchanged.</p>
                <ul className="grid gap-2 sm:grid-cols-2">
                  {groups.manual.map((f) => {
                    const st = f.suggested ? statusOf.get(f.suggested.student_id) : null;
                    return (
                      <FaceRow key={f.id} face={f} url={urlFor(f.image_id)} selected={selected === f.id} busy={busyFace === f.id}>
                        <p className="text-sm">
                          <strong>{f.suggested?.registration_no}</strong> {f.suggested?.full_name}
                        </p>
                        <p className="text-xs text-slate-500">
                          Your mark: {st ? STATUS_WORD[st] : "—"} · AI saw them ({pct(f.similarity)})
                        </p>
                      </FaceRow>
                    );
                  })}
                </ul>
              </section>
            )}
          </>
        )}
      </div>

      <ConfirmDialog
        open={!!moveConfirm}
        title="Move this match?"
        description="That student is already matched to another face. Move the match to this face instead?"
        confirmLabel="Move match"
        onConfirm={() => {
          const m = moveConfirm;
          setMoveConfirm(null);
          if (m) void act((v) => recognitionApi.assign(m.face.id, v, m.studentId, true), m.face.id, "Match moved.").catch(() => undefined);
        }}
        onCancel={() => setMoveConfirm(null)}
      />
    </Card>
  );
}

function Diagnostics({ run }: { run: RecognitionRun }) {
  const d = run.diagnostics!;
  const stages = d.detection_stages_ms;
  return (
    <details className="text-xs text-slate-500" role="group" aria-label="Recognition diagnostics">
      <summary className="cursor-pointer break-words">
        Model {d.model.replace("insightface/", "")}
        {d.fallback_from && <strong className="text-amber-700 dark:text-amber-300"> (fallback — {d.fallback_from} unavailable)</strong>}
        {" · "}
        {d.detector} · detection {secs(d.detection_ms)} · recognition {secs(d.recognition_ms)} · total {secs(d.total_ms)}
        {d.images.some((i) => i.rotation) && " · sideways photo auto-rotated"}
      </summary>
      <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-3 gap-y-0.5 break-words">
        {d.prepare_ms !== undefined && (<><dt>Preparing</dt><dd>{secs(d.prepare_ms)}</dd></>)}
        {d.decode_ms !== undefined && (<><dt>Reading photos</dt><dd>{secs(d.decode_ms)}</dd></>)}
        {stages && (<><dt>Detection</dt><dd>orientation {secs(stages.orient)} · full image {secs(stages.full)} · tiles {secs(stages.tiles)}</dd></>)}
        <dt>Matching</dt>
        <dd>{d.matching_ms} ms</dd>
        {d.images.map((img, i) => (
          <FragmentRow key={img.image_id} label={`Photo ${i + 1}`}>
            {img.faces} face(s){img.tiles ? ` · ${img.tiles} tiles` : ""}{img.rotation ? ` · rotated ${img.rotation}°` : ""}
            {img.merged_duplicates ? ` · ${img.merged_duplicates} duplicate box(es) merged` : ""}
          </FragmentRow>
        ))}
      </dl>
    </details>
  );
}

function FragmentRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{children}</dd>
    </>
  );
}

function FaceCrop({ face, url, size = 64 }: { face: RecognitionFace; url?: string; size?: number }) {
  // Pad the box a little and scale the whole photo so the face fills the thumbnail.
  const pad = 0.2;
  const bw = face.bbox.width * (1 + 2 * pad);
  const bh = face.bbox.height * (1 + 2 * pad);
  const side = Math.max(bw, bh);
  const scale = size / side;
  const x = face.bbox.x + face.bbox.width / 2 - side / 2;
  const y = face.bbox.y + face.bbox.height / 2 - side / 2;
  return (
    <div
      role="img"
      aria-label="Detected face"
      className="shrink-0 rounded-lg bg-slate-200 bg-no-repeat dark:bg-slate-700"
      style={{
        width: size,
        height: size,
        backgroundImage: url ? `url(${url})` : undefined,
        backgroundSize: `${face.image_width * scale}px ${face.image_height * scale}px`,
        backgroundPosition: `${-x * scale}px ${-y * scale}px`,
      }}
    />
  );
}

function FaceRow({ face, url, selected, busy, children }: { face: RecognitionFace; url?: string; selected: boolean; busy: boolean; children: ReactNode }) {
  const g = faceGroup(face);
  return (
    <li className={cn("flex min-w-0 gap-3 rounded-lg border p-2.5", selected ? "border-brand-500 ring-1 ring-brand-500" : "border-slate-200 dark:border-slate-800", busy && "opacity-60")}>
      <FaceCrop face={face} url={url} />
      <div className="min-w-0 flex-1">
        <Badge tone={GROUP_STYLE[g].badge}>{face.category === "ambiguous" ? "Ambiguous" : face.category === "duplicate" ? "Duplicate?" : face.category === "low_confidence" && g === "review" ? "Low confidence" : GROUP_STYLE[g].label}</Badge>
        <div className="mt-1">{children}</div>
      </div>
    </li>
  );
}

function StudentPicker({ roster, linked, onPick }: { roster: AttendanceSession["records"]; linked: Set<number | undefined>; onPick: (studentId: number) => void }) {
  return (
    <label className="inline-flex min-w-0 max-w-full items-center gap-1.5">
      <UserPlus className="h-4 w-4 shrink-0 text-slate-400" aria-hidden />
      <select
        aria-label="Choose a roster student for this face"
        defaultValue=""
        onChange={(e) => {
          if (e.target.value) onPick(Number(e.target.value));
          e.target.value = "";
        }}
        className="h-8 min-w-0 max-w-[14rem] rounded-lg border border-slate-300 bg-white px-2 text-sm dark:border-slate-700 dark:bg-slate-950"
      >
        <option value="">Choose student…</option>
        {roster.map((r) => (
          <option key={r.student_id} value={r.student_id}>
            {r.registration_no} — {r.full_name}
            {linked.has(r.student_id) ? " (matched)" : ""}
          </option>
        ))}
      </select>
    </label>
  );
}
