"""Restore drill: prove a SmartClass backup can actually be restored and used.

    .venv\\Scripts\\python.exe deploy\\windows\\restore_drill.py [--dump FILE] [--keep]

1. Restores the newest (or given) pg_dump file into a NEW database smartclass_restore_<timestamp>
   (never over the live one).
2. Compares the Alembic version and the exact row count of every table with the live database.
3. Starts a temporary backend on 127.0.0.1:8011 against the restored database and checks
   /health/ready and a real login, then stops it.
4. Drops the restored database (unless --keep).
Passwords are read from the ACL-restricted files in <deploy>\\config and never printed.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx
import psycopg2

DEPLOY = Path(os.environ.get("SMARTCLASS_DEPLOY_ROOT", r"D:\SmartClassDeploy"))
PROJECT = Path(__file__).resolve().parents[2]
PG_BIN = DEPLOY / "bin" / "pgsql" / "bin"
LIVE_DB, APP_USER = "smartclass_phase11", "smartclass_app"


def secret(name: str) -> str:
    return (DEPLOY / "config" / name).read_text().strip()


def connect(db: str, user: str, password: str):
    return psycopg2.connect(host="127.0.0.1", port=5432, dbname=db, user=user, password=password)


def snapshot(db: str) -> tuple[str, dict[str, int]]:
    with connect(db, APP_USER, secret("postgres-app.secret")) as con, con.cursor() as cur:
        cur.execute("SELECT version_num FROM alembic_version")
        version = cur.fetchone()[0]
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY 1")
        counts = {}
        for (table,) in cur.fetchall():
            cur.execute(f'SELECT count(*) FROM "{table}"')
            counts[table] = cur.fetchone()[0]
    return version, counts


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dump", type=Path)
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()
    dump = args.dump or max((DEPLOY / "backups").glob(f"{LIVE_DB}_*.dump"), key=lambda p: p.stat().st_mtime)
    target = f"smartclass_restore_{datetime.now():%Y%m%d_%H%M%S}"
    print(f"dump: {dump.name} ({dump.stat().st_size:,} bytes) -> new database {target}")
    failures = []

    admin = connect("postgres", "postgres", secret("postgres-superuser.secret"))
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute(f'CREATE DATABASE "{target}" OWNER {APP_USER} ENCODING \'UTF8\' TEMPLATE template0')
        cur.execute(f'REVOKE ALL ON DATABASE "{target}" FROM PUBLIC')
    env = {**os.environ, "PGPASSWORD": secret("postgres-app.secret")}
    started = time.perf_counter()
    r = subprocess.run([str(PG_BIN / "pg_restore.exe"), "-h", "127.0.0.1", "-U", APP_USER, "-d", target, "--no-owner",
                        "--exit-on-error", str(dump)], env=env, capture_output=True, text=True)
    print(f"pg_restore exit {r.returncode} in {time.perf_counter() - started:.1f} s")
    if r.returncode != 0:
        failures.append("pg_restore failed: " + r.stderr.strip()[:300])
    try:
        if not failures:
            live_version, live = snapshot(LIVE_DB)
            restored_version, restored = snapshot(target)
            print(f"alembic: live {live_version} / restored {restored_version}")
            if live_version != restored_version:
                failures.append("alembic version differs")
            diff = {t: (live.get(t), restored.get(t)) for t in sorted(set(live) | set(restored)) if live.get(t) != restored.get(t)}
            important = ("users", "students", "attendance_sessions", "attendance_records", "face_embeddings",
                         "student_face_images", "audit_logs", "attendance_recognition_runs")
            print("rows (live = restored): " + ", ".join(f"{t}={live.get(t)}" for t in important))
            print(f"tables compared: {len(live)}; differing: {diff or 'none'}")
            if diff:
                failures.append(f"row counts differ: {diff}")

            # The application itself on the restored database (temporary instance, loopback only).
            app_env = {**os.environ, "SMARTCLASS_ENV_FILE": str(DEPLOY / "config" / "production.env"),
                       "FACE_RECOGNITION_PRELOAD": "false",
                       "DATABASE_URL": f"postgresql+psycopg2://{APP_USER}:{secret('postgres-app.secret')}@127.0.0.1:5432/{target}"}
            proc = subprocess.Popen([str(PROJECT / ".venv" / "Scripts" / "python.exe"), "-m", "uvicorn", "backend.app.main:app",
                                     "--host", "127.0.0.1", "--port", "8011"], cwd=PROJECT, env=app_env,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                ready = None
                for _ in range(120):
                    try:
                        ready = httpx.get("http://127.0.0.1:8011/health/ready", timeout=2)
                        break
                    except httpx.HTTPError:
                        time.sleep(0.5)
                login = httpx.post("http://127.0.0.1:8011/api/v1/auth/login", timeout=30,
                                   json={"email": "teacher.cse@smartclass.edu", "password": "Demo@1234"})
                sessions = httpx.get("http://127.0.0.1:8011/api/v1/attendance/sessions", timeout=30,
                                     headers={"Authorization": "Bearer " + login.json().get("access_token", "")})
                print(f"app on restored DB: ready={ready and ready.status_code} login={login.status_code} "
                      f"history={sessions.status_code} ({sessions.json().get('total') if sessions.status_code == 200 else '-'} sessions)")
                if not (ready and ready.status_code == 200 and login.status_code == 200 and sessions.status_code == 200):
                    failures.append("application could not use the restored database")
            finally:
                proc.terminate()
                proc.wait(timeout=30)
    finally:
        if not args.keep:
            with admin.cursor() as cur:
                cur.execute(f'DROP DATABASE IF EXISTS "{target}" WITH (FORCE)')
            print(f"dropped {target}")
        admin.close()
    print("RESTORE DRILL:", "PASS" if not failures else f"FAIL {failures}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
