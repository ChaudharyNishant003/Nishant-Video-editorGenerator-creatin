"""Settings from environment (and an optional backend/.env file). No provider keys ever live here."""

import os
from dataclasses import dataclass
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_DIR = BACKEND_DIR.parent


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_dotenv(BACKEND_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    app_password: str
    session_secret: str
    data_dir: Path
    max_upload_mb: int
    max_upload_seconds: int
    job_concurrency: int
    retention_days: int
    session_hours: int
    frontend_dist: Path
    secure_cookies: bool


def load_settings() -> Settings:
    data_dir = Path(os.environ.get("DATA_DIR") or (REPO_DIR / "data")).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    return Settings(
        app_password=os.environ.get("APP_PASSWORD", ""),
        session_secret=os.environ.get("SESSION_SECRET", ""),
        data_dir=data_dir,
        max_upload_mb=int(os.environ.get("MAX_UPLOAD_MB", "300")),
        max_upload_seconds=int(os.environ.get("MAX_UPLOAD_SECONDS", "180")),
        job_concurrency=max(1, int(os.environ.get("JOB_CONCURRENCY", "1"))),
        retention_days=int(os.environ.get("RETENTION_DAYS", "30")),
        session_hours=int(os.environ.get("SESSION_HOURS", "720")),
        frontend_dist=Path(os.environ.get("FRONTEND_DIST") or (REPO_DIR / "frontend" / "dist")).resolve(),
        secure_cookies=os.environ.get("SECURE_COOKIES", "0") == "1",
    )


settings = load_settings()
