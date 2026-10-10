"""Single-password gate with a signed, HttpOnly session cookie (PRD §12.1)."""

import base64
import hashlib
import hmac
import json
import threading
import time
from collections import defaultdict, deque

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel

from .config import settings

COOKIE = "aiyt_session"
_MAX_ATTEMPTS = 5
_WINDOW_S = 600
_attempts: dict[str, deque] = defaultdict(deque)
_attempts_lock = threading.Lock()

router = APIRouter(prefix="/api/auth")


def _secret() -> bytes:
    if not settings.session_secret:
        raise HTTPException(status_code=500, detail={"code": "no_session_secret", "message": "सर्वर पर SESSION_SECRET सेट नहीं है।"})
    return settings.session_secret.encode("utf-8")


def make_token(ttl_s: int | None = None) -> str:
    exp = int(time.time()) + (ttl_s if ttl_s is not None else settings.session_hours * 3600)
    payload = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode()
    sig = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def verify_token(token: str | None) -> bool:
    if not token or "." not in token or not settings.session_secret:
        return False
    payload, sig = token.rsplit(".", 1)
    expected = hmac.new(_secret(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return False
    try:
        exp = json.loads(base64.urlsafe_b64decode(payload.encode()))["exp"]
    except Exception:
        return False
    return time.time() < exp


def is_authenticated(request: Request) -> bool:
    return verify_token(request.cookies.get(COOKIE))


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _rate_limited(ip: str) -> bool:
    now = time.time()
    with _attempts_lock:
        q = _attempts[ip]
        while q and now - q[0] > _WINDOW_S:
            q.popleft()
        return len(q) >= _MAX_ATTEMPTS


def _record_failure(ip: str) -> None:
    with _attempts_lock:
        _attempts[ip].append(time.time())


def reset_rate_limit() -> None:
    with _attempts_lock:
        _attempts.clear()


class LoginIn(BaseModel):
    password: str


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response):
    ip = _client_ip(request)
    if _rate_limited(ip):
        raise HTTPException(status_code=429, detail={"code": "too_many_attempts", "message": "बहुत ज़्यादा कोशिशें। 10 मिनट बाद फिर कोशिश करें।"})
    if not settings.app_password:
        raise HTTPException(status_code=500, detail={"code": "no_app_password", "message": "सर्वर पर APP_PASSWORD सेट नहीं है।"})
    if not hmac.compare_digest(body.password.encode("utf-8"), settings.app_password.encode("utf-8")):
        _record_failure(ip)
        time.sleep(0.5)
        raise HTTPException(status_code=401, detail={"code": "wrong_password", "message": "पासवर्ड ग़लत है।"})
    response.set_cookie(
        COOKIE, make_token(), httponly=True, samesite="lax", secure=settings.secure_cookies,
        max_age=settings.session_hours * 3600, path="/",
    )
    return {"ok": True}


@router.post("/logout")
def logout(response: Response):
    response.delete_cookie(COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(request: Request):
    return {"authenticated": is_authenticated(request)}
