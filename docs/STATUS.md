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

## Phase 2 — Workflow A "edit my video" (2026-10-11)

### Built
- **Backend** (`backend/app/edit/`, `storage.py`, `render/probe.py`, `render/fonts.py`):
  - Streamed raw-body upload. Limits: 300 MB, 180 s, extension whitelist. Validated with ffprobe, or by parsing `ffmpeg -i` locally, because the bundled ffmpeg has no ffprobe. A partial upload leaves nothing behind, so retrying works.
  - **Ingest job:** converts to constant frame rate (fps rounded, capped at 30), shortest side capped at 720, H.264 + AAC. Phone rotation is applied. A silent track is added if the video has no audio. Also writes 16 kHz FLAC for STT.
  - **Transcribe job:** STT with free-only fallback. Groq Whisper uses word timestamps.
  - **LLM planner:** Hindi/Hinglish/English prompt plus transcript → JSON plan. Parsed leniently; one repair retry on the same provider, then the next free LLM.
  - **Plan validator (pydantic):**
    - Accepts `1:05`-style times.
    - Clamps to the video length with a Hindi warning; drops `start ≥ end`; merges overlapping cuts.
    - Resolves zoom/speed/b-roll conflicts; allows one captions/music/cleanup op.
    - Clamps parameters; checks referenced uploads; refuses "cut everything".
    - Passes through the LLM's clarifying `question` and the `proposed_by_ai` flag.
  - **Compiler:**
    - Original→output **time map**, frame-aligned.
    - Each piece (cut / speed / zoom) is rendered as a frame-exact segment (H.264 + PCM, so no AAC drift), then concatenated.
    - Final pass:
      - b-roll (stock search + download with attribution, or the user's own upload; overlay or replace mode)
      - Devanagari ASS captions (word highlight or line style, remapped through the time map) and text overlays
      - music with sidechain ducking
      - `afftdn` denoise and `loudnorm`
    - Output duration is **verified against the time map (±0.1 s)**; the render fails loudly otherwise.
  - Re-render without re-upload, using plan versions. Cancelling cleans up partial files.
  - Asset streaming with HTTP Range support. Deleting a project removes its media folder.
- **Frontend:**
  - `#/edit`: upload with progress and language choice.
  - `#/edit/<id>`:
    - video player and ingest progress
    - transcript, which starts automatically; tapping a timestamp seeks the video
    - prompt → "AI से प्लान बनाओ"
    - editable plan rows for all 9 ops: ⏱ "now" time button, delete, "+ जोड़ो", music/b-roll upload
    - AI question and warnings
    - "मंज़ूर करो और वीडियो बनाओ" (nothing renders before this)
    - progress, cancel and log
    - result player and download, with attribution
  - Home lists edit projects with their status.

### Bug found and fixed during testing (important)
- The `subtitles` filter in ffmpeg does **not** enable HarfBuzz shaping, so conjuncts broke ("क्षत्रिय" was drawn as "क्षत्रयि"). Phase 0 had used the `ass` filter. The renderer now uses `ass=…:shaping=complex`, and a regression test measures the ink width of "क्ष" with complex vs simple shaping.
- `crop` cannot follow per-frame size changes, so zoom was off-centre. Zoom now uses `zoompan` after `fps=`, and a test checks where the bar ends up after zoom.

### Acceptance checks (PRD §14 Workflow A)
| Check | Result | How |
|---|---|---|
| 60 s sample with cut + overlay + zoom + captions: duration = time map; cut boundaries within 0.2 s | ✅ pass | pytest `test_cut_overlay_zoom_captions`: synthetic video whose bar position encodes source time; frames checked either side of the cut, plus zoom geometry |
| Devanagari captions visually correct (conjuncts) | ✅ pass | frames inspected on Windows (Nirmala UI) and in the Linux container (Noto Sans Devanagari); automatic shaping regression test |
| Invalid LLM output is repaired or falls back, never crashes | ✅ pass (mocked LLMs) | invalid JSON → repaired on the same provider; garbage twice → Gemini with a "switch" notice; all fail → clear `all_failed` |
| Timestamp past the end → warning, not failure | ✅ pass | pytest + API (8 s clip, cut at 12–18 s is dropped with a warning) |
| Silence removal keeps audio in sync | ✅ pass | pytest: tone onsets in the output line up with the video's source time within 0.15 s at all 14 joins |
| Speed, music + ducking, b-roll (overlay/replace), denoise/loudnorm | ✅ pass | pytest: duration exact, speed-up mapping checked, replace-mode frame colour checked |
| Upload guards (type, size, length, no video, interrupted) / no-audio video / portrait video | ✅ pass | pytest |
| Sentinel key through transcribe / plan / render (stock) jobs | ✅ pass | pytest: data dir, SQLite, logs and responses are all clean |
| Cancel during render (UI and API) | ✅ pass | UI: cancelled at 41 %, no ffmpeg left, earlier output still playable; pytest: no partial files remain |
| Full UI flow in the browser (upload → ingest → plan rows → save → approve → result → re-render → cancel) | ✅ pass | Vite dev server + production build on :8001 (videos play under CSP, no console errors); 375 px: no horizontal scroll, all tap targets ≥ 44 px |
| Whole suite inside the Linux Docker image (Debian ffmpeg 7.1.5, real ffprobe, Noto) | ✅ pass | 52 passed, 4 skipped |
| **Real Groq Whisper Hindi transcription** | ❌ not tested — needs key | the demo transcript was injected from Edge-TTS word timings; the UI shows the "no key" error correctly |
| **Real LLM plan from a prompt (Groq/Gemini/OpenRouter)** | ❌ not tested — needs key | without a key the UI says "Settings में key डालें"; manual plan rows work |
| **Stock b-roll search/download (Pexels/Pixabay)** | ❌ not tested — needs key | without a key the b-roll op is skipped with a visible notice and the render still finishes |
| A real phone-recorded video (VFR, rotation) | ❌ not tested | logic is covered by a synthetic portrait test; no real phone file was available |

Test totals (backend): **52 passed, 4 skipped (needs key)**, the same on Windows and in the Linux container. Frontend: `tsc` strict ✅, `vite build` ✅.

## How to run (local)
1. Backend: `backend/.venv/Scripts/python.exe -m uvicorn app.main:app --app-dir backend --port 8001` (password in `backend/.env`).
2. Frontend dev: `node node_modules/vite/bin/vite.js --config frontend/vite.config.ts` → http://localhost:5174
   or production-like: build (`node node_modules/vite/bin/vite.js build --config frontend/vite.config.ts`) and open http://localhost:8001
3. Tests: `backend/.venv/Scripts/python.exe -m pytest backend/tests -q` (about 2 min; the Workflow A render tests write sample frames to `backend/tests/.artifacts/`, which is gitignored)
4. Workflow A in the UI: Home → "वीडियो एडिट करो" → upload → (Groq key in Settings for the transcript, an LLM key for "AI से प्लान बनाओ"; without keys, add plan rows by hand) → "मंज़ूर करो और वीडियो बनाओ".

### Phase 2 decisions (my call, within the approved plan)
- Workflow A output keeps the source aspect and fps, but **fps is capped at 30 and the shortest side at 720 px**. This keeps a 3-minute edit near the PRD's 5-minute budget on this 2-core CPU. 1080p is a later option.
- Music is **upload-only**: no bundled tracks, because of licensing (PRD risk 10).
- The caption font on Windows dev is "Nirmala UI" (system font, copied into the render folder per job, never committed). In Docker it is Noto Sans Devanagari from `fonts-noto-core`. Dropping `NotoSansDevanagari-*.ttf` into `backend/app/assets/fonts/` makes it the first choice everywhere; this was not done, to avoid downloading files without approval.
