# IMPLEMENTATION_PLAN.md — AI YT Studio v2 (PRD v1.0)

*Written 2026-10-10 on branch `uat/ai-yt-studio-v2`. **Approved by the owner on 2026-10-10 with the changes in §0a.***

## 0a. Owner's approval changes (2026-10-10) — these override anything below

1. **Delete nothing.** No file of the existing app is deleted or moved — not now, not in Phase 4. The legacy app (`src/`, root Vite config, `backend/main.py`, MoviePy, legacy tests) stays exactly as on `main` and keeps working. All new code is *added* next to it.
2. **The UAT branch starts as a full copy of `main`.** Verified: `git diff main uat/ai-yt-studio-v2` is empty; both at `e7a04a3`.
3. **Keys are entered by the owner on the Settings page, browser-only, like the existing system.** Settings, key storage and the "Test key" flow are built end-to-end now. Every test that needs a real provider key is **skipped and recorded as "not tested — needs key"**; the owner will add keys at the end and ask for a re-run.
4. **Online UAT (nice-to-have, later).** Focus stays local. At the end of a phase the owner may ask for an online UAT URL (options: a Railway service built from the `uat/*` branch, or a temporary tunnel to the local server). Nothing is deployed without asking.
5. **Open questions answered:** ports `5174`/`8001` — yes; no new npm libraries (plain React, hand-written routing/state, manual PWA) — my call, yes; UI language — my call: Hindi (Devanagari) with English technical terms, per PRD; captions follow the spoken language (Devanagari for Hindi); retention 30 days — yes.
6. **No `npm install` needed for the new frontend.** `frontend/` reuses the root `node_modules` (same React 18 / Vite 5 / TS versions) through normal Node resolution, so the owner does not have to run anything for Phase 1.
*Inputs: `docs/PRD_v1.md`, `CODEBASE_DISCOVERY.md` (repo audit), Phase 0 experiments below. All hour figures are my estimates and are UNVERIFIED.*

## 0. Owner decisions already given (binding)

| Decision | Consequence |
|---|---|
| All new work on branch **`uat/ai-yt-studio-v2`** (UAT). `main` and existing code stay untouched. | Never commit/push to `main`. |
| **Rollback safety**: annotated tag `baseline-pre-uat-2026-10-10` = exact `main` state (`e7a04a3`, 3 commits ahead of `origin/main` = `c8f95c5`). Local `pre-push` hook blocks any push to `main`/`master` (tested: blocked → exit 1; `uat/*` → exit 0). | See §7 rollback commands. The hook is local (`.git/hooks`), not versioned. |
| **No Railway for now.** New work is tested locally the same way the current app runs (Vite dev server + local uvicorn). | PRD Phase 0 items 1 & 4 (Railway container/limits) and all Railway-specific acceptance checks are **deferred, not done**. Dockerfile may be written and tested on local Docker only. |
| Process: Phase 0 + this plan → one approval → phases run without per-step questions; I report after each phase (passed / failed / not tested). | |
| `npm install` is run **by the owner** when I ask (Claude Code's classifier blocks it for me). Python deps via `uv` work for me. | Keep new npm dependencies minimal and batch them into one request per phase. |
| Existing 7-stage app: owner answered "do all new changes on the UAT branch; don't change existing for now". | Old app is kept **working side-by-side** until the new one reaches parity; deleted only in a final cleanup commit the owner approves. |

## 1. Phase 0 results (run locally 2026-10-10; scratch files outside repo)

| # | PRD check | Result | Evidence / caveat |
|---|---|---|---|
| 1 | Devanagari captions via ffmpeg/libass | ✅ **Pass locally.** `क्षत्रिय श्रीमान द्वारा कर्मचारियों`, `ज्ञ`, `ष्ट्र`, `त्व`, `पूर्ण` render correctly; per-line colour override and `\k` karaoke tags render. | Bundled ffmpeg 7.1 (`imageio-ffmpeg`) has libass+HarfBuzz+FriBidi. Frame inspected visually. Font was **Nirmala UI** (Windows). **Not tested:** Noto Sans Devanagari (not yet bundled), Railway container. |
| 2 | ffmpeg-native vs MoviePy, one scene | ✅ **~14× faster.** 5.5 s scene with zoompan + ASS captions + audio: **3.0 s** (direct zoompan), 3.8 s (scale→zoompan, smoother), 1.7 s static. MoviePy path measured earlier ≈ 42 s/scene. | i3-5005U 2-core, `-preset veryfast -crf 23`, 1280×720. Image was 1015×580. Railway CPU unknown. |
| 3 | Avatar frame speed | ✅ **Faster than real time.** Pillow/numpy composite piped to ffmpeg: full-frame 32.8 fps; **region-composite 44.5 fps** (10 s video in 5.4 s). | **Synthetic** character (drawn ellipses). Look/quality of real character art is **not judged**. |
| 4 | Edge-TTS Hindi word timings (PRD §5.3-4) | ✅ `hi-IN-SwaraNeural` and `hi-IN-MadhurNeural` return **18/18 `WordBoundary` events**, offsets monotonic. (`SentenceBoundary` only gives sentences.) | Must use `boundary="WordBoundary"`. Unofficial endpoint, can break (PRD risk #4). |
| 5 | Groq Whisper Hindi word timestamps | ❌ **Not run — no Groq key stored.** | Docs (earlier this session): `whisper-large-v3(-turbo)`, word timestamps supported, free 20 RPM / 7.2K audio-s per hour / 28.8K per day, 25 MB file cap; Hindi not explicitly listed. Needs owner's Groq key. |
| 6 | Railway CPU/RAM/upload limits | ⏸ **Deferred by owner.** | |

Net: the two biggest technical doubts (Devanagari shaping, render speed) look good locally; the biggest remaining unknown is **avatar art quality** and Groq-Hindi accuracy.

## 2. Gap analysis (PRD vs repo)

| PRD requirement | Repo today | Gap |
|---|---|---|
| Workflow A: upload → STT → prompt → plan → approve → render | none (no upload, STT, plan, compiler) | build entirely |
| Workflow B: wizard → facts → script → TTS → visuals → avatar → compose | old 7-stage slideshow pipeline (topic→script→scenes→images→voice→MoviePy) | different product; reuse ideas only |
| ffmpeg-only renderer, no MoviePy | MoviePy 2.2.1, per-frame Python | replace (Phase 0 shows ~14×) |
| Password gate, signed cookie, rate-limit | none | build |
| SQLite + data dir, jobs with progress/cancel (subprocess kill) | none (sync HTTP render) | build |
| Provider registry, tiers, fallback, key test, docs links | browser-only adapters (`src/providers/*`) calling vendors via dev-only proxy | move calls **server-side**; keep keys browser-only, sent per request in `X-Provider-Keys` |
| Keys never on server disk/logs/DB + sentinel test | keys in localStorage (matches) | add header transport, redaction, sentinel test |
| Hindi UI, mobile-first PWA | English desktop UI | rebuild UI; PWA by hand-written manifest + service worker (no new npm dep) |
| Devanagari word-synced ASS captions | on-screen text only, Arial-style fonts, Windows paths | build ASS writer + bundled Noto Sans Devanagari |
| Time-map compiler, `cut/remove_silence/captions/text_overlay/zoom/speed/music/broll/audio_cleanup` | none | build |
| Avatar renderer + 2-3 characters | none | build; art risk |
| Stock (Pexels/Pixabay) + cache + attribution; Pollinations; Wikimedia | Pollinations URL only | build |
| YouTube pack, thumbnail (Pillow + Devanagari), AI-disclosure gate | none | build |
| Tests (sentinel, cancel, contract, acceptance) | 16 Vitest tests, never run | new Python tests (pytest via uv) + manual acceptance |

## 3. Per-file decision (keep / change / delete)

| Path | Decision | Reason |
|---|---|---|
| `src/**`, `package.json`, `vite.config.ts`, `index.html`, `tsconfig.json` (legacy frontend) | **Keep untouched (never deleted, §0a)** | Old app stays runnable; new UI goes in `frontend/` |
| `src/providers/*.ts` | **Reference only** | Request/response shapes for Groq/Gemini/OpenRouter/Edge-TTS are ported into Python adapters |
| `src/components/Settings.tsx` (draft + Save + confirmation) | **Reference** | Pattern reused in new Settings page |
| `src/stages.test.ts`, `src/providers/index.test.ts` | Keep untouched | Legacy tests; kept per §0a |
| `backend/main.py` | **Keep untouched**; the new app lives in `backend/app/` | Legacy `/render/*` keeps the legacy UI working |
| `backend/requirements.txt` | **Change additively** (add new deps; MoviePy stays because the legacy backend uses it) | |
| `backend/.venv` | Keep (gitignored). Recreate with `uv` if needed | |
| `README.md` | Change at end of Phase 4 | describe v2 + local run + rollback |
| `.claude/launch.json` | Change | add backend + new frontend servers |
| `AGENT_HANDOFF.md`, `CODEBASE_DISCOVERY.md` | Keep in place (not moved, §0a); committed on the UAT branch | |
| `.gitignore` | Change | add `data/`, `.env`, test outputs |
| **New:** `frontend/` (Vite+React+TS, Hindi UI, PWA), `backend/app/…` (§7.3 of PRD), `backend/tests/`, `Dockerfile` (local-Docker-tested only), `.env.example`, `docs/STATUS.md`, `docs/BENCHMARKS.md`, `docs/PRD_v1.md` | Create | |

Resulting layout on the UAT branch: legacy app + new app coexist; new app listens on its own ports (frontend `5174`, backend `8001`) so both can run at once.

## 4. Phase plan (adapted)

Estimates are for Claude Code working time on this machine, UNVERIFIED; they exclude waiting on the owner (keys, `npm install`, art approval).

| Phase | Scope | Est. | Acceptance (run, then report) |
|---|---|---|---|
| **0** | Done (above) | ~2 h | table in §1 |
| **1 Foundation** | `backend/app` skeleton: config/env, password gate (signed HttpOnly cookie, login rate-limit), SQLite (stdlib `sqlite3` + pydantic), data dir, job runner (thread pool=1, ffmpeg subprocess, progress via `-progress`, cancel = kill process tree, SSE), provider registry + adapters for llm (Groq/Gemini/OpenRouter), tts (Edge-TTS, word boundaries), stt (Groq Whisper + faster-whisper optional), stock (Pexels/Pixabay), image (Pollinations); fallback logic (free→free only); key handling (`X-Provider-Keys`, in-memory per job, log redaction); `frontend/` shell: Hindi UI, Login, Home, Settings (keys in localStorage, test button, docs links, tier badges, clear keys), manual PWA manifest+service worker; Dockerfile (local Docker build test only) | 8–12 h | unauth `/api` rejected; login rate limit; **sentinel-key test** (grep DB, data dir, logs); cancel kills ffmpeg ≤ few s; PWA installable & 380 px layout (manual, Chrome devtools on laptop; phone test needs same-network access — owner); adapter contract tests with mocks |
| **2 Workflow A** | Upload (stream, `ffprobe` validate, ≤3 min/300 MB), CFR normalise, STT job, LLM→plan (pydantic validation/clamp/merge/warnings/clarifying question), plan editor UI, compiler with original→output **time map**, ops: cut, remove_silence (`silencedetect`), captions (Devanagari ASS, word highlight, remapped through time map), text_overlay, zoom, speed (`atempo`), music (upload + `sidechaincompress`), broll (stock/upload), audio_cleanup; render + duration verification (±0.1 s); result screen; re-render without re-upload | 14–20 h | 60 s sample with cut+overlay+zoom+captions: plan matches prompt, duration = time-map expectation, cuts ±0.2 s; Devanagari conjuncts visually checked; invalid-LLM-output repair/fallback test (simulated); timestamp past end → warning; silence removal A/V sync check |
| **3 Workflow B** | Wizard (8 screens), research (Wikipedia REST hi/en + notes → facts with source URLs, `uncertain` flags, editable), outline, per-chapter script JSON (pydantic, 1 repair retry → next LLM), TTS per scene with real durations + word timings, visuals (stock/Pollinations with 24 h cache, attribution; Pollinations images are generated on first fetch → backend fetches with timeout and stores under data dir), avatar renderer (audio-RMS → 4 mouth levels, blinks, breathing, region-composite → ffmpeg pipe), 2–3 characters + 2–3 backgrounds, 4 layouts, composition + concat, per-scene regenerate, YouTube pack (3 titles, description with chapters, tags, Pillow thumbnail 1280×720 with Noto Devanagari, attribution), AI-disclosure gate | 24–36 h | 1-min and 3-min free-only runs in 16:9 and 9:16; mouth follows speech; fallback notice on disabled first LLM; cache hit on 2nd run; scene durations = audio durations; disclosure required |
| **4 Hardening** | Hindi error messages, retention cleanup of *new* project media only, fallback tests, performance tuning, README + `docs/BENCHMARKS.md`, full acceptance run (key-dependent tests run after the owner adds keys). **No legacy code is deleted** (§0a). | 5–8 h | PRD §14 list |

Total ≈ **53–78 h** (PRD said 26–35 h; I raise it because Phase 2/3 each contain several independent subsystems and each needs real verification). Phases are independently shippable; Phase 2 alone delivers Workflow A.

## 5. Needed from the owner (blocking items, with when)

| Item | Needed by | Why |
|---|---|---|
| **Groq API key** (valid) | Phase 1 STT/LLM tests, Phase 2 | PRD item 5 untested; Hindi STT accuracy unknown |
| **Valid Gemini key** (stored one was a fake 17-char string) | Phase 1 | LLM fallback chain test |
| **Pexels + Pixabay API keys** | Phase 2 (b-roll), Phase 3 | stock search |
| `npm install` in `frontend/` | Phase 1 (one command, I'll give it) | React/Vite/TS only; no PWA plugin |
| OK to write `.env` locally with a dev `APP_PASSWORD`/`SESSION_SECRET` (gitignored) | Phase 1 | gate testing |
| Approval of **character look** (I will generate neutral character art with Pollinations + draw mouth sprites programmatically, per PRD §11.4) | before Phase 3 avatar work | biggest quality risk (PRD #3) |
| Permission for me to `git push` the `uat/*` branch only (never `main`) | optional | currently blocked by your earlier no-push rule and by the classifier |
| OK to move `AGENT_HANDOFF.md` / `CODEBASE_DISCOVERY.md` into `docs/` and commit | optional | currently untracked |

Keys are only ever typed into the browser UI (localStorage) per PRD §6.5; they never enter the repo or `.env`.

## 6. PRD assumptions vs reality (PRD §15)

| # | PRD assumption | Status now |
|---|---|---|
| 1 | Railway CPU/RAM sufficient | **Untested** (deferred). Local i3 numbers in §1 are encouraging but are a different machine |
| 2 | Devanagari shaping in libass | **Confirmed locally** with Nirmala; Noto + container untested |
| 3 | Programmatic mouth sprites look acceptable | **Speed OK; look unjudged** |
| 4 | Edge-TTS keeps working | Working today incl. Hindi word boundaries; remains an unofficial endpoint |
| 5 | Free-tier limits | Groq limits seen in docs this session; Gemini/OpenRouter **not verified** |
| 6 | Pollinations free access | URL-based, no key; images generate lazily on first fetch (observed) — terms unverified |
| 7–12 | XSS/key-loss, restart-loses-keys, premium prices, music licensing, accuracy, YouTube policy | Accepted as written; no new evidence |
| — | PRD "existing repo facts" | **Verified true**: React+Vite, FastAPI, MoviePy ≈ 40 s/scene (measured 42), no DB/queue, keys in localStorage, dev-only proxy. PRD says `frontend/` layout; repo has `src/` at root → handled by side-by-side `frontend/` |
| — | "Stop if an assumption is false" | **No assumption is contradicted.** Two environment facts change process: classifier blocks `npm install`/`git push`; Railway deferred |

## 7. Rollback (what to do if something wrong reaches `main`)

State is anchored by tag **`baseline-pre-uat-2026-10-10`** (= `main` at `e7a04a3`).

```bash
# See what changed on main since the baseline
git log --oneline baseline-pre-uat-2026-10-10..main

# Restore local main exactly to the baseline (destructive to local main only)
git switch main && git reset --hard baseline-pre-uat-2026-10-10

# If a bad commit already reached origin/main (remote): prefer a revert commit (non-destructive)
git revert --no-edit baseline-pre-uat-2026-10-10..origin/main
```
Note: `origin/main` is currently `c8f95c5`, 3 commits behind the baseline; the baseline contains those 3 extra local commits. The pre-push guard blocks pushing to `main`; remove it only deliberately (`.git/hooks/pre-push`).

## 8. Open questions

1. Frontend dev port `5174` and backend `8001` for the new app (to run beside the legacy app) — acceptable?
2. Should the new frontend be plain React + hand-written router/state (no new deps) — yes by default; say so if you prefer a library.
3. UI copy: Hindi (Devanagari) throughout; error messages Hindi with technical code — confirm Hinglish-Roman is **not** wanted anywhere in the UI (earlier discussion asked for Roman captions; PRD supersedes with Devanagari).
4. Retention default 30 days — keep?

## 9. Not tested / out of scope in this plan

Railway deployment, container CPU/RAM limits, upload limits behind Railway, Noto Sans Devanagari rendering, Groq Hindi STT, real avatar art, phone installation of the PWA, any premium provider.
