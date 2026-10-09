# AI YT Studio — Agent Handoff / Status Document

*Generated 2026-10-09. Paste this whole file into a new agent/session to give it full context on this project with zero prior history.*

## 1. What this project is

A browser-based (React + Vite + TypeScript) pipeline that turns a topic into a finished YouTube-style video: Research & Hook → Scriptwriter → Visual Director → Image Generation → Video Generation (optional) → Voiceover → Storyboard/Assemble + export. A local FastAPI backend ("Phase 2") adds narration synthesis and real `.mp4` rendering that the browser alone can't do. Every stage has a swappable menu of API providers ordered free → paid (22 providers total across LLM/image/video/TTS).

Not a hosted product yet — runs on one developer's machine via `npm run dev` + a local Python backend. No git remote pushes are happening right now (paused by the project owner's explicit instruction; 3 local commits are ahead of `origin/main`).

## 2. The MVP this status is measured against

**"Does the core promise work, for one person, for free, right now?"** — i.e., type a topic, get a real finished downloadable video, using only free-tier providers, no code changes needed by the end user.

A **separate, newer MVP** (vlog-editing: customer uploads their own footage, system auto-edits it per parameters/prompt, hybrid insert of customer clips into AI-generated videos, multi-platform export) is **in requirements discussion only** — no code has been written for it yet. Do not assume any of section 2's new scope exists in the code. See section 6.

## 3. Status table — original MVP

| Area | Status | Evidence / notes |
|---|---|---|
| Research & Hook (LLM stage) | ✅ Done, verified live | Ran against real OpenAI key. |
| Scriptwriter (LLM stage) | ✅ Done, verified live | Ran against real OpenAI key. |
| Visual Director → scene JSON | ✅ Done, verified live | Produced 10 real scenes. **Known fragility**: `parseScenes()` in `src/stages.ts` extracts JSON by string-slicing between first `[` and last `]` — breaks if the model appends trailing prose containing a stray `]`. Documented with a test that asserts the current (broken) behavior. |
| Image Generation (Pollinations, free) | ✅ Done, verified live | 10 real scene images generated and used in renders. |
| Image Generation (other 4 providers: HF, Together, Stability, OpenAI) | 🟡 Built, never run | Code looks complete (real fetch calls), never exercised with a real key. |
| Voiceover — Browser Web Speech | ✅ Done, verified | Playback-only, no downloadable file (by design, free/no-key). |
| Voiceover — Edge-TTS | ✅ Done, verified indirectly | Proven working as part of the `.mp4` render pipeline (backend calls it per-scene). Never run standalone via the Voiceover stage's own UI button. |
| Voiceover — ElevenLabs / Google Cloud TTS / OpenAI TTS | 🟡 Built, never run | Google Cloud TTS was added this session (wires the previously-dead `/api/gtts` proxy route); none of the three have been tested with a real key. |
| Video Generation stage (7 providers: fal, Replicate, HF, MiniMax, Luma, Runway, Veo) | 🟡 Built, never run | All have real implementations (verified by reading code), but **none are free** and no real video-provider key has ever been saved in this project. Deliberately excluded from "Run full pipeline" by design (credit-based). |
| Settings & API key vault | ✅ Done, verified | Rebuilt this session: explicit **Save** button per provider card (previously auto-saved every keystroke), draft state until saved, green "Saved successfully" confirmation reusing the app's free-tier badge colors. |
| Export real `.mp4` (Phase 2 backend) | ✅ Done, verified at scale | Confirmed with a real 2-scene render and a real 10-scene render (valid 1280×720, 55.75s, H.264/AAC). Stitches: real video clip if `Video Generation` produced one for that scene (resized/cropped/looped-or-trimmed to match narration) → **falls back to a Ken-Burns zoom** on the still if not. Captions are a fixed overlay (don't zoom with the background). |
| — real video-clip path specifically | 🟡 Built, **never exercised** | Every test so far used stills only (no Video Generation provider has a saved key), so the "use the actual generated clip" code path in `backend/main.py` has not been hit by a real request — only the Ken-Burns fallback has. |
| Render performance | ⚠️ Known issue | ~42s/scene on this dev machine (Intel i3-5005U, 2 core/4 thread, no dedicated GPU) after a 2.3x optimization (BILINEAR resample + direct frame generation instead of MoviePy's generic Resize+Composite). The in-app UI text still says "~30-90s" for a 6-10 scene video — **that estimate is now wrong** and should be updated or the UI should show a live estimate. |
| Storyboard preview player | ✅ Built | Not fully re-verified after the latest changes; known gap below. |
| Generated media survives a page refresh | ❌ Not built | By design, `store.ts`'s `persist()` only saves `{text, scenes}` per stage to `localStorage`. Images/video/audio are blob URLs that die on reload — hit repeatedly during testing, had to regenerate images/voiceover after every browser reload. |
| Runs outside `npm run dev` (production deploy) | ❌ Not built | Every provider call is routed through Vite's dev-only CORS proxy (`vite.config.ts`). The built `dist/` cannot call any provider API on its own — no production reverse-proxy equivalent exists. |
| Automated tests (Vitest) | 🟡 Written, never run | Two files (`src/stages.test.ts`, `src/providers/index.test.ts`, 15 tests) target the two riskiest pieces of logic (scene-JSON parsing, provider registry). **Blocked**: `npm install` to pull in `vitest` has been refused by Claude Code's own safety classifier every time it's been attempted — this is independent of the project owner's approval, confirmed not installed as of this writing (`node_modules/.bin/vitest` absent). |
| CI | ❌ Not built | No `.github/workflows` or equivalent. |
| Backend Python environment | ✅ Fixed this session | The original `backend/.venv` was copied in from a different developer's machine (`C:\Users\kumar\...`) and was non-functional here (broken interpreter path). Rebuilt cleanly on this machine using `uv` on Python 3.13. |
| Security / key storage | ⚠️ Known limitation, by design for a local tool | API keys stored in plaintext in browser `localStorage`. Acceptable for single-user local use, not acceptable if this becomes a hosted multi-user product. |

**Rough completion estimate** (the project owner's own two bars):
- *"One person, free, topic → finished video, today"*: ~85%. Main gap: the saved Gemini API key is fake (17 chars, doesn't match Google's `AIza…` format) so the free LLM path has never actually been proven end-to-end — only the paid OpenAI path has.
- *"Robust, shippable to others"*: ~60%. Gaps: no CI, tests never run, no persistence across reload, no production deploy story, render speed not acceptable for a product.

## 4. Full codebase structure

```
D:\Youtube_content_creation\
├── README.md                    — product pitch + setup instructions (kept in sync with code this session)
├── AGENT_HANDOFF.md              — THIS FILE
├── package.json                  — scripts: dev, build, preview, test (vitest — not yet runnable, see §3)
├── vite.config.ts                — dev-only CORS proxy for every provider (/api/<name>) + /render → FastAPI backend. NOT present in production build.
├── index.html / tsconfig.json    — standard Vite/React/TS scaffolding
│
├── src/
│   ├── main.tsx                  — React entry point
│   ├── App.tsx                   — top-level layout: Sidebar + InputsBar + (StagePanel | Settings)
│   ├── types.ts                  — all core domain types: Provider, StageDef, StageWiring, StageRuntimeState, Scene, RunContext, etc.
│   ├── stages.ts                 — the 7 pipeline stages + their default editable LLM prompts; fillTemplate(); parseScenes() [FRAGILE — see §3]; dimsToPixels()
│   ├── engine.ts                 — runStage(id) / runAll() / cancelStage(id). Dispatches by provider kind (llm/image/video/tts), wires stage-to-stage data flow (research→script→visuals→images/video/voiceover). runAll() hardcodes order, deliberately excludes "video" and "assemble".
│   ├── store.ts                  — single global store (useSyncExternalStore, no Redux). inputs/secrets/wiring/runtime/view. Persists only {text, scenes} per stage + secrets + wiring to localStorage — NOT images/video/audio (§3).
│   ├── icons.tsx                 — inline SVG icon components
│   ├── styles.css                — all app styling, dark theme. Has the free/freemium/paid badge color tokens reused for the Settings "Saved successfully" pill.
│   │
│   ├── providers/
│   │   ├── index.ts              — allProviders[] registry, providersFor(kind) [sorts free→freemium→paid], getProvider(id), TIER_LABEL
│   │   ├── llm.ts                 — 7 text providers: Gemini, Groq (free) · OpenRouter, Together (freemium) · DeepSeek, OpenAI, Anthropic (paid). All real implementations.
│   │   ├── image.ts               — 5 image providers: Pollinations (free, no key) · HF, Together (freemium) · Stability, OpenAI (paid). All real.
│   │   ├── video.ts                — 7 video providers: fal, Replicate, HF, MiniMax (freemium) · Luma, Runway, Veo (paid). None free. All real implementations (polling-based for async ones). requireRemoteImage() guards image→video modes against local blob URLs.
│   │   ├── tts.ts                  — 4 voice providers: Web Speech (free, playback-only), Edge-TTS (free, needs backend), ElevenLabs (freemium), OpenAI TTS (paid) + Google Cloud TTS (freemium, added this session — wires the previously-dead /api/gtts proxy route).
│   │   └── index.test.ts           — [NEW, unrun] tests providersFor() ordering, getProvider() lookup, no-duplicate-ids, every provider has the right run* function for its kind
│   │
│   ├── components/
│   │   ├── Sidebar.tsx              — 7-stage nav + Run full pipeline / Stop + Settings link
│   │   ├── InputsBar.tsx            — global inputs: Topic, Dimensions (16:9/9:16/1:1), Duration, Audience type, Age group
│   │   ├── StagePanel.tsx           — renders one stage: provider dropdown, param fields, editable system prompt (LLM stages), Run/Stop, output view (text/scenes/images/video/audio depending on stage.kind)
│   │   ├── FieldEditor.tsx          — generic controlled input (text/password/select/number) — reused for both Settings secrets AND stage params, kept intentionally "dumb"/instant-onChange
│   │   ├── Settings.tsx             — [REBUILT this session] API key vault, grouped by kind. ProviderCard sub-component holds local draft state, Save button (disabled until dirty), green success confirmation.
│   │   ├── AssemblePlayer.tsx       — client-side storyboard slideshow (image/clip + caption, synced to voiceover audio duration or 4.5s/scene fallback)
│   │   └── RenderExport.tsx         — [UPDATED this session] talks to the Phase-2 backend: health check badge, voice field, Render .mp4 button. Now sends BOTH image and video (resolveMedia(), blob→dataURL conversion) per scene, not just image.
│   │
│   └── stages.test.ts               — [NEW, unrun] tests parseScenes() (clean JSON, code-fence stripping, snake_case fallback, garbage-input error, and a test that documents the known "stray ] breaks it" fragility), fillTemplate(), dimsToPixels()
│
├── backend/                         — Phase 2: local FastAPI render service
│   ├── main.py                      — [HEAVILY MODIFIED this session]
│   │     Routes: GET /render/health · GET /render/voices (built, unused by frontend) · POST /render/tts · POST /render/video
│   │     /render/video pipeline per scene: if scene.video present → download clip, _cover_resize_video() to fill frame, _fit_video_duration() loops/trims to match narration; else → _ken_burns_clip() (direct per-frame crop+BILINEAR resize, NOT moviepy's generic Resize effect — that was 2.3x slower). _caption_overlay() composites a FIXED caption on top either way. Falls back to Ken-Burns if clip download fails.
│   │     Also fixed this session: a Windows-specific MoviePy bug (WinError 32 — temp audio file transiently locked during muxing, usually by antivirus) via explicit temp_audiofile path + one-time retry.
│   ├── requirements.txt             — fastapi, uvicorn, edge-tts, moviepy, pillow, numpy, requests
│   └── .venv/                       — [REBUILT this session with `uv` on Python 3.13] — gitignored, machine-specific, do not assume it exists on a fresh machine; recreate with `uv venv backend/.venv && uv pip install -r backend/requirements.txt --python backend/.venv`
│
├── .claude/launch.json               — dev-server launch config (frontend only; backend started manually, see README)
└── .gitignore                        — node_modules/, dist/, backend/.venv/, backend/__pycache__/, *.pyc, .env*
```

## 5. Concrete next steps, in priority order

1. **Prove the free path actually works.** Get a real Gemini or Groq key, save it via the new Settings UI, run the full pipeline on 100% free providers (currently only the paid OpenAI path has been proven).
2. **Exercise the real video-clip path.** Get one free/trial video-provider key (fal.ai is easiest — free signup credits), generate a clip for at least one scene, confirm `backend/main.py`'s clip-stitching branch (not just the Ken-Burns fallback) actually works.
3. **Unblock and run the test suite.** `npm install` needs either a Claude Code permission rule or the project owner running it manually once; then `npm test`.
4. **Fix or re-scope render speed.** ~42s/scene is too slow for a real product. Options: ffmpeg-native zoompan filter instead of per-frame PIL, lower default resolution/fps for previews, or accept it and set correct user-facing expectations (the "~30-90s" UI text is currently wrong).
5. **Persist generated media across reload**, or explicitly warn the user before a refresh that in-progress media will be lost.
6. **Decide and build a deployment story** — the dev-only CORS proxy means the built app can't run standalone anywhere else yet.

## 6. The newer, NOT-YET-BUILT "vlog-editing" MVP (context only — no code exists for this)

Discussed but not approved/built as of this document. Requirements gathered so far via Q&A with the project owner (in Hindi/Hinglish conversation):
- **Scope for this MVP**: video generation/editing only — posting to platforms stays manual.
- **Two modes, unified**: (A) existing topic→video flow, (B) new — customer uploads their own footage/vlog, system asks a few parameters (length, style, platform, music mood) + free-text prompt, auto-edits it, customer can preview and give follow-up prompts to tweak ("intro chhota karo" etc.), can swap any scene's clip.
- **Hybrid**: customer can also insert their own clip into specific scenes of an otherwise AI-generated video.
- **Target footage type**: short talking-head vlogs, 1-5 minutes.
- **Edit operations needed**: silence/filler-word/bad-take removal + length trim to target duration, auto captions, music + audio clean-up, B-roll overlay (AI images or stock clips over spoken sections).
- **Output formats**: 16:9 (YouTube), 9:16 (Reels/Shorts/Status — needs smart reframe, not just letterboxing), 1:1 (LinkedIn/Facebook).
- **Language**: Hinglish — captions and any generated text in Roman script (NOT Devanagari), but transcription/voice engines default to Devanagari (Whisper does not support direct Hinglish output — would need Devanagari transcript + a transliteration pass, or a specialized fine-tuned model like `Oriserve/Whisper-Hindi2Hinglish`).
- **Transcription decision**: free-tier **Groq Whisper** (cloud) approved by the project owner — large-v3/turbo, ~8 hours/day free, word-level timestamps, 25MB file-size limit (audio only, not video). Local Whisper was explicitly ruled out as primary (this machine is a 2-core/4-thread i3 with no GPU — too slow/low-quality for Hindi).
- **Narration voice** (topic-mode only): Hindi voice (e.g., Edge-TTS Swara/Madhur) — script in Devanagari for correct pronunciation, captions still rendered in Roman Hinglish on screen.
- **Acceptable wait time**: ~5 minutes for a 3-minute vlog to go from upload to finished edit, on this machine.
- **Cost policy**: free/local-first (ffmpeg, free AI images, free stock like Pexels/Pixabay) — paid APIs only as optional upgrades, not required path.
- **Extras wanted**: platform-wise title/description/hashtag generation, logo watermark + brand colors/font, auto thumbnail, intro/outro clip insertion.
- **Editing engine decision (research done, not yet built/approved as a plan)**: MoviePy (current stack) is too slow for this (~7 min to render a 10-scene topic-video on this hardware). **Remotion was researched and ruled out** — free only for orgs ≤3 people, otherwise $25/seat/month, and is a headless-Chrome renderer (heavy for this hardware). Leaning toward an **ffmpeg-native** approach (filter_complex / zoompan) instead of frame-by-frame Python compositing, but this has NOT been prototyped or measured yet — was the planned first validation step before the requirements conversation was interrupted.
- **Status**: requirements-gathering was in progress (3 rounds of clarifying questions asked and answered) when this was paused. **No plan has been written or approved. No code for this MVP exists.** Before any development starts here, the project owner explicitly required: ask questions until ~95% sure of scope, then present a plan, then wait for explicit approval — only after that, start building.

## 7. Standing rules for whoever works on this next (from the project owner, repeated multiple times)

- **Explain what a task will do and what it affects, then wait for explicit approval, before any action** (builds, tests, installs, edits, commits). This is a durable rule for this project, not a one-off.
- **Do not `git push`** — local commits only, until the owner explicitly says to resume pushing.
- **Do not reuse conventions from the owner's other project ("StandByMe")** — define testing/workflow per this project's own stack, don't import patterns from elsewhere.
- When genuinely verifying something (not just chatting about it), actually run it and show real output/files — this owner has repeatedly asked for proof over claims.
