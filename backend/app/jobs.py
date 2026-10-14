"""In-process job runner backed by SQLite (PRD §7.1, §12).

- Worker thread pool (concurrency from JOB_CONCURRENCY, default 1).
- Progress/step/log persisted in the jobs table (log lines are redacted).
- Cancel kills the running ffmpeg subprocess (process tree) within a few seconds.
- Provider keys live only in the in-memory JobContext; a server restart fails running jobs.
"""

from __future__ import annotations

import io
import json
import os
import signal
import subprocess
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Iterable

from . import db
from .config import settings
from .render.ffmpeg import ffmpeg_exe
from .security.redact import redact

TERMINAL = ("done", "failed", "cancelled")


class JobCancelled(Exception):
    pass


class JobContext:
    def __init__(self, job_id: str, keys: dict):
        self.id = job_id
        self.keys = keys  # in memory only — never persisted
        self.cancel_event = threading.Event()
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    # --- reporting ---------------------------------------------------------
    def log(self, message: str, level: str = "info") -> None:
        entry = {"t": round(time.time(), 2), "level": level, "msg": redact(str(message))}
        with db.locked() as c:
            row = c.execute("SELECT log_json FROM jobs WHERE id=?", (self.id,)).fetchone()
            log = json.loads(row["log_json"]) if row else []
            log.append(entry)
            c.execute("UPDATE jobs SET log_json=? WHERE id=?", (json.dumps(log, ensure_ascii=False), self.id))

    def progress(self, pct: float, step: str | None = None) -> None:
        pct = max(0.0, min(100.0, float(pct)))
        with db.locked() as c:
            if step is None:
                c.execute("UPDATE jobs SET progress=? WHERE id=?", (pct, self.id))
            else:
                c.execute("UPDATE jobs SET progress=?, step=? WHERE id=?", (pct, step, self.id))

    def check_cancelled(self) -> None:
        if self.cancel_event.is_set():
            raise JobCancelled()

    # --- ffmpeg -----------------------------------------------------------
    def run_ffmpeg(self, args: list[str], expected_duration_s: float | None = None,
                   pct_from: float = 0.0, pct_to: float = 100.0, step: str | None = None,
                   cwd: str | None = None, collect_stderr: bool = False,
                   stdin_frames: Iterable[bytes] | None = None) -> list[str]:
        """Run ffmpeg with -progress on stdout; maps out_time to job progress; cancellable.
        Returns the stderr lines when collect_stderr (e.g. silencedetect output), else [].
        stdin_frames: raw bytes fed to ffmpeg's stdin by a writer thread (use `-i pipe:0` in args),
        e.g. avatar frames rendered in Python."""
        self.check_cancelled()
        cmd = [ffmpeg_exe(), "-hide_banner", *([] if stdin_frames is not None else ["-nostdin"]), "-y",
               "-progress", "pipe:1", "-nostats", *args]
        kwargs: dict = {"stdout": subprocess.PIPE, "stderr": subprocess.PIPE, "cwd": cwd,
                        "stdin": subprocess.PIPE if stdin_frames is not None else subprocess.DEVNULL}
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        if step:
            self.progress(pct_from, step)
        with self._lock:
            self._proc = subprocess.Popen(cmd, **kwargs)
        proc = self._proc
        stdout = io.TextIOWrapper(proc.stdout, encoding="utf-8", errors="replace")
        stderr = io.TextIOWrapper(proc.stderr, encoding="utf-8", errors="replace")
        stderr_tail: list[str] = []
        stderr_all: list[str] = []
        feed_errors: list[BaseException] = []

        def _drain_stderr():
            for line in stderr:
                stderr_tail.append(line.rstrip())
                del stderr_tail[:-30]
                if collect_stderr:
                    stderr_all.append(line.rstrip())

        def _feed_stdin():
            try:
                for chunk in stdin_frames:
                    if self.cancel_event.is_set():
                        break
                    proc.stdin.write(chunk)
            except (BrokenPipeError, ConnectionResetError, ValueError, OSError):
                pass  # ffmpeg exited early; its return code tells the story
            except BaseException as e:  # a bug in the frame generator must fail the job
                feed_errors.append(e)
                self._kill()
            finally:
                try:
                    proc.stdin.close()
                except Exception:
                    pass

        t = threading.Thread(target=_drain_stderr, daemon=True)
        t.start()
        feeder = None
        if stdin_frames is not None:
            feeder = threading.Thread(target=_feed_stdin, daemon=True)
            feeder.start()
        try:
            for line in stdout:
                if self.cancel_event.is_set():
                    self._kill()
                    break
                if expected_duration_s and line.startswith("out_time_us="):
                    try:
                        us = int(line.split("=", 1)[1])
                        frac = min(1.0, us / 1e6 / expected_duration_s)
                        self.progress(pct_from + (pct_to - pct_from) * frac)
                    except ValueError:
                        pass
            proc.wait()
        finally:
            if feeder is not None:
                feeder.join(timeout=5)
            t.join(timeout=2)
            with self._lock:
                self._proc = None
        if self.cancel_event.is_set():
            raise JobCancelled()
        if feed_errors:
            raise feed_errors[0]
        if proc.returncode != 0:
            raise RuntimeError("ffmpeg विफल (code %s): %s" % (proc.returncode, " | ".join(stderr_tail[-5:])))
        self.progress(pct_to)
        return stderr_all

    def _kill(self) -> None:
        with self._lock:
            proc = self._proc
        if proc is None or proc.poll() is not None:
            return
        try:
            if sys.platform == "win32":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
            else:
                os.killpg(proc.pid, signal.SIGKILL)
        except Exception:
            proc.kill()

    def cancel(self) -> None:
        self.cancel_event.set()
        self._kill()


class JobRunner:
    def __init__(self, workers: int):
        self._pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="job")
        self._active: dict[str, JobContext] = {}
        self._lock = threading.Lock()

    def recover_after_restart(self) -> None:
        with db.locked() as c:
            c.execute(
                "UPDATE jobs SET status='failed', error=?, finished_at=? WHERE status IN ('queued','running')",
                ("सर्वर restart हुआ — job फिर से चलाएँ (keys memory में थीं, सहेजी नहीं जातीं)।", time.time()),
            )

    def submit(self, kind: str, fn: Callable[[JobContext], dict | None], keys: dict | None = None,
               project_id: str | None = None) -> str:
        job_id = db.new_id()
        with db.locked() as c:
            c.execute("INSERT INTO jobs(id, project_id, kind, status, progress, log_json, created_at) VALUES (?,?,?,?,?,?,?)",
                      (job_id, project_id, kind, "queued", 0, "[]", time.time()))
        ctx = JobContext(job_id, keys or {})
        with self._lock:
            self._active[job_id] = ctx
        self._pool.submit(self._run, ctx, fn)
        return job_id

    def _run(self, ctx: JobContext, fn) -> None:
        if ctx.cancel_event.is_set():
            self._finish(ctx, "cancelled", None, None)
            return
        with db.locked() as c:
            c.execute("UPDATE jobs SET status='running', started_at=? WHERE id=?", (time.time(), ctx.id))
        try:
            result = fn(ctx)
            self._finish(ctx, "done", result, None)
        except JobCancelled:
            ctx.log("Job रद्द किया गया।", "warn")
            self._finish(ctx, "cancelled", None, None)
        except Exception as e:
            ctx.log(redact("".join(traceback.format_exception_only(type(e), e)).strip()), "error")
            self._finish(ctx, "failed", None, redact(str(e)))
        finally:
            ctx.keys = {}
            with self._lock:
                self._active.pop(ctx.id, None)

    def _finish(self, ctx: JobContext, status: str, result, error) -> None:
        with db.locked() as c:
            c.execute("UPDATE jobs SET status=?, result_json=?, error=?, finished_at=?, progress=CASE WHEN ?='done' THEN 100 ELSE progress END WHERE id=?",
                      (status, json.dumps(result, ensure_ascii=False) if result is not None else None, error, time.time(), status, ctx.id))

    def cancel(self, job_id: str) -> bool:
        with self._lock:
            ctx = self._active.get(job_id)
        if ctx is None:
            return False
        ctx.cancel()
        return True

    def get(self, job_id: str) -> dict | None:
        with db.locked() as c:
            row = c.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return db.row_to_dict(row)


runner = JobRunner(settings.job_concurrency)
