"""Project media folders + asset rows. Everything lives under DATA_DIR/projects/<project_id>/."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from . import db
from .config import settings


def project_dir(project_id: str) -> Path:
    if not project_id.isalnum():
        raise ValueError("bad project id")
    d = settings.data_dir / "projects" / project_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def remove_project_dir(project_id: str) -> None:
    if project_id.isalnum():
        shutil.rmtree(settings.data_dir / "projects" / project_id, ignore_errors=True)


def add_asset(project_id: str, kind: str, path: Path, mime: str | None = None, duration_s: float | None = None,
              meta: dict | None = None, attribution: str | None = None) -> dict:
    aid = db.new_id()
    with db.locked() as c:
        c.execute("INSERT INTO assets(id, project_id, kind, path, mime, duration_s, meta_json, attribution, created_at) "
                  "VALUES (?,?,?,?,?,?,?,?,?)",
                  (aid, project_id, kind, str(path), mime, duration_s, json.dumps(meta or {}, ensure_ascii=False),
                   attribution, db.now()))
    return get_asset(aid)


def get_asset(asset_id: str) -> dict | None:
    with db.locked() as c:
        return db.row_to_dict(c.execute("SELECT * FROM assets WHERE id=?", (asset_id,)).fetchone())


def list_assets(project_id: str, kinds: tuple[str, ...] | None = None) -> list[dict]:
    with db.locked() as c:
        rows = c.execute("SELECT * FROM assets WHERE project_id=? ORDER BY created_at", (project_id,)).fetchall()
    out = [db.row_to_dict(r) for r in rows]
    return [a for a in out if kinds is None or a["kind"] in kinds]


def latest_asset(project_id: str, kind: str) -> dict | None:
    items = list_assets(project_id, (kind,))
    return items[-1] if items else None


def set_status(project_id: str, status: str) -> None:
    with db.locked() as c:
        c.execute("UPDATE projects SET status=?, updated_at=? WHERE id=?", (status, db.now(), project_id))


def public_asset(a: dict) -> dict:
    """Asset fields safe for the UI (no server paths)."""
    meta = a.get("meta") or {}
    return {"id": a["id"], "kind": a["kind"], "mime": a.get("mime"), "duration_s": a.get("duration_s"),
            "name": meta.get("name"), "meta": {k: v for k, v in meta.items() if k != "path"},
            "attribution": a.get("attribution"), "url": f"/api/assets/{a['id']}", "created_at": a.get("created_at")}
