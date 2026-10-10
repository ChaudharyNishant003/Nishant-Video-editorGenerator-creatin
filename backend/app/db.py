"""SQLite storage (PRD §8). No secrets in any table."""

import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL CHECK (kind IN ('edit','create')),
  title TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'draft',
  created_at REAL NOT NULL, updated_at REAL NOT NULL, settings_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS assets (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL, kind TEXT NOT NULL, path TEXT NOT NULL,
  mime TEXT, duration_s REAL, meta_json TEXT NOT NULL DEFAULT '{}', attribution TEXT,
  created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS transcripts (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL, provider TEXT, language TEXT,
  words_json TEXT NOT NULL, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS edit_plans (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL, version INTEGER NOT NULL, prompt TEXT,
  plan_json TEXT NOT NULL, approved_at REAL, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS scripts (
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL, facts_json TEXT, outline_json TEXT,
  chapters_json TEXT, created_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY, project_id TEXT, kind TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('queued','running','done','failed','cancelled')),
  step TEXT, progress REAL NOT NULL DEFAULT 0, log_json TEXT NOT NULL DEFAULT '[]',
  error TEXT, result_json TEXT, created_at REAL NOT NULL, started_at REAL, finished_at REAL
);
CREATE TABLE IF NOT EXISTS preferences (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS stock_cache (
  provider TEXT NOT NULL, query_hash TEXT NOT NULL, response_json TEXT NOT NULL,
  fetched_at REAL NOT NULL, PRIMARY KEY (provider, query_hash)
);
"""

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None


def db_path() -> Path:
    return settings.data_dir / "studio.sqlite3"


def conn() -> sqlite3.Connection:
    global _conn
    with _lock:
        if _conn is None:
            _conn = sqlite3.connect(db_path(), check_same_thread=False, isolation_level=None)
            _conn.row_factory = sqlite3.Row
            _conn.execute("PRAGMA journal_mode=WAL")
            _conn.executescript(SCHEMA)
        return _conn


@contextmanager
def locked():
    with _lock:
        yield conn()


def new_id() -> str:
    return uuid.uuid4().hex


def now() -> float:
    return time.time()


def row_to_dict(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    d = dict(row)
    for k in list(d):
        if k.endswith("_json") and isinstance(d[k], str):
            try:
                d[k[:-5]] = json.loads(d[k])
            except json.JSONDecodeError:
                d[k[:-5]] = None
            del d[k]
    return d


def reset_for_tests() -> None:
    """Close the shared connection (tests point DATA_DIR at a temp dir)."""
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None
