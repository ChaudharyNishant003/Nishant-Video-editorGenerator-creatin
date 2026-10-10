# STATUS.md — AI YT Studio v2 (branch `uat/ai-yt-studio-v2`)

Rule: nothing is marked done unless it was actually run. "Not tested" is stated explicitly.

## Phase 0 — de-risk (2026-10-10) ✅
See `docs/IMPLEMENTATION_PLAN.md` §1 and `docs/BENCHMARKS.md`. Update: Devanagari captions now also **verified with Noto Sans Devanagari inside the Linux Docker image** (local Docker, not Railway).

## Phase 1 — Foundation (2026-10-10)

### Built
- `backend/app/` (new; legacy `backend/main.py` untouched): config + `backend/.env` (gitignored), SQLite schema (PRD §8), password gate (signed HttpOnly SameSite=Lax cookie, 5 attempts / 10 min rate limit), security headers + strict CSP, provider registry (llm: Groq/Gemini/OpenRouter; stt: Groq Whisper (+ optional faster-whisper); tts: Edge-TTS with Hindi word timings (+ Kokoro/Sarvam/ElevenLabs placeholders disabled); image: Pollinations (+ Wikimedia placeholder); stock: Pexels/Pixabay with 24 h cache; avatar: built-in placeholder + premium placeholder), free-only fallback with retries/backoff and Hindi notices, key transport via `X-Provider-Keys` header (memory only), log redaction, job runner (thread pool, progress via `ffmpeg -progress`, SSE, cancel kills process tree, restart → jobs failed), preferences (secret-looking names refused), projects CRUD, `/api/jobs/selftest` diagnostic job, SPA serving of `frontend/dist`.
- `frontend/` (new; legacy `src/` untouched): Hindi mobile-first UI — Login, Home (two workflow cards + recent projects), Settings (per-capability default dropdown, tier badges, premium shown disabled "(जल्द)", "key डालो" hint, key inputs with Save/Test, status chips, "Key कैसे लें" links, honest browser-only note, Clear all keys, retention days, System check job with live progress + cancel), placeholders for Workflow A/B, hand-written PWA manifest + app-shell service worker + icons. Reuses root `node_modules` (no `npm install`).
- `Dockerfile` + `.dockerignore` + `backend/requirements-v2.txt`, `backend/.env.example`, launch configs (`v2 backend (UAT)` :8001, `v2 frontend (UAT)` :5174).

### Acceptance checks
| Check | Result | How |
|---|---|---|
| Unauthenticated `/api` and `/media` rejected | ✅ pass | pytest `test_unauthenticated_api_is_rejected`; container curl → 401 |
| Login rate limit | ✅ pass | pytest (6th attempt → 429) |
| Wrong/right password in UI | ✅ pass | browser: "पासवर्ड ग़लत है।", then Home |
| Sentinel-key test (DB, data dir, logs) | ✅ pass | pytest `test_sentinel_key_never_persisted_or_logged`; plus UI run with a fake Groq key → `grep` of `data/` = 0 matches, backend log clean |
| Key test end-to-end via UI (real Groq call with fake key) | ✅ pass | Settings → Save → "Key टेस्ट करें" → "Groq: key अमान्य है (401)" |
| Job cancel kills ffmpeg within seconds | ✅ pass | pytest (< 5 s) + UI cancel at 14 %, `tasklist` shows no ffmpeg |
| Job progress over SSE | ✅ pass | pytest + UI progress bar |
| Clear all keys | ✅ pass | UI; localStorage emptied, inputs cleared |
| Layout fits 380 px, tap targets ≥ 44 px | ✅ pass | 375 px emulation: no horizontal scroll; all controls ≥ 44 px (one fixed) |
| Production build + single-service serving + SW + manifest + CSP, no console errors | ✅ pass | `vite build`; opened on :8001 |
| Docker image builds; container serves API + SPA; Noto Devanagari + libass/HarfBuzz present | ✅ pass (local Docker) | `docker build`, `docker run`, caption frame rendered in-container |
| Edge-TTS Hindi word timings (real network) | ✅ pass | pytest `test_edge_tts_hindi_word_timings_real` |
| Free-only fallback, never auto-premium, retry/backoff | ✅ pass (mocked) | pytest |
| PWA install on a real phone | ❌ not tested | needs phone on same network / online URL |
| Real provider calls with valid keys (Groq chat, Gemini, Groq Whisper Hindi, Pexels/Pixabay) | ❌ not tested — needs key | 4 tests skipped; owner adds keys on Settings page, then re-run |
| Anything on Railway | ❌ not tested | deferred by owner |

Test totals (backend): **23 passed, 4 skipped (needs key)**. Frontend: `tsc --noEmit` strict ✅ (no unit tests; legacy Vitest still not installed).

## How to run (local)
1. Backend: `backend/.venv/Scripts/python.exe -m uvicorn app.main:app --app-dir backend --port 8001` (password in `backend/.env`).
2. Frontend dev: `node node_modules/vite/bin/vite.js --config frontend/vite.config.ts` → http://localhost:5174
   or production-like: build (`node node_modules/vite/bin/vite.js build --config frontend/vite.config.ts`) and open http://localhost:8001
3. Tests: `backend/.venv/Scripts/python.exe -m pytest backend/tests -q`
