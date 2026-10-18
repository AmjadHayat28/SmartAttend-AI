"""Minimal process supervisor for running SmartClass on Windows without administrator rights.

Started by a Task Scheduler task (at logon) with pythonw.exe, it keeps ONE child process running:

    pythonw supervise.py --name backend --run-dir D:\\SmartClassDeploy\\run --log-dir D:\\SmartClassDeploy\\logs
        --cwd D:\\Projects\\smartclass-attendance --env SMARTCLASS_ENV_FILE=D:\\...\\production.env
        -- D:\\...\\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8001

- Restarts the child whenever it exits, with backoff (1 s doubling to 30 s; reset after 60 s up).
- Child stdout+stderr → <log-dir>/<name>.log, timestamped, rotated at 10 MB (5 files kept).
- One instance per name (a lock file): a second start exits immediately.
- Stop cleanly: create <run-dir>/<name>.stop. The
  optional --stop-command runs first (e.g. pg_ctl stop -m fast), then the child is terminated.
  (`supervise.py --name X --run-dir D --stop` creates the stop file.)
- The child and all its descendants run in a Windows Job Object that is closed with the
  supervisor, so killing the supervisor never leaves orphans (e.g. uvicorn workers holding a port).
- No secrets are logged: the command line is logged, environment values are not.
Standard library only.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import threading
import time
from ctypes import wintypes
from datetime import datetime
from pathlib import Path

MAX_LOG_BYTES = 10 * 1024 * 1024
LOG_BACKUPS = 5


class RotatingLog:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        self.fh = open(path, "a", encoding="utf-8", errors="replace")

    def _rotate(self) -> None:
        self.fh.close()
        for i in range(LOG_BACKUPS - 1, 0, -1):
            src, dst = self.path.with_name(f"{self.path.name}.{i}"), self.path.with_name(f"{self.path.name}.{i + 1}")
            if src.exists():
                os.replace(src, dst)
        os.replace(self.path, self.path.with_name(f"{self.path.name}.1"))
        self.fh = open(self.path, "a", encoding="utf-8", errors="replace")

    def write(self, line: str) -> None:
        stamp = datetime.now().astimezone().isoformat(timespec="seconds")
        with self.lock:
            self.fh.write(f"{stamp} {line.rstrip()}\n")
            self.fh.flush()
            if self.fh.tell() > MAX_LOG_BYTES:
                self._rotate()


# ── Windows Job Object: kill the whole process tree with the supervisor ──
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
_JobObjectExtendedLimitInformation = 9


class _IO_COUNTERS(ctypes.Structure):
    _fields_ = [(n, ctypes.c_ulonglong) for n in ("r", "w", "o", "rb", "wb", "ob")]


class _BASIC(ctypes.Structure):
    _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]


class _EXTENDED(ctypes.Structure):
    _fields_ = [("BasicLimitInformation", _BASIC), ("IoInfo", _IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]


def _make_kill_on_close_job():
    if os.name != "nt":
        return None
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateJobObjectW.restype = wintypes.HANDLE
    k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    job = k32.CreateJobObjectW(None, None)
    info = _EXTENDED()
    info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    k32.SetInformationJobObject(job, _JobObjectExtendedLimitInformation, ctypes.byref(info), ctypes.sizeof(info))
    return k32, job


def _assign(job, proc: subprocess.Popen) -> None:
    if job is not None:
        k32, handle = job
        k32.AssignProcessToJobObject(handle, wintypes.HANDLE(int(proc._handle)))


def _single_instance(run_dir: Path, name: str):
    """Hold an exclusive lock for this name; None if another supervisor already holds it."""
    import msvcrt

    fh = open(run_dir / f"{name}.lock", "a+")
    try:
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        fh.close()
        return None
    return fh


def _pump(stream, log: RotatingLog) -> None:
    for raw in iter(stream.readline, b""):
        log.write(raw.decode("utf-8", errors="replace"))


def supervise(args) -> int:
    run_dir, log_dir = Path(args.run_dir), Path(args.log_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    lock = _single_instance(run_dir, args.name)
    log = RotatingLog(log_dir / f"{args.name}.log")
    if lock is None:
        log.write(f"[supervisor] another '{args.name}' supervisor is already running; exiting")
        return 0
    stop_file = run_dir / f"{args.name}.stop"
    stop_file.unlink(missing_ok=True)
    env = os.environ.copy()
    for item in args.env or []:
        key, _, value = item.partition("=")
        env[key] = value
    job = _make_kill_on_close_job()
    flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    backoff, restarts = 1.0, 0
    log.write(f"[supervisor] pid {os.getpid()} supervising '{args.name}': {' '.join(args.command)}")
    while not stop_file.exists():
        started = time.monotonic()
        try:
            proc = subprocess.Popen(args.command, cwd=args.cwd, env=env, stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, creationflags=flags)
        except OSError as exc:
            log.write(f"[supervisor] could not start: {exc}")
            proc = None
        if proc is not None:
            _assign(job, proc)
            (run_dir / f"{args.name}.pid").write_text(json.dumps(
                {"supervisor": os.getpid(), "child": proc.pid, "started": datetime.now().isoformat(),
                 "restarts": restarts}))
            log.write(f"[supervisor] started child pid {proc.pid} (restart #{restarts})")
            reader = threading.Thread(target=_pump, args=(proc.stdout, log), daemon=True)
            reader.start()
            while proc.poll() is None:
                if stop_file.exists():
                    log.write("[supervisor] stop requested")
                    if args.stop_command:
                        subprocess.run(args.stop_command, shell=True, cwd=args.cwd, env=env, timeout=60,
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
                        try:
                            proc.wait(timeout=30)
                        except subprocess.TimeoutExpired:
                            pass
                    if proc.poll() is None:
                        proc.terminate()
                        proc.wait(timeout=30)
                    break
                time.sleep(0.5)
            reader.join(timeout=5)
            log.write(f"[supervisor] child pid {proc.pid} exited with code {proc.returncode}")
        if stop_file.exists():
            break
        if time.monotonic() - started > 60:
            backoff = 1.0  # it ran fine for a while: restart quickly
        log.write(f"[supervisor] restarting in {backoff:.0f} s")
        deadline = time.monotonic() + backoff
        while time.monotonic() < deadline and not stop_file.exists():
            time.sleep(0.2)
        backoff = min(backoff * 2, 30.0)
        restarts += 1
    stop_file.unlink(missing_ok=True)
    (run_dir / f"{args.name}.pid").unlink(missing_ok=True)
    log.write("[supervisor] stopped")
    return 0


def request_stop(args) -> int:
    (Path(args.run_dir) / f"{args.name}.stop").write_text("stop")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--name", required=True)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--log-dir", default=None)
    parser.add_argument("--cwd", default=None)
    parser.add_argument("--env", action="append", help="KEY=VALUE for the child (value not logged)")
    parser.add_argument("--stop-command", default=None)
    parser.add_argument("--stop", action="store_true", help="ask the running supervisor of --name to stop")
    argv = sys.argv[1:]
    split = argv.index("--") if "--" in argv else len(argv)
    args = parser.parse_args(argv[:split])
    args.command = argv[split + 1:]
    if args.stop:
        return request_stop(args)
    if not args.command or not args.log_dir:
        parser.error("needs --log-dir and the command to run after --")
    return supervise(args)


if __name__ == "__main__":
    sys.exit(main())
