# CODEBASE_DISCOVERY.md — AI YT Studio

*Read-only audit, 2026-10-10. Repo HEAD `e7a04a3` (3 commits ahead of `origin/main` = `c8f95c5`). Audited by reading the actual source and tracing call chains. Nothing was modified, installed, run, or pushed during the audit; this file is the only thing written.*

**Reading guide — status legend (used everywhere):**
✅ VERIFIED (code exists AND was observed executing successfully) · 🟢 IMPLEMENTED, NOT VERIFIED · 🟡 PARTIAL · 🟠 SCAFFOLD/STUB · 🔴 BROKEN · ⚪ PLANNED/REFERENCED ONLY · ❌ MISSING · UNKNOWN = needs verification

**Important caveat about "verified":** the repository contains **no recorded evidence of any execution** (no logs, screenshots, fixtures, sample outputs, CI). Every ✅ below rests on executions that were *observed live in the working sessions of 2026-09-20 → 2026-09-22* (details in §18). That evidence is not reproducible from the repo alone. Treat ✅ as "was seen working once, on one machine".

---

## 1. Project identity

| Item | Finding |
|---|---|
| Name | **AI YT Studio** (`package.json` name `ai-yt-studio`, v0.1.0, `private: true`; UI title "AI YT Studio — agentic video pipeline") |
| Root | `D:\Youtube_content_creation` |
| Git remote | `https://github.com/ChaudharyNishant003/Youtube_content_creation.git` (`main`). History starts 2026-09-20 with a "handover snapshot"; code predates it (files dated 2026-09-13). Original author per project owner: "Sahil"; current owner took over. |
| Not a git repo before | History is only 6 commits, all 2026-09-20…22 |
| Product type | Single-user, local, browser-based tool + local Python render service |
| Stage | **Early prototype / MVP-in-progress.** Not hosted, no auth, no DB, no CI, tests never executed. |
| Current focus | **AI video *generation* from a topic** (topic → script → scenes → images → narration → MP4). **No video *editing* of user-supplied footage exists.** |
| Target user (per code/README) | A solo YouTube/short-form creator running it on their own machine with their own API keys |

## 2. Executive summary

The repository is a **React + Vite + TypeScript single-page app** (≈2.9k lines under `src/`) that runs a 7-stage "agentic" pipeline — Research & Hook → Scriptwriter → Visual Director → Image Generation → Video Generation → Voiceover → Storyboard/Assemble — where each stage has a **swappable provider menu** (24 provider adapters across LLM/image/video/TTS, ordered free→paid). All provider calls are `fetch()` calls from the browser through a **dev-only Vite CORS proxy**. A **single-file FastAPI backend** (`backend/main.py`, 377 lines) adds the one thing browsers can't do: stitching scene images (+ optional video clips) + per-scene Edge-TTS narration + burned-in text captions into a real `.mp4` via MoviePy.

What demonstrably works end-to-end (observed): topic → hooks/outline → script → 10-scene JSON → 10 Pollinations images → `.mp4` (valid 1280×720, 55.75 s, H.264/AAC) with Ken-Burns zoom and fixed captions, **using a paid OpenAI key for the text stages**. What has never been proven: the free-LLM path (the saved Gemini key was invalid), any video-generation provider, the real-video-clip stitching branch, any TTS other than Web Speech and (inside the render) Edge-TTS, and the entire test suite.

**One finding that contradicts earlier project notes:** the **Voiceover stage cannot run Edge-TTS at all** — `engine.ts:45-47` throws unconditionally for any provider with `needsBackend: true`, without ever checking whether the backend is up (🔴, see §21). Edge-TTS only works *inside* `/render/video`, which re-synthesizes narration itself.

## 3. Actual product purpose

Evidence-based: "Given a topic and audience parameters, use LLMs and image/TTS providers to produce a narrated, captioned, Ken-Burns-animated slideshow video and export it as MP4." Video clips from AI video providers are an *optional, manual, per-scene* upgrade. Posting/publishing, uploading user footage, editing existing video, subtitles-from-speech, music — none exist.

## 4. Complete architecture

```
BROWSER (React SPA, Vite dev server :5173)                     LOCAL PYTHON (FastAPI :8000)
┌──────────────────────────────────────────┐                  ┌───────────────────────────────┐
│ App.tsx                                  │                  │ backend/main.py               │
│  ├ Sidebar (stage nav, Run full pipeline)│                  │  GET  /render/health          │
│  ├ InputsBar (topic/aspect/duration/aud.)│                  │  GET  /render/voices (unused) │
│  └ StagePanel(stageId) | Settings        │                  │  POST /render/tts   (UNREACHABLE
│      └ RenderExport / AssemblePlayer     │                  │       from UI, see §21)       │
│ store.ts  (global store + localStorage)  │                  │  POST /render/video           │
│ engine.ts (runStage / runAll / cancel)   │                  │    ├ Edge-TTS per scene (mp3) │
│ providers/{llm,image,video,tts}.ts       │                  │    └ MoviePy build+encode     │
│        │ fetch('/api/<name>/…')          │                  └──────────────▲────────────────┘
└────────┼─────────────────────────────────┘                                 │ '/render/*'
         ▼  Vite dev-server proxy (vite.config.ts) — DEV ONLY ───────────────┘ (proxy → 127.0.0.1:8000)
   Gemini · Groq · OpenRouter · OpenAI · DeepSeek · Together · Anthropic · HuggingFace
   ElevenLabs · Stability · Google TTS (gtts) · fal · Replicate · Luma · Runway · MiniMax
   (Pollinations images are loaded by direct URL, not through the proxy — see §15)
```

Key architectural facts (all verified in code):
- **No database, no server-side project state, no queue.** All state is browser memory + one `localStorage` key.
- **Provider-adapter pattern**: every provider is an object implementing `Provider` (`types.ts:55-75`) with one of `runLlm/runImage/runVideo/runTts`. Registry in `providers/index.ts`.
- **Two independent narration paths** exist: (a) the Voiceover *stage* (`engine.ts` → `provider.runTts` → `audioUrl`, used only by the storyboard preview player), and (b) the *render* path, where the backend synthesizes Edge-TTS per scene itself. **The provider selected in the Voiceover stage does not affect the exported MP4's audio** — the MP4 always uses Edge-TTS with the voice typed in the RenderExport panel.
- **Rendering is a synchronous HTTP request** that can last minutes; there is no job id, progress, or cancellation.

## 5. Complete codebase tree (excluding `node_modules`, `dist`, `backend/.venv`, `.git`)

```
D:\Youtube_content_creation
├── README.md                    product pitch + run instructions (updated to match code on 2026-09-22)
├── AGENT_HANDOFF.md             UNTRACKED, written 2026-10-09 by a prior agent session; status + owner rules (contains one stale count, see §21)
├── CODEBASE_DISCOVERY.md        THIS FILE
├── package.json                 scripts: dev, build, preview, test; deps react/react-dom; devDeps incl. vitest (NOT installed)
├── package-lock.json            2026-09-13 — does NOT contain vitest (0 matches) → out of sync with package.json
├── tsconfig.json                strict:false, noUnused*:false, noEmit
├── vite.config.ts               dev proxies for 17 upstreams + /render → :8000   (dev only)
├── index.html                   mounts #root, loads /src/main.tsx
├── .gitignore                   node_modules, dist, backend/.venv, __pycache__, *.pyc, .env, .env.local
├── .claude/launch.json          dev-server launch config (frontend only)
├── dist/                        STALE build from 2026-09-20 22:20 (predates all 09-22 changes) — gitignored
├── src/
│   ├── main.tsx                 React root
│   ├── App.tsx                  layout; view === "settings" ? <Settings/> : <StagePanel stageId={view}/>
│   ├── types.ts                 domain types (Provider, StageDef, StageWiring, StageRuntimeState, Scene, RunContext…)
│   ├── stages.ts                STAGES[7], default LLM prompts, fillTemplate, dimsToPixels, parseScenes
│   ├── engine.ts                runStage / runAll / cancelStage
│   ├── store.ts                 useSyncExternalStore global store + localStorage persistence
│   ├── icons.tsx                inline SVG icons
│   ├── styles.css               643 lines, dark theme
│   ├── stages.test.ts           9 tests (UNRUN)
│   ├── providers/
│   │   ├── index.ts             allProviders, providersFor(kind) [tier-sorted], getProvider, TIER_LABEL
│   │   ├── index.test.ts        7 tests (UNRUN)
│   │   ├── llm.ts               7 adapters
│   │   ├── image.ts             5 adapters
│   │   ├── video.ts             7 adapters (+ poll(), requireRemoteImage())
│   │   └── tts.ts               5 adapters
│   └── components/
│       ├── Sidebar.tsx          stage rail, status dots, Run-all/Stop, Settings link
│       ├── InputsBar.tsx        topic, dimensions, duration (free text), audience, age group
│       ├── StagePanel.tsx       per-stage provider/param/prompt wiring + Run/Stop + outputs
│       ├── FieldEditor.tsx      generic controlled input (instant onChange)
│       ├── Settings.tsx         API-key vault; ProviderCard w/ draft state + Save + "Saved successfully"
│       ├── AssemblePlayer.tsx   client-side storyboard slideshow (timer + <audio>)
│       └── RenderExport.tsx     backend health badge, voice field, "Render .mp4", preview, download
└── backend/
    ├── main.py                  FastAPI app (all backend logic)
    ├── requirements.txt         fastapi, uvicorn[standard], edge-tts, moviepy, pillow, numpy, requests (all `>=`, unpinned)
    ├── __pycache__/             ignored
    └── .venv/                   ignored; rebuilt 2026-09-20 with uv on CPython 3.13.5 (original was copied from another user's PC and unusable)
```

Total tracked source ≈ 4,065 lines incl. docs/CSS/lockfile-free. There is **no** `tests/` directory beyond the two co-located `*.test.ts` files, no `scripts/`, no `docs/`, no `.github/`, no Dockerfile, no `.env.example`, no DB/migrations.

## 6. Technology stack (actual usage)

| Layer | Technology | Version | Evidence | Status |
|---|---|---|---|---|
| Frontend | React + react-dom | ^18.3.1 | `src/main.tsx`, all components | ✅ in use |
| Frontend build | Vite + @vitejs/plugin-react | ^5.4.11 (5.4.21 observed running) / ^4.3.4 | `vite.config.ts`, dev server ran | ✅ |
| Language | TypeScript | ^5.6.3 | `tsconfig.json` (strict **off**); never type-checked in CI | 🟢 (type-check never run as a gate) |
| State | Custom `useSyncExternalStore` store | — | `store.ts` | ✅ |
| Backend | FastAPI + uvicorn | 0.141.1 / 0.53.0 (as installed 2026-09-20; reqs say `>=`) | `backend/main.py`; ran and served requests | ✅ |
| Database | **None** | — | no ORM/driver/migrations anywhere | ❌ |
| AI / LLM | 7 REST adapters (Gemini, Groq, OpenRouter, DeepSeek, Together, OpenAI, Anthropic) | model names editable per stage | `providers/llm.ts` | ✅ OpenAI only; ⚠ rest 🟢 |
| Image generation | Pollinations (URL-only), HF FLUX, Together FLUX, Stability, OpenAI image | — | `providers/image.ts` | ✅ Pollinations; others 🟢 |
| Video generation | fal, Replicate, HF text→video, MiniMax, Luma, Runway, Veo | — | `providers/video.ts` | 🟢 all, none ever run |
| STT | **None** | — | grep `whisper|transcri|subtitle` = no hits | ❌ |
| TTS | Web Speech (browser), Edge-TTS (`edge-tts` 7.2.8, backend), ElevenLabs, Google Cloud TTS, OpenAI TTS | — | `providers/tts.ts`, `main.py` | Web Speech ✅ (playback only); Edge-TTS ✅ *inside render only*; Edge-TTS *stage* 🔴; others 🟢 |
| Video processing | **MoviePy 2.2.1** (per-frame Python), Pillow 11.3.0, NumPy 2.5.3, ffmpeg via `imageio-ffmpeg` (bundled v7.1 binary, transitive) | — | `main.py` imports; **no direct ffmpeg/subprocess calls** | ✅ |
| Rendering | MoviePy `write_videofile` libx264/aac, 24 fps fixed by frontend | — | `build_movie()` | ✅ (slow) |
| Storage | Browser `localStorage` key `ai-yt-studio:v1`; backend OS temp dirs (`aiyt_*`, never cleaned) | — | `store.ts`, `main.py` | 🟡 |
| Queue/workers | **None** (HTTP request thread + `asyncio.to_thread`; browser-side polling for video providers) | — | `main.py:render_video`, `video.ts:poll` | ❌ |
| Testing | Vitest ^2.1.8 (declared) | **not installed** (`node_modules/.bin` has no vitest; lockfile has no entry) | `package.json`, 2 test files | 🔴 cannot run as-is |
| Deployment | `npm run dev` + manual `uvicorn`. No Docker/CI/hosting config | — | repo contents | ❌ |
| Python tooling | `uv` 0.12.17 used to rebuild the venv (not referenced by repo files) | — | session | n/a |

## 7. Feature inventory

*(Code location → Tested? → Evidence. "Observed" = seen executing in 2026-09 sessions, see §18.)*

### AI / content
| Feature | Status | Location | End-to-end flow | Tested? | Evidence |
|---|---|---|---|---|---|
| Topic input + audience params | ✅ | `InputsBar.tsx`, `store.setInputs` | UI→store→`fillTemplate`/`inputsSummary` | observed | duration is free text; only injected into prompts, never enforced |
| Research / hooks / outline | ✅ (OpenAI) | `stages.ts:research`, `engine.ts:50-70` | LLM→Markdown text | observed (OpenAI only) | 🟢 for the 6 other LLMs |
| Web research | ❌ | — | none; "research" is purely LLM prior knowledge | — | no search/browse code |
| Script generation | ✅ (OpenAI) | `stages.ts:script` | research text → LLM → text | observed | |
| Outline generation | ✅ (part of Research) | | | observed | |
| Scene planning | ✅ (OpenAI) | `stages.ts:visuals`, `parseScenes` | script → LLM → JSON → `Scene[]` | observed (10 scenes) | parser fragile (§21) |
| Image-prompt generation | ✅ | inside Visual Director output (`imagePrompt`) | | observed | |
| "AI agents" | ⚪ | marketing wording only | there is no agent loop/tool-use/planner; stages are fixed sequential LLM calls | — | |
| LLM provider choice | 🟢/✅ | `providers/llm.ts` | | OpenAI observed | Gemini key was invalid → free path unproven |

### Media
| Feature | Status | Location | Flow | Tested? | Evidence |
|---|---|---|---|---|---|
| Image generation (Pollinations) | ✅ | `image.ts` | builds `https://image.pollinations.ai/prompt/…?seed=<random>` — **no network call at run time**; image is generated lazily when the URL is first fetched (by `<img>` or by backend `requests.get`) | observed | seed is random per run → re-run changes images |
| Image generation (HF/Together/Stability/OpenAI) | 🟢 | `image.ts` | | no | never run |
| Image retrieval / stock | ❌ | — | | | |
| Uploaded video / images | ❌ | — | no `<input type=file>` anywhere | | grep |
| Video generation (7 providers) | 🟢 | `video.ts` | per scene, sequential, manual only | no | never run; no video key ever saved; none free |
| Voiceover — Web Speech | ✅ | `tts.ts` | browser `speechSynthesis`, `playbackOnly`, no file | observed | |
| Voiceover — Edge-TTS (stage) | 🔴 | `tts.ts:51`, `engine.ts:45` | unconditional throw (§21) | no | |
| Voiceover — ElevenLabs / OpenAI TTS / Google Cloud TTS | 🟢 | `tts.ts` | | no | Google TTS appears in UI dropdown (observed) but never called |
| Narration inside MP4 | ✅ | `main.py:synth_to_file` | Edge-TTS per scene | observed (ffprobe: AAC 44.1 kHz stereo, duration matches) | I did not listen to it |
| STT / transcription | ❌ | — | | | |
| Subtitles from speech | ❌ | — | | | |
| "Captions" | 🟡 | `main.py:_caption_overlay` | **burned-in `onScreenText` short phrases from the LLM**, one per scene, fixed position — NOT speech-synced subtitles | observed | |
| Music / SFX | ❌ | — | | | |

### Editing
| Feature | Status | Location | Notes |
|---|---|---|---|
| Timeline | ❌ | — | storyboard list/slideshow only |
| Scene editing UI | ❌ | — | scenes are read-only output; only the raw JSON can be viewed |
| Clip stitching | ✅ (stills) / 🟢 (clips) | `main.py:build_movie` | `concatenate_videoclips(method="chain")`; clip branch never executed |
| Trim/cut | 🟡 | `_fit_video_duration` | only loop/trim a generated clip to narration length; no user trimming |
| Transitions | ❌ | — | hard cuts |
| Zoom / Ken Burns | ✅ | `main.py:_ken_burns_clip` | 1.0↔1.12 zoom, alternates per scene; BILINEAR; observed |
| B-roll | ❌ | — | |
| Overlays | 🟡 | `_caption_overlay` | caption only |
| Audio mixing | ❌ | — | single narration track per scene |
| Effects | ❌ | — | |
| Prompt-based editing / automatic editing / vlog editing | ❌ | — | no editing-instruction pipeline of any kind |

### Output
| Feature | Status | Notes |
|---|---|---|
| Preview | 🟡 | `AssemblePlayer`: equal-time slideshow (`totalMs / scenes.length`, ignores each scene's `time` field), plays stage voiceover audio if present |
| MP4 render | ✅ | observed: 2-scene ≈63 s–148 s; 10-scene 6 m 56 s on this machine |
| Download | ✅ | `<a download="ai-yt-studio.mp4">` blob link |
| Project saving | 🟡 | only text/scenes + settings in localStorage; no export/import of a project |
| Media persistence | ❌ | images/videos/audio URLs deliberately not persisted (`store.ts:73,107,122`) |
| Project history | ❌ | |

### YouTube
Title/description/tags/chapters/thumbnail/Shorts packaging/YouTube API/publishing — **all ❌ MISSING** (grep for `youtube` API/OAuth = no hits). "YouTube" appears only in prompts/UI copy.

## 8. Actual AI pipeline (traced from `engine.ts`)

`runAll()` (`engine.ts:117-126`) = fixed order **research → script → visuals → images → voiceover**, stops at first failure, no retry. `video` and `assemble` are never included (by design: credit-based).

| Stage | Input | Output (stored in `runtime[stage]`) | Provider/model (default → options) | Code | Fallback / errors | Tested |
|---|---|---|---|---|---|---|
| research | `inputsSummary(inputs)` as user msg; system = filled template | `text` (Markdown) | default Gemini (first free LLM); 7 options | `engine.ts:50-70` | `try/catch` → `status:"error"`, message shown; AbortError→idle; **no retry** | OpenAI observed |
| script | `runtime.research.text` (falls back to inputs summary) | `text` | same menu | same | same | observed |
| visuals | `runtime.script.text` (**throws if missing**) | `text` + `scenes[]` via `parseScenes` | same menu | same | `parseScenes` throws on bad JSON | observed (10 scenes) |
| images | `scenes[].imagePrompt`, sequentially | `images{scene→url}` | default Pollinations (flux/turbo) | `engine.ts:71-82` | per-scene errors abort the stage; **no per-scene retry/resume** (re-run regenerates all) | Pollinations observed |
| video (manual) | `imagePrompt` + `images[scene]` as still | `videos{scene→url}` | default fal; 7 options | `engine.ts:83-95` | image→video modes call `requireRemoteImage` (rejects `blob:`/`data:`) | **never run** |
| voiceover | whole `script.text` | `audioUrl` (blob) or playback-only | default Web Speech; 5 options | `engine.ts:96-100` | 🔴 Edge-TTS option always throws | Web Speech observed |
| assemble | scenes+images+videos(+audio) | storyboard preview; MP4 on demand | — | `AssemblePlayer`, `RenderExport` | backend errors surface as `error-box` | MP4 observed |

Default wiring for each stage = first provider after tier-sorting (`store.buildDefaults`). Prompt templates support `{{topic}} {{duration}} {{audienceType}} {{ageGroup}} {{dimensions}}` (plain `replaceAll`).

## 9. Video-generation pipeline (Step 7)

| Provider | Adapter exists | API integrated (real HTTP) | Credentials | Tested | Working |
|---|---|---|---|---|---|
| fal.ai (`fal-ai/ltx-video` default; any model id) | ✅ | sync `POST /api/fal/<model>`; text or image mode | API key | no | UNKNOWN |
| Replicate (`lightricks/ltx-video` default) | ✅ | `Prefer: wait` then polling `/v1/predictions/<id>` | token | no | UNKNOWN |
| Hugging Face text→video (`ali-vilab/text-to-video-ms-1.7b`) | ✅ | returns raw bytes → `blob:` URL (`remote:false`) | HF token | no | UNKNOWN; blob URL cannot be fetched by the backend unless re-encoded by `resolveMedia` (it is) |
| MiniMax Hailuo (`T2V-01`/`I2V-01`) | ✅ | create task → poll → `files/retrieve` (needs Group ID) | key + groupId | no | UNKNOWN |
| Luma Dream Machine (`ray-flash-2`/`ray-2`) | ✅ | create → poll `state` | key | no | UNKNOWN |
| Runway (`gen4_turbo`/`gen3a_turbo`) | ✅ | image→video only, poll task | key | no | UNKNOWN |
| Google Veo (`veo-3.0-generate-preview`, `veo-2.0-generate-001`) | ✅ | `:predictLongRunning` + poll `operation`; appends key to download URI | Gemini key | no | UNKNOWN; model ids may be stale |

Shared: `poll()` 4 s interval / 240 s timeout (Veo 8 s / 300 s); abort via `AbortSignal`; errors = trimmed upstream body; **no retries, no webhooks, no output storage** (only provider URL or blob URL kept in memory). Provider abstraction layer: **yes** (same `Provider` interface). No clip is ever downloaded/persisted by the app itself; the backend downloads it at render time.

**Is the generated clip actually used in the export?** Code path exists (`main.py:build_movie` → `_fetch_video_to_file` → `_cover_resize_video` → `_fit_video_duration`; `RenderExport.tsx` sends `video`). 🟢 — **never executed**: every test render sent `video: null`.

## 10. Video-editing pipeline (Step 6)

Question: *Can it "upload raw vlog → understand → edit per prompt → export"?* **No — ❌ none of it exists.**

| Needed capability | Status |
|---|---|
| Upload / media ingestion | ❌ no file input, no upload endpoint |
| Video metadata extraction (ffprobe) | ❌ |
| Transcript extraction (STT) | ❌ |
| Scene detection | ❌ |
| Clip selection / trimming by user or AI | ❌ (only loop/trim of a *generated* clip to narration length) |
| Timeline generation / edit-decision list | ❌ (the `Scene[]` array is the only structure; it has no source-media/in/out fields) |
| AI editing instructions (prompt → edits) | ❌ |
| B-roll insertion | ❌ |
| Audio processing (cleanup, music, ducking) | ❌ |
| Speech-synced captions | ❌ |
| Rendering of arbitrary user media | 🟡 backend can open an mp4 **if** `scene.video` is a URL/data-URI and treat it as a scene visual; untested |

Reusable existing pieces (facts, not recommendations): the `Scene` model, `RenderExport` → `/render/video` contract (`SceneIn.video`, `.image`, `.narration`, `.onScreenText`), `_cover_resize_video`, `_fit_video_duration`, `_caption_overlay`.

## 11. Frontend architecture (Step 10)

Screens: (1) **Stage panel** (7 variants, one component `StagePanel`), (2) **Settings & API keys**. No router; `store.view` string selects the screen. No media library, no project list, no timeline, no onboarding.

Actual user flow: *open app → type topic/duration/audience → (Settings: save an API key per provider card) → per stage pick provider/model/edit prompt (LLM stages) → click **Run full pipeline** (research…voiceover) or run stages individually → inspect outputs → (optional, manual) run Video Generation → Storyboard/Assemble: Play storyboard preview → ensure backend online badge → set Edge-TTS voice → **Render .mp4** (minutes) → inline preview + Download.*

UX facts: status dots per stage; Stop button per stage / global; errors shown inline; loading = text. Settings Save button is disabled until the draft differs from stored value and shows a green "Saved successfully" pill for 2.5 s (✅ observed). The UI hint under the render button says "~30–90 s" — **stale/wrong** (observed 1–7 min). Generated media is lost on page reload; the storyboard then shows "no media yet" until stages are re-run.

## 12. Backend architecture (`backend/main.py`)

Single file, 377 lines: models (`TtsIn`, `SceneIn`, `VideoJob`), helpers (Edge-TTS synth, image cover-crop, caption overlay, `_ken_burns_clip`, `_fetch_video_to_file`, `_cover_resize_video`, `_fit_video_duration`), `build_movie()` (blocking; run via `asyncio.to_thread`), 4 routes. CORS allows only `http://localhost:5173` / `127.0.0.1:5173`. No auth, no rate limits, no size limits, no env/config file. Fonts are hard-coded Windows paths (`C:\Windows\Fonts\arialbd.ttf` etc.) with a name-only fallback — **Roman-script captions only; Devanagari would not render with these fonts** (UNKNOWN on non-Windows).

Render algorithm per scene: duration = `max(1.0, narration_audio.duration) + 0.35` (3.0 s if no narration). Visual = fitted real clip, else Ken-Burns of the cover-cropped image (dark placeholder if image fetch fails). Caption overlay composited fixed on top. Scenes concatenated, encoded `libx264` + `aac`, `fps` (24), `threads=4`, `temp_audiofile` pinned to workdir, **one retry** on `OSError`/`PermissionError` (fix for a Windows MoviePy `WinError 32` temp-file lock hit during testing). Output: `FileResponse` of `ai-yt-studio.mp4`. Resolutions: 16:9→1280×720, 9:16→720×1280, 1:1→1080×1080.

## 13. API inventory (Step 11)

| Endpoint | Purpose | Implemented | Connected to UI | Tested | Notes |
|---|---|---|---|---|---|
| `GET /render/health` | liveness | ✅ | `RenderExport` badge | observed | |
| `GET /render/voices` | list Edge-TTS voices | ✅ | **no** (voice is free text) | no | dead endpoint |
| `POST /render/tts` | one mp3 from text | ✅ | only via `tts.ts:edgetts` which `engine.ts` never lets run | no | 🔴 effectively unreachable |
| `POST /render/video` | build MP4 | ✅ | `RenderExport.exportMp4` | observed (2 & 10 scenes, via the real fetch payload and curl) | the actual UI *button* click path with the new `video` field was not clicked; payload replicated by script |
| Vite proxies `/api/<name>/*` | CORS bypass to 17 upstreams | ✅ | all provider adapters | OpenAI/Pollinations-adjacent only | `/api/pollinations` proxy defined but unused |

## 14. Database / storage (Step 9)

- **Database:** none. No schema, migrations, models, users, job tables.
- **Browser `localStorage["ai-yt-studio:v1"]`:** persists `inputs`, `secrets` (**API keys in plaintext**), `wiring` (provider/params/system prompts), and per-stage `{text, scenes}` only. On reload, stages with text/scenes are restored with `status:"done"`.
- **Browser memory only (lost on reload):** `images`, `videos`, `audioUrl`, run status/errors, rendered MP4 blob URL.
- **Server:** per-render temp dir `aiyt_*` under the OS temp folder holding narration mp3s, downloaded clips, `temp_audio.m4a`, and the final mp4. **Never deleted** (`grep rmtree` = none) → disk growth. `/render/tts` does delete its temp file.
- **Object storage:** none. Project/asset library: none.

## 15. Provider architecture (Step 8)

- Interface: `Provider { id, name, kind, tier, secrets[], params[], needsBackend?, runLlm?/runImage?/runVideo?/runTts? }` (`types.ts:55`). Adapters are plain objects in four arrays; `providers/index.ts` concatenates them, `providersFor(kind)` sorts free→freemium→paid (stable), `getProvider(id)` looks up. No factories/DI; **selection is a per-stage string in `wiring[stageId].providerId`**; secrets and params are merged by `stageConfig()` into `ctx.config`.
- **Fallback logic: none** (no automatic provider failover).
- UI fields (keys/model/voice) are generated from each adapter's `secrets`/`params` declarations — adding an adapter shows it in Settings and stage panels automatically.
- Counts (verified from files): LLM 7, image 5, video 7, TTS 5 = **24** adapters.
- Pollinations bypasses the proxy (direct `image.pollinations.ai` URL, returned as `remote:true`).
- `needsBackend` is a *static flag*, not a health check (root cause of the Edge-TTS bug).

## 16. Async / jobs (Step 12)

No worker/queue/Celery/Redis/webhooks. Lifecycles that exist:
- **LLM/image/TTS stages:** `await` in the browser; status `running→done|error|idle(abort)`; `AbortController` per stage (`cancelStage`).
- **Video providers:** create-job then browser-side `poll()` loop.
- **Render:** one long-lived POST; backend does sequential Edge-TTS awaits then a thread for MoviePy. No progress events, no cancel (RenderExport has no AbortController), no job id → closing the tab loses the result; concurrent renders compete for CPU (two parallel renders both failed during testing before the WinError fix).

## 17. Testing audit (Step 13)

| Item | Finding |
|---|---|
| Framework | Vitest ^2.1.8 declared in `package.json`; `"test": "vitest run"` |
| Installed? | **No.** `node_modules/.bin/vitest` absent; `package-lock.json` has 0 vitest entries (lockfile is older than `package.json`). `npm install` has been blocked every time by Claude Code's own auto-mode classifier in these sessions |
| Files | `src/stages.test.ts` (9 tests: parseScenes ×5 incl. one that asserts the current fragile behavior, fillTemplate ×2, dimsToPixels ×2); `src/providers/index.test.ts` (7 tests: ordering, kind filter, google-tts tier, lookups, unique ids, run-function-per-kind) = **16 tests** (earlier notes say 15 — miscount) |
| Executed? | **Never.** No results anywhere |
| Mocks / real providers | none used; pure-function tests (no network) |
| Integration / E2E / render tests | none |
| Backend tests | none (no pytest) |
| Lint / type-check gate / CI | none |
| Manual verification | see §18 |

Nothing is "test-verified". Unknown whether the 16 tests would pass.

## 18. Verification evidence (Step 14)

**In the repo:** none (no logs/screenshots/fixtures/outputs). `AGENT_HANDOFF.md` (untracked) and commit messages *claim* results; commit `b79711a` states a 55.75 s 10-scene render.

**Observed executions in the working sessions (2026-09-20→22, this audit's source of ✅):**
- Backend started under Python 3.13 venv; `/render/health` → `{"ok":true,…}`.
- Research, Script, Visual Director ran on **OpenAI gpt-4o-mini** → 10 scenes parsed; Image stage produced 10 Pollinations URLs; Web Speech voiceover ran (playback-only).
- `/render/video` returned HTTP 200 for 2 scenes (valid mp4, 1280×720, 9.49 s; later optimized run 63.6 s wall) and 10 scenes (3.66 MB, **ffprobe: 55.75 s, h264 1280×720 24 fps, AAC 44.1 kHz stereo**, 6 m 56 s wall). Earlier 10- and 2-scene attempts returned 500 `WinError 32` before the temp-audio fix.
- Settings Save flow tested in-browser (typing did not persist; Save persisted; success pill shown; test key removed afterwards).
- Google Cloud TTS option appeared in Settings and Voiceover dropdown.
- **Not observed:** any video provider, the clip-stitching branch, ElevenLabs/Google/OpenAI TTS, non-OpenAI LLMs, HF/Together/Stability/OpenAI images, listening to the narration, visually reviewing the Ken-Burns frames in the final mp4 (the file was delivered to the owner; its visual quality was never inspected by the auditor), the UI "Render .mp4" button itself, any test run.

## 19. Configuration (Step 15)

- No `.env`, no `.env.example`, no config files for the backend. Port 8000 and the Vite proxy target are hard-coded; default voice `en-US-AriaNeural` constant.
- API keys are entered in the UI and stored in `localStorage` per provider id: `apiKey` for all; MiniMax also `groupId`. Keys the app can use: Gemini, Groq, OpenRouter, DeepSeek, Together (text + image), OpenAI (text/image/TTS), Anthropic, Hugging Face (image + video), Stability, ElevenLabs, Google Cloud TTS (separate key from Gemini), fal, Replicate, MiniMax (+Group ID), Luma, Runway, Google Veo (Gemini key). *(No values were read or printed in this audit.)*
- Environment observation (not repo content): at last check the stored Gemini entry was a 17-character non-`AIza…` string (invalid), the OpenAI entry looked like a real key, and nothing was stored for Groq or any video provider.
- Feature flags: none. Dev vs prod configuration: none (the proxy exists only under `vite dev`/`vite preview` server options).

## 20. Dependency audit (Step 16)

- Runtime JS deps: only `react`, `react-dom`. Dev: vite, @vitejs/plugin-react, typescript, @types/react(-dom), **vitest (declared, uninstalled, absent from lockfile)**.
- **Lockfile drift:** `package.json` (2026-09-20) ahead of `package-lock.json` (2026-09-13); `npm ci` would fail/omit vitest.
- Backend: all `>=` unpinned ranges (installed: fastapi 0.141.1, uvicorn 0.53.0, edge-tts 7.2.8, moviepy 2.2.1, pillow 11.3.0, numpy 2.5.3, requests 2.34.2). MoviePy 2.x API is used (`with_duration`, `resized`, `subclipped`, `with_effects`) — a future major bump could break it; no upper bounds. ffmpeg is provided only transitively through `imageio-ffmpeg`; not declared.
- Apparently unused: none in JS. `/render/voices` and the `/api/pollinations` proxy are unused code.
- Referenced but absent: `vitest` (above). No Python test deps.
- Python 3.12 → 3.13 change: the owner's original venv was 3.12; code has only been run on **3.13.5**.

## 21. Known problems (Step 17)

| # | Problem | Severity | Location | Impact | Evidence |
|---|---|---|---|---|---|
| 1 | **Voiceover stage cannot run Edge-TTS** — unconditional throw for any `needsBackend` provider, backend health never checked | High | `engine.ts:45-47` | the project's only free *downloadable* voice cannot be used from the stage; picking it also makes "Run full pipeline" stop at voiceover; `/render/tts` unreachable | code trace |
| 2 | Voiceover-stage provider has **no effect on MP4 audio** (backend re-synthesizes Edge-TTS) | High (UX/product) | `main.py:render_video` vs `engine.ts` | paid/ElevenLabs voice choice silently ignored in export | code trace |
| 3 | Real video-clip stitching branch never executed | High | `main.py:build_movie` | headline feature unproven | all test payloads `video:null` |
| 4 | Render is slow & synchronous (~40 s/scene on i3-5005U), no progress/cancel/job id; UI says "30–90 s" | High | `main.py`, `RenderExport.tsx:117` | long blocking request; proxy/browser timeouts UNKNOWN | measured |
| 5 | Generated media not persisted across reload | High | `store.ts:73,107,122` | any refresh loses images/audio/videos | observed repeatedly |
| 6 | Production build cannot call any provider (dev-only proxy) | High | `vite.config.ts` | cannot deploy `dist/` as-is | code |
| 7 | Tests never executed; vitest not installed; lockfile out of sync | High | `package.json`, lockfile | zero automated assurance | §17 |
| 8 | `parseScenes` slices first `[` to last `]` | Medium | `stages.ts:122` | trailing text with `]` breaks scene parsing (a test encodes this) | code + test |
| 9 | Free LLM path unproven (invalid Gemini key stored); every verified LLM run used paid OpenAI | Medium | environment | "free end-to-end" claim unverified | session |
| 10 | Render temp dirs never deleted | Medium | `main.py:render_video` | disk growth | grep |
| 11 | Backend fetches arbitrary URLs from the request body (`requests.get(spec)`), no allow-list/size cap; no auth | Medium (local-only now) | `main.py:_fetch_image/_fetch_video_to_file` | SSRF/abuse if ever exposed | code |
| 12 | API keys plaintext in `localStorage` | Medium (single-user) | `store.ts` | unacceptable for hosted multi-user | code |
| 13 | Captions are LLM `onScreenText`, not speech subtitles; fonts are Windows-only paths, Roman script only | Medium | `main.py:_load_font` | no real subtitles; non-Windows fonts UNKNOWN | code |
| 14 | `AssemblePlayer` splits time equally per scene (ignores `scene.time` and real narration lengths) | Low | `AssemblePlayer.tsx:44-47` | preview ≠ export timing | code |
| 15 | Pollinations seed is random per run; no re-use of prior images | Low | `image.ts:47` | non-reproducible visuals | code |
| 16 | Dead code: `/render/voices`, `/api/pollinations` proxy | Low | | confusion | code |
| 17 | `tsconfig strict:false`; no type-check/lint gate | Low | | latent type bugs | config |
| 18 | Stale/incorrect docs: UI render-time hint; `AGENT_HANDOFF.md` says "22 providers" (actual 24) and "15 tests" (actual 16); AssemblePlayer notice text partly outdated | Low | | misleading | verified counts |
| 19 | `dist/` is a stale 2026-09-20 build | Low | | misleading if served | mtime |
| 20 | No retries/backoff on any provider call; `runAll` aborts on first failure with no resume | Medium | `engine.ts` | flaky providers hurt runs | code |
| 21 | Veo model ids / endpoints may be outdated | Low–Med | `video.ts:402-440` | UNKNOWN until run | UNKNOWN |

Marker scan (`TODO|FIXME|XXX|HACK|NotImplemented|stub|mock|skip`): **zero hits** in source — all problems above come from tracing, not from comments.

## 22. Missing functionality (Step 18, scoped to *current* purpose only)

- **Missing for the current MVP (topic → video):** a proven free LLM run; proving the clip-stitch branch; working Edge-TTS stage (or removing the option); persisting generated media or warning before reload; honest render-time messaging/progress; running the tests.
- **Missing for the current intended workflow:** deployability outside `vite dev`; a way to keep/re-open projects; per-scene regeneration/retry; speech-synced captions (if "captions" is meant literally).
- **Technical debt:** lockfile drift, unpinned backend deps, no CI/lint/type gate, MoviePy per-frame rendering, single-file backend, unused endpoints, temp-dir leak, plaintext secrets, Windows-specific fonts.
- **Nice-to-have (not required by current scope):** transitions, music, per-scene timing in preview.
- **Future product features (⚪, not current requirements):** user-footage upload/editing, STT/transcripts, multi-platform export presets, YouTube metadata/thumbnail/publishing, hosted multi-user service. These are *discussed* (README "next enhancement" wording; `AGENT_HANDOFF.md` §6 records an in-progress requirements conversation) but **have zero code**.

## 23. Current MVP definition (Step 19)

**One sentence:** *A single user on their own machine enters a topic and audience, and the app uses their chosen LLM/image/voice providers to generate a script, scene breakdown, scene images and narration, then a local backend renders them into a captioned, Ken-Burns-animated MP4 (optionally using AI-generated clips per scene).*

- **MVP input:** topic, aspect ratio, duration (text), audience type, age group, API keys, optional per-stage provider/prompt overrides.
- **MVP processing:** 5-stage LLM/image/TTS chain (+ optional manual video-gen stage) → backend per-scene Edge-TTS + MoviePy assembly.
- **MVP output:** downloadable `.mp4` (16:9 / 9:16 / 1:1), plus on-page text/scene/image outputs.
- **Success condition (as implemented):** an MP4 whose length ≈ total narration, each scene showing its image (zoom) and caption. *Currently achieved only with paid-OpenAI text stages; free-key success unproven.*

## 24. Completion estimate (Step 20)

Reasoned, not precise. Against the **current defined MVP above**: roughly **65–75%** of functionality exists as code; roughly **45–55%** is demonstrated/verified; versus a "shippable to others" bar, nearer **40–50%**.

| Area | Est. completion | Reasoning |
|---|---|---|
| Core AI pipeline | 80% | stages, wiring, data flow complete; only OpenAI path observed |
| Research | 85% | LLM-only; no web retrieval |
| Script | 90% | |
| Visual generation (scenes/images) | 80% | Pollinations proven; parser fragile; others unrun |
| Video generation (AI clips) | 35% | 7 adapters + wiring exist, 0 executions, none free, clip stitch unrun |
| Video editing (user footage) | 0% | nothing exists |
| Voice | 60% | Web Speech + render-embedded Edge-TTS work; Edge-TTS stage broken; 3 providers unrun |
| Captions | 40% | overlay text only; no STT/subtitles |
| Rendering | 70% | works and valid output; slow, sync, no cleanup, no progress |
| Storage/persistence | 20% | settings+text only |
| UI | 70% | functional 2-screen app; no project mgmt/timeline |
| Testing | 10% | written, never run, not installable |
| YouTube integration | 0% | |

## 25. Current state summary (Step 21)

**🟢 BUILT AND VERIFIED (observed once)**
- Topic → Research/Script/Visual-Director (OpenAI) → 10-scene JSON
- Pollinations image URLs; Web Speech playback
- MP4 export with Ken-Burns + fixed captions + Edge-TTS narration (valid H.264/AAC output, 2- and 10-scene)
- Settings Save/confirmation flow
- Backend environment (uv, py3.13) and health endpoint

**🟡 BUILT BUT NOT VERIFIED**
- Gemini, Groq, OpenRouter, DeepSeek, Together, Anthropic LLM adapters
- HF/Together/Stability/OpenAI image adapters
- All 7 video-generation adapters; the real-clip stitching branch
- ElevenLabs, Google Cloud TTS, OpenAI TTS
- The 16 Vitest tests; the UI "Render .mp4" button path with `video` payload

**🟠 PARTIAL / IN PROGRESS**
- Captions (overlay text, not subtitles); storyboard preview (equal-time); project persistence (text only); docs sync

**🔴 BROKEN**
- Voiceover stage with Edge-TTS (unconditional guard); vitest install/run; lockfile sync; production (non-dev) provider access

**⚪ PLANNED / REFERENCED ONLY**
- Vlog/user-footage editing, STT/transcripts, music, multi-format export, metadata/thumbnail, hosting — requirements discussions only (`AGENT_HANDOFF.md` §6), no code

**❌ MISSING**
- Upload, STT, subtitles, timeline/editor, transitions, B-roll, audio mixing, DB, job queue, auth, CI, YouTube API, media persistence, retries

## 26. AI handoff map (Step 22)

```
PROJECT ROOT  D:\Youtube_content_creation
│
├── src/                    FRONTEND (React/Vite/TS). Everything the user sees + all AI-provider calls.
│   ├── stages.ts           ← START HERE for the pipeline: 7 stage defs, prompts, parseScenes (fragile)
│   ├── engine.ts           ← orchestration: runStage/runAll (contains the Edge-TTS guard bug @45-47)
│   ├── store.ts            ← state + persistence rules (what survives reload)
│   ├── types.ts            ← the Provider interface and Scene/Runtime shapes
│   ├── providers/          ← AI LOGIC LIVES HERE: llm.ts image.ts video.ts tts.ts + index.ts registry
│   └── components/         ← StagePanel (main UI), Settings (keys), RenderExport (MP4 export), AssemblePlayer (preview)
├── backend/main.py         RENDERING + Edge-TTS. build_movie() is the video engine (MoviePy). 4 routes.
├── vite.config.ts          dev-only proxies — explains how browser reaches every provider
├── package.json / lock     deps (vitest declared, not installed)
├── *.test.ts (2 files)     the only tests (never run)
├── README.md               intent/run instructions (reasonably accurate)
├── AGENT_HANDOFF.md        prior agent's status + owner's standing rules (read §7 rules before acting)
└── (no DB, no queue, no infra, no CI, no .env)
```
- **Where config is:** UI → localStorage (`ai-yt-studio:v1`); backend has none.
- **Run:** `npm run dev` (5173) and `backend/.venv` python `-m uvicorn main:app --port 8000` from `backend/`.
- **What works:** §25 🟢. **What doesn't:** §25 🔴/🟡.
- **Where to start investigating:** `engine.ts` → `providers/index.ts` → `main.py:build_movie`.
- **Owner's standing rules (from the project owner, per memory/handoff):** explain-and-get-approval before any action; do not `git push` unless told; don't import conventions from the owner's other project (StandByMe); prove claims by running things. In this environment `npm install` and some git pushes are blocked by Claude Code's auto-mode classifier regardless of owner approval.

## 27. "If I joined this project today" (Step 23)

1. **First file:** `src/engine.ts` (126 lines — the whole orchestration, plus bug #1).
2. **Second:** `src/providers/index.ts` + one adapter (e.g. `image.ts` Pollinations) to see the adapter pattern.
3. **Third:** `backend/main.py` `build_movie()` + `render_video()` (the video engine).
- **Main architecture to understand:** browser-orchestrated pipeline of swappable provider adapters; backend only renders.
- **Main working flow:** topic → OpenAI text stages → Pollinations → `/render/video` → MP4.
- **Main unfinished flow:** anything involving user footage, real video clips, STT, persistence of media, deployment.
- **Biggest technical risk:** the MoviePy per-frame render engine (slow on target hardware, synchronous, Windows file-lock fragility) combined with a dev-only proxy architecture that cannot be deployed.
- **Biggest product gap:** the code is a *generator* of slideshow-style videos; it has no ingestion/editing capability, so any "edit my footage" requirement is a new subsystem, not an extension of a half-built one.
- **Most important unresolved question:** UNKNOWN — requires verification: does the real-clip path (`scene.video`) and the free-key (Gemini/Groq) path actually work end-to-end, and what is the target runtime environment (local-only vs hosted), since that decides whether the dev-proxy/localStorage/sync-render design can stand.

*(Per Step 24: no redesign, roadmap, or market recommendations are made here.)*
