# AI YT Studio: Product Requirements Document (PRD) v1.0

Owner: single user (private tool). Date: 2026-10-10.
Audience: Claude Code (implementer). Written in English for precision; UI strings are in Hindi (Devanagari) unless noted.

---

## 0. How Claude Code must use this document

1. Read this whole document first.
2. **Inspect the existing repository without editing anything.** Do not assume the structure described below is current; verify it.
3. Write `docs/IMPLEMENTATION_PLAN.md` containing:
   - gap analysis: existing code vs. this PRD
   - for each existing file: keep / change / delete, with a reason
   - the phase plan from section 13 adapted to the real repo, with hour estimates
   - open questions and any PRD assumption (section 15) that the repo contradicts
4. **Stop and wait for the owner's approval of that plan** before changing code.
5. Execute phases in order. After each phase: run that phase's acceptance checks (section 14), commit, and report what passed, what failed, and what was not tested.
6. If an assumption in section 15 turns out to be false, stop and ask. Do not silently work around it.
7. Never mark something "done" that was not actually run. Say "not tested" instead.

Facts about the existing repo from an earlier audit (2026-10-10, **verify**): React + Vite frontend, FastAPI backend, MoviePy rendering (~40 s per scene, the main bottleneck), no database, no job queue, API keys kept in browser localStorage, provider calls routed through a Vite dev-only proxy (does not exist in production).

---

## 1. Product summary

**AI YT Studio** is a private, web-based (PWA) tool for making Hindi/Hinglish YouTube videos, deployed on Railway and used mainly from a phone, also from a laptop. It has two workflows:

- **Workflow A: Edit my video (built first).** Upload a 1-2 minute video, describe the edits in plain language with timestamps, review the proposed edit plan, approve, get an edited MP4.
- **Workflow B: Create a video from a topic (built second).** Give a topic. A setup wizard collects style, language, format, avatar, voice and layout. The tool researches, writes a script, and produces a video in which an animated avatar sits on a chair and speaks to the camera, with reference images/clips appearing around or over it.

**Positioning (from market research):** a free, private, Hindi-first alternative to OpusClip/Descript/InVideo-style tools. The unfilled gap is Hindi-first quality (Devanagari captions) combined with cheap editing of the user's own footage and bring-your-own-keys operation. Topic-to-faceless-video alone is saturated (for example MoneyPrinterTurbo, free and open source), so Workflow A is the differentiator and Workflow B must be good rather than merely present.

**MVP 1 uses only free providers.** Premium providers are added later by the user through the settings page without code redesign (section 6).

---

## 2. Goals, non-goals, success criteria

### 2.1 Goals
- G1: Edit a 1-2 minute Hindi vlog from a text prompt with timestamps, with a human-approved edit plan.
- G2: Generate a 1-5 minute Hindi/Hinglish topic video with an animated avatar, at zero rupees, end to end.
- G3: Correct Devanagari captions (matras and conjuncts render correctly), word-synced.
- G4: Phone-friendly PWA behind a password gate, deployed on Railway.
- G5: A provider layer where free and premium options live side by side in dropdowns, with automatic free fallback.
- G6: API keys are never stored on the server (not in DB, not in files, not in logs).

### 2.2 Non-goals for MVP 1
- Premium providers (Sarvam, voice cloning, realistic lip-sync avatars): architecture is ready, adapters are not built (section 3).
- Avatar from the user's own photo.
- Marathi or other languages (the provider layer must stay language-agnostic, but only Hindi and Hinglish/English are tested).
- Native mobile app (PWA only).
- YouTube upload API, multi-user accounts, billing, public hosting.
- Full timeline editor, batch generation (also a YouTube monetization risk, section 12.3).

### 2.3 Success criteria
**Workflow A is successful when:** the owner uploads a 60-second video, writes a prompt such as "0:12 to 0:18 remove; at 0:30 show the text 'Important'; add Hindi captions; zoom in at 0:40-0:45", reviews the generated plan, approves it, and receives an MP4 where:
- each requested edit is applied at the right place in the original timeline (cut boundaries within 0.2 s)
- Devanagari captions are correctly shaped and synced to speech
- the plan the tool showed matches what was rendered

**Workflow B is successful when:** the owner enters a topic (for example a Hindi history topic), completes the wizard, and gets a 3-minute video (16:9 or 9:16) with avatar, voice, captions and inserts, using only free providers, without manual file handling.

**Performance targets (UNVERIFIED, must be benchmarked on Railway in Phase 0):**
- Workflow A render time at most 3x the video duration for 1-2 minute inputs.
- Workflow B 3-minute video total at most 15 minutes.

---

## 3. Scope by release

| Area | MVP 1 (build now) | MVP 2 (later, user-triggered) |
|---|---|---|
| LLM | Groq, Gemini, OpenRouter (free) | Paid tiers/grounding |
| Voice (TTS) | Edge-TTS (default), Kokoro (optional fallback) | Sarvam Bulbul, voice cloning (own voice) |
| Speech-to-text | Groq Whisper (default); local faster-whisper (fallback) | Sarvam STT |
| Images | Pollinations (free), Wikimedia Commons (optional) | Paid image APIs |
| Stock footage/photos | Pexels, Pixabay | none |
| Avatar | 2D layered cartoon, preset characters | Realistic lip-sync avatar (HeyGen-class API), own-photo avatar |
| Captions | Devanagari word-synced ASS | none |
| Extras | Topic research and fact check, YouTube title/description/tags, thumbnail | Publishing API |

Budget note: the owner set up to INR 500 per month for premium later. Realistic lip-sync avatar APIs may exceed that. Prices are not verified; check them when Premium work starts.

---

## 4. Workflow A: Edit my video

### 4.1 User flow
1. **Upload** a video (mp4/mov/webm). Limit: 3 minutes, 300 MB (configurable). Validate with `ffprobe`; reject if no video stream or longer than the limit.
2. **Transcribe** automatically (STT provider with word timestamps). Show the transcript with timestamps (read-only in MVP 1).
3. **Prompt**: free text in Hindi/Hinglish/English describing edits.
4. **Edit plan**: the LLM converts the prompt (plus the transcript) into a structured plan. The UI shows it as an editable list, one row per operation, with start/end times, parameters, and a delete button for each row. The user may also add or edit rows manually.
5. **Approve** and render. Nothing renders before approval.
6. **Result**: video player plus download button. Offer "adjust prompt and re-render" without re-uploading or re-transcribing.

### 4.2 Operation types (all four categories chosen by the owner)

All timestamps in the prompt and plan refer to the **original** video timeline. The compiler maps them to output time after cuts and speed changes.

| Op | Parameters | Notes |
|---|---|---|
| `cut` | `start`, `end` | Remove a segment. |
| `remove_silence` | `min_silence_ms` (default 600), `threshold_db` (default -35), optional range | Detected with ffmpeg `silencedetect`; converted into `cut`s. |
| `captions` | `style` (preset id), `range` (default whole video), `language` | Words from the transcript, remapped after cuts. Devanagari-safe font. |
| `text_overlay` | `start`, `end`, `text`, `position`, `style` | Static text box. |
| `zoom` | `start`, `end`, `scale` (1.1-2.0), `focus` (center by default) | Smooth zoom via ffmpeg `zoompan`/crop expressions. |
| `speed` | `start`, `end`, `factor` (0.5-2.0) | Adjust audio with `atempo`. |
| `music` | `track` (upload or bundled), `volume`, `duck` (bool) | Auto-ducking under speech. |
| `broll` | `start`, `end`, `source` (`stock:<query>` or `upload:<asset_id>`), `mode` (`overlay` or `replace`) | Stock via Pexels/Pixabay with attribution recorded. |
| `audio_cleanup` | `denoise`, `loudnorm` (bools) | ffmpeg `afftdn`, `loudnorm`. |

### 4.3 Plan schema (validated with pydantic; reject or repair invalid LLM output)
```json
{
  "version": 1,
  "source_duration_s": 61.4,
  "ops": [
    {"id": "op1", "type": "cut", "start": 12.0, "end": 18.0},
    {"id": "op2", "type": "text_overlay", "start": 30.0, "end": 33.0,
     "text": "महत्वपूर्ण", "position": "bottom_center", "style": "bold_yellow"},
    {"id": "op3", "type": "zoom", "start": 40.0, "end": 45.0, "scale": 1.4},
    {"id": "op4", "type": "captions", "style": "hindi_bold_word_highlight"}
  ],
  "warnings": ["Prompt said '0:35' but video is 0:34 long; clamped to end."]
}
```
Validation rules: clamp times to `[0, duration]`; reject `start >= end`; detect overlapping `cut`s and merge; refuse ops that cannot be mapped; every ambiguity goes into `warnings` and is shown to the user. If the LLM cannot parse a timestamp, it must ask rather than guess (the UI shows a question on the plan screen).

### 4.4 Edge cases
- Prompt has no timestamps: the LLM may propose ranges from the transcript (for example "remove the part where I repeat myself") and must mark them `proposed_by_ai`; the user confirms.
- Video has no speech: captions are skipped with a visible notice.
- Portrait vs landscape input: preserve the source aspect by default; the output aspect option is MVP 2 (auto-reframe is a later feature).
- Variable frame rate phone videos: normalize to constant frame rate during ingest.
- Upload interrupted: resumable not required in MVP 1; show a clear retry.

---

## 5. Workflow B: Create a video from a topic

### 5.1 Setup wizard (screens in order)
1. **Topic** and short notes (free text). Optional: audience, tone.
2. **Language**: Hindi or Hinglish/English.
3. **Format and length**: 16:9 or 9:16; length 1, 2, 3, 4 or 5 minutes.
4. **Avatar**: choose from preset characters (2 to 3 in MVP 1). Pick outfit/background from presets.
5. **Voice**: provider dropdown (Free: Edge-TTS voices; Premium appears when its key is saved) and voice selection with a preview button.
6. **Layout**: choose one of the layouts below or "Auto".
7. **Captions style** (preset).
8. **Review and start.**

### 5.2 Layouts (all four requested by the owner)
| Id | Description |
|---|---|
| `avatar_center_side_inserts` | Avatar seated in the middle, small images or clips beside it that refer to what is being said. |
| `broll_fullscreen_avatar_corner` | Full-screen image or clip for a scene; avatar small in a corner. |
| `avatar_only` | Avatar with captions only. |
| `auto` | The LLM picks a layout per scene based on the script. |

### 5.3 Generation pipeline
1. **Research and fact check.** Baseline free source: Wikipedia REST API (Hindi/English) plus the user's notes. The LLM extracts key facts, each with a source URL; claims it cannot support are marked `uncertain`. The user can **review and edit facts** before the script is written. This matters for historical topics. (Search grounding through Gemini is paid: Premium later.)
2. **Outline**: 4-6 chapters (for 5 minutes), fewer for shorter videos.
3. **Script per chapter**: one LLM call per chapter returning narration plus scenes.
4. **Voice**: TTS per scene or chapter; measure real audio duration. **Scene durations come from real audio, never from LLM guesses.** Obtain word timings (Edge-TTS word-boundary events, otherwise STT on the generated audio).
5. **Visuals per scene**: search stock (Pexels/Pixabay) or generate an image (Pollinations). Cache search results for 24 hours (Pixabay requires it). Store attribution.
6. **Avatar track**: render the avatar video from audio (section 11.4).
7. **Compose** per chapter with ffmpeg according to the layout; apply captions; add music with ducking if chosen.
8. **Concatenate** chapters without re-encoding where possible.
9. **YouTube pack**: title, description, tags, thumbnail (section 5.5).

### 5.4 Scene JSON (LLM output, validated)
```json
{
  "chapter": 1,
  "narration": "…",
  "scenes": [
    {"id": "s1", "text": "…", "layout": "avatar_center_side_inserts",
     "visual": {"kind": "stock_image", "query": "Raigad fort", "alt_queries": ["Maharashtra hill fort"]},
     "fact_refs": ["f3"], "est_seconds": 8}
  ]
}
```
`est_seconds` is advisory only. Validate with pydantic; on failure retry once with a repair prompt, then fall back to the next LLM provider.

### 5.5 YouTube pack (included in MVP 1)
- Title (3 options), description with chapter timestamps, tags.
- Thumbnail: Pillow-rendered image with Devanagari text (bundled Noto Sans Devanagari), using a frame or avatar crop. 1280x720.
- Attribution lines for stock assets.
- **Mandatory AI disclosure reminder** on the export screen: the user must tick that they will set YouTube's altered/synthetic content disclosure. Also a "human value" nudge (add your own voice, research, opinion) because of the YouTube inauthentic-content policy (section 12.3).

### 5.6 Avatar scope in MVP 1
Preset 2D layered characters seated on a chair facing the camera, with mouth movement driven by the audio and idle blinking. Characters are created as images plus a small config file (mouth anchor, scale, eye positions). See 11.4 and the risk in section 15. Own-photo avatars and realistic lip-sync are MVP 2 via premium providers.

---

## 6. Provider registry and Settings page

### 6.1 Concept
Every external capability is a **capability slot** with multiple **providers**. Each provider is an adapter implementing one interface. Free and premium providers appear together in the same dropdown. Adding a premium provider later means adding one adapter file plus one registry entry, with no changes to workflows.

Capabilities: `llm`, `tts`, `stt`, `image`, `stock`, `avatar`.

### 6.2 Provider adapter interface (conceptual)
```
id, label, capability, tier ("free" | "premium"),
requires_keys: [ {name, label, docs_url} ],
limits_note: string,          # human-readable rate limit info with "as of" date
supports: {languages, formats},
health_check(keys) -> ok | error(reason)
call(request, keys) -> result  # keys passed in per request, never stored
```

### 6.3 MVP 1 registry (all free)
| Capability | Providers (priority order) | Key needed | Docs link (put on settings page) |
|---|---|---|---|
| llm | Groq, Gemini, OpenRouter (free models) | yes (each) | https://console.groq.com/keys ; https://aistudio.google.com/app/apikey ; https://openrouter.ai/keys |
| tts | Edge-TTS; Kokoro (optional, local) | none | https://github.com/rany2/edge-tts ; https://github.com/hexgrad/kokoro |
| stt | Groq Whisper; faster-whisper (local) | Groq key / none | https://console.groq.com/docs/speech-to-text ; https://github.com/SYSTRAN/faster-whisper |
| image | Pollinations; Wikimedia Commons (optional) | none (verify) | https://pollinations.ai ; https://commons.wikimedia.org |
| stock | Pexels; Pixabay | yes (each) | https://www.pexels.com/api/ ; https://pixabay.com/api/docs/ |
| avatar | Layered 2D cartoon (built in) | none | n/a |

Premium placeholders (not implemented in MVP 1; show them **disabled** with "coming later" so the dropdown structure is visible): Sarvam Bulbul (TTS, https://www.sarvam.ai/api-pricing), ElevenLabs (voice cloning), a realistic lip-sync avatar provider. **All premium links and prices are UNVERIFIED; check at implementation time.**

### 6.4 Settings page (requirements)
- One section per capability. Each shows the dropdown of providers, a "default" selection, and the tier badge (Free/Premium).
- For each provider that needs keys: input fields, a "Test key" button, a status (not set / valid / invalid / rate-limited), and the **"How to get this key" docs link**.
- A provider whose key is missing is shown greyed in workflow dropdowns with the text "key डालो" and a link to Settings.
- Selecting a provider in a workflow dropdown uses it for that run. If the chosen provider has no key or fails, behave per 6.6.
- A short, honest note on the page: "Keys are saved only in this browser, never on the server. If you clear browser data or use another device you must enter them again."
- A "Clear all keys" button.

### 6.5 Key handling (owner's requirement: keys not in the DB and not anywhere on the server)
- Keys live **only in the browser** (localStorage, as the existing code already does). Do not move them server-side.
- The browser sends the needed keys to the backend with each request over HTTPS in a request header (never in the URL or query string).
- The server uses them in memory only. A background job keeps its keys in memory for the life of that job. They are **never** written to disk, SQLite, logs, job records, error reports, or exception traces. Add log redaction and a test that greps logs and the DB for a sentinel key after a run.
- If the server restarts mid-job, the job fails with "restart the job"; do not persist keys to survive restarts.
- Mitigate XSS risk: strict Content-Security-Policy, no third-party scripts, no `dangerouslySetInnerHTML`, dependencies pinned.
- Non-secret preferences (selected providers, defaults) may be stored in the DB.

### 6.6 Automatic fallback
- If the chosen provider fails (rate limit, timeout, invalid output), automatically try the next provider of the same capability **among free providers with available keys**, and show a visible notice in the job log and UI: "Groq limit reached, switched to Gemini."
- Never auto-switch to a **premium** provider (it costs money). Premium is used only if the user explicitly selected it.
- If every option fails, stop the job at that step, keep all completed work, and let the user retry or pick another provider.
- Retry transient errors with backoff (respect `Retry-After`). Failed requests may still count against OpenRouter free limits, so cap retries.

---

## 7. Architecture

### 7.1 Stack
- **Frontend:** React + Vite, built as a PWA (web manifest, service worker for app shell only, installable on phone). Mobile-first layouts, large tap targets, works on a 380 px wide screen.
- **Backend:** FastAPI (Python), serving the built frontend as static files in production (single Railway service).
- **Rendering:** ffmpeg (per-scene commands, concat demuxer). **MoviePy is removed.**
- **Jobs:** an in-process job runner backed by SQLite (no Redis). A worker thread pool with concurrency 1 by default (configurable to 2); each job runs ffmpeg as a subprocess so it can be cancelled by killing the process.
- **Storage:** Railway Volume mounted at `/data`; SQLite file and media under it. Keys never touch it.
- **Auth:** a single password gate (section 12.1).
- **Container:** Dockerfile includes ffmpeg built with libass and HarfBuzz, `fonts-noto` plus Noto Sans Devanagari, Python dependencies, and the built frontend.

### 7.2 Railway constraints (verify in Phase 0)
- No GPU. Everything must run on CPU, so no local heavy models by default (faster-whisper and Kokoro are optional fallbacks and must be benchmarked on the actual plan).
- CPU and RAM depend on the plan; check the service's limits and set concurrency accordingly.
- HTTP requests have time limits, so every long operation is a background job with progress polling or SSE. Uploads should be streamed to disk.
- The container filesystem is ephemeral; only the Volume persists.
- Edge-TTS is an unofficial Microsoft endpoint (LGPL-3.0 library). It may break or block; the fallback path must work.

### 7.3 Module layout (suggested; adapt to the real repo)
```
backend/
  app/main.py                # FastAPI app, static serving, auth middleware
  app/auth.py                # password gate, signed session cookie
  app/jobs/                  # job runner, progress, cancel
  app/providers/             # registry + adapters per capability
  app/pipelines/edit/        # Workflow A: ingest, plan, compile, render
  app/pipelines/create/      # Workflow B: research, script, tts, visuals, avatar, compose
  app/render/                # ffmpeg command builders, ASS caption writer, avatar renderer
  app/models.py              # SQLAlchemy/pydantic models
  app/security/redact.py     # log redaction
frontend/
  src/pages/                 # see 10
  src/providers/             # provider metadata, key storage (localStorage)
Dockerfile, railway.json, .env.example
```

---

## 8. Data model (SQLite)

No secrets in any table.

- `projects(id, kind[edit|create], title, status, created_at, updated_at, settings_json)`
- `assets(id, project_id, kind[upload|audio|image|video|music|thumbnail|output], path, mime, duration_s, meta_json, attribution)`
- `transcripts(id, project_id, provider, language, words_json)`  # word-level timestamps
- `edit_plans(id, project_id, version, prompt, plan_json, approved_at)`
- `scripts(id, project_id, facts_json, outline_json, chapters_json)`
- `jobs(id, project_id, kind, status[queued|running|done|failed|cancelled], step, progress, log_json, error, started_at, finished_at)`
- `preferences(key, value)`  # selected providers, defaults, caption style; non-secret only
- `stock_cache(provider, query_hash, response_json, fetched_at)`  # 24 h TTL

Retention: a setting for auto-deleting finished project media after N days (default 30), because the Volume is limited.

---

## 9. API (all under `/api`, all require the session cookie except `/api/auth/*`)

Keys travel in the `X-Provider-Keys` header (JSON, base64) on each request that needs them; never in URLs or bodies that get logged.

| Method + path | Purpose |
|---|---|
| `POST /auth/login`, `POST /auth/logout`, `GET /auth/me` | Password gate |
| `GET /providers` | Registry metadata: capabilities, providers, tiers, docs links, limits notes |
| `POST /providers/{id}/test` | Test a key (key in header, not stored) |
| `GET/PUT /preferences` | Non-secret defaults |
| `GET/POST /projects`, `GET/DELETE /projects/{id}` | Project CRUD |
| `POST /projects/{id}/upload` | Streamed upload (Workflow A source, music, user images) |
| `POST /projects/{id}/transcribe` | Start STT job |
| `POST /projects/{id}/plan` | Prompt to edit plan (LLM) |
| `PUT /projects/{id}/plan` | Save user edits to the plan |
| `POST /projects/{id}/approve-and-render` | Compile and render (Workflow A) |
| `POST /projects/{id}/research` | Facts for a topic (Workflow B) |
| `PUT /projects/{id}/facts` | Save user-edited facts |
| `POST /projects/{id}/script` | Outline + chapter scripts |
| `POST /projects/{id}/generate` | Run the full B pipeline (or resume from a step) |
| `POST /projects/{id}/scenes/{sid}/regenerate` | Per-scene regenerate (image/voice/text) |
| `GET /jobs/{id}` , `GET /jobs/{id}/events` (SSE) | Progress and logs |
| `POST /jobs/{id}/cancel` | Kill ffmpeg and stop |
| `GET /projects/{id}/output`, `GET /assets/{id}` | Download/stream media (range requests) |
| `POST /projects/{id}/youtube-pack` | Titles, description, tags, thumbnail |

Errors use a consistent JSON shape with a user-readable Hindi message and a technical code.

---

## 10. Screens (mobile-first)

1. **Login** (password).
2. **Home**: two big cards, "वीडियो एडिट करो" (A) and "टॉपिक से वीडियो बनाओ" (B); recent projects.
3. **A: Upload + transcript.**
4. **A: Prompt + edit plan** (editable list, warnings, approve button).
5. **A: Render progress + result.**
6. **B: Wizard** (section 5.1), then **fact review**, **script review** (edit narration per chapter), **progress**, **result**, **YouTube pack** with disclosure checkbox.
7. **Project page**: scenes list with per-scene regenerate (B), re-render (A).
8. **Settings**: provider dropdowns, keys, docs links, test buttons, defaults, caption style, clear keys, data retention.
9. **Job log drawer** showing fallback notices and errors.

UI language Hindi with English technical terms where clearer. Accessible contrast; font for Devanagari in the UI must render properly (Noto Sans Devanagari).

---

## 11. Rendering specification

### 11.1 General
- Output H.264 (`libx264`, `-preset veryfast`, `-crf 23`), AAC, `yuv420p`, `+faststart`. Default 720p; 1080p optional. 16:9 = 1280x720 / 1920x1080; 9:16 = 720x1280 / 1080x1920. 24 or 30 fps (keep source fps for Workflow A).
- Build ffmpeg commands as argument arrays, never shell strings built from user text (injection safety). Text for overlays/captions goes through ASS files, never inline in filter strings.
- Report progress using `-progress pipe:1`; map to percentage using known duration.
- Cancel = terminate the process group.

### 11.2 Captions (Devanagari)
- Generate ASS subtitles with `Noto Sans Devanagari` (bundled in the image and referenced by path via `fontsdir`).
- Word-synced style: show a few words at a time with the current word highlighted (karaoke tags), or line-by-line preset. Position and size adapt to 16:9 vs 9:16.
- **Phase 0 test (blocking):** render a test sentence with matras and conjuncts (for example "क्षत्रिय", "श्रीमान", "द्वारा", "कर्मचारियों") through ffmpeg/libass inside the Railway container image and inspect the frames. If shaping is wrong, fix before anything else (check libass built with HarfBuzz; fall back to rendering caption images with Pillow + Raqm).

### 11.3 Workflow A compilation
1. Normalize ingest (constant frame rate, standard audio) into a working file.
2. Convert `remove_silence` into `cut`s and merge with explicit `cut`s into a set of kept segments (in original time).
3. Build a time map original to output, accounting for cuts and `speed` ops.
4. Per kept segment, apply zoom, speed, overlays, b-roll with filters; concat segments (re-encode only when filters require it).
5. Remap transcript words through the time map; write ASS; burn in.
6. Mix music (with `sidechaincompress` ducking if enabled), apply optional `afftdn` and `loudnorm`.
7. Verify output duration equals the expected duration from the time map within 0.1 s; otherwise fail loudly.

### 11.4 Avatar renderer (Workflow B, free 2D)
- Character package: `body.png` (seated, mouth closed, eyes open), `eyes_closed.png` overlay, mouth sprites for 4 levels (closed, small, medium, wide) plus a config (`mouth_anchor`, `scale`, `eye_anchor`) and an optional background set.
- Mouth control is **audio-driven and language-agnostic**: compute an RMS envelope of the TTS audio (about 40 ms windows), smooth it, quantize to the 4 mouth levels. This avoids needing phoneme data for Hindi.
- Idle motion: random blinks every 3-6 s, subtle breathing (1-2 px vertical sway).
- Rendering approach: composite frames with Pillow/numpy and pipe raw frames into ffmpeg (alpha or on the chosen background), at 24 fps. **Benchmark on Railway CPU in Phase 0**; if too slow, pre-render a small set of mouth-state clips and switch between them with ffmpeg `overlay`/`enable` expressions, or lower the avatar frame rate to 12 fps and interpolate.
- Characters are created by the implementer: neutral AI-generated image (mouth closed) with mouth sprites **drawn programmatically** (vector shapes tinted to match skin tone) and positioned using the config. This avoids needing the AI image to have separable mouth layers. Ship 2-3 characters and 2-3 backgrounds (for example a study room, a library).
- Layout positions: center, side-inserts, or small corner (about 25% of frame width).

### 11.5 Inserts and visuals
- Images: scale/crop to target; slow Ken Burns via `zoompan` on pre-scaled images (pre-scale to output size for speed).
- Clips: trim with `-ss`/`-t`, scale, crop, mute.
- Side inserts: rounded-corner or bordered frames with a soft fade in/out timed to the sentence that mentions them.
- Optional crossfades with `xfade` between scenes.
- Parallelism: render at most 2 scenes at once; respect the container's CPU count.

---

## 12. Security, privacy, compliance

### 12.1 Password gate
- Single password from environment variable `APP_PASSWORD` (this is the gate password, not a provider key). Signed, HttpOnly, SameSite=Lax, Secure cookie using `SESSION_SECRET` from environment.
- Rate-limit login attempts (for example 5 per 10 minutes per IP) and add a short delay on failure.
- All `/api` and media routes require the session. Media URLs are not guessable and still require the session.
- `.env.example` documents `APP_PASSWORD`, `SESSION_SECRET`, `DATA_DIR`. No provider keys appear anywhere in env files.

### 12.2 General security
- Validate uploads with `ffprobe`, size and duration limits, store with generated file names.
- No shell string interpolation of user text; ffmpeg argument arrays only.
- Strict CSP, HTTPS only, secure headers, CORS limited to the same origin.
- Log redaction middleware; never log request headers containing keys.
- Respect third-party terms: Pexels attribution, Pixabay no hotlinking and 24 h cache, Wikimedia attribution when used.

### 12.3 YouTube compliance (from research, YouTube inauthentic content policy effective 15 July 2025)
- AI-generated content is allowed, mass-produced templated content is not monetizable.
- The tool must not encourage batch/templated uploads: no "generate 20 videos" feature.
- The export screen requires a tick on the AI disclosure reminder and shows a short checklist (own voice/opinion/research added, varied structure).
- The owner is responsible for setting YouTube's disclosure in YouTube Studio.

### 12.4 Voice cloning (MVP 2)
- Only the owner's own voice, with explicit consent confirmation in the UI. No cloning of other people's voices.

---

## 13. Build order for Claude Code

Hour figures are rough estimates for Claude Code working time and are UNVERIFIED; replace them with real estimates in `IMPLEMENTATION_PLAN.md`.

**Phase 0: Inspect and de-risk (about 2-3 h).** Inspect the repo and write the plan. Then run the blocking experiments inside the actual Railway container image:
1. Devanagari caption rendering test (11.2).
2. One-scene ffmpeg benchmark vs. the existing MoviePy path.
3. Avatar frame rendering speed on Railway CPU (11.4).
4. Railway CPU/RAM limits and upload size behavior.
5. Groq Whisper word-timestamp output for a Hindi sample.
Report results; stop for approval if any result invalidates an assumption.

**Phase 1: Foundation (about 3-4 h).** Dockerfile (ffmpeg, fonts), Railway config, FastAPI serving the frontend, password gate, SQLite + Volume, job runner with progress/cancel, provider registry, Settings page with browser-only key storage, redaction and the sentinel-key test, PWA shell.

**Phase 2: Workflow A (about 6-8 h).** Upload, ingest, STT, LLM plan with validation, plan editor UI, compiler, all op types, Devanagari captions, music ducking, result screen, re-render without re-upload.

**Phase 3: Workflow B (about 12-16 h).** Wizard, research and fact review, script generation, TTS and word timings, stock/image search with cache and attribution, avatar renderer and 2-3 characters, layouts, composition, concat, per-scene regenerate, YouTube pack and thumbnail, disclosure gate.

**Phase 4: Hardening (about 3-4 h).** Fallback behavior tests, error messages in Hindi, retention cleanup, performance tuning, full acceptance run, README with deployment steps.

Per phase: commit with a clear message, no secrets in the repo, and update `docs/STATUS.md`.

---

## 14. Test plan and acceptance checks

Do not close a phase until its checks have actually been run.

**Foundation**
- Unauthenticated requests to `/api` and media are rejected; login rate limit works.
- Sentinel-key test: send a unique fake key, run a job, then grep the SQLite file, `/data`, and application logs; the key must not appear.
- Job cancel kills the ffmpeg process within a few seconds.
- App installs as a PWA on a phone and the layout fits a 380 px screen.

**Workflow A**
- 60 s sample, prompt with one cut, one overlay, one zoom, captions: the plan matches the prompt; output has the right duration (time-map check); cut boundaries within 0.2 s.
- Devanagari captions visually correct on the conjunct test sentences.
- Invalid LLM output (simulate) is repaired or falls back, not crashed.
- Timestamp past the end of the video yields a warning, not a failure.
- Silence removal works on a sample with pauses; audio stays in sync (check start/end of segments).

**Workflow B**
- 1-minute and 3-minute topic runs on free providers only, in both 16:9 and 9:16.
- Avatar mouth visibly follows speech; blinking present; no frozen frames.
- Fallback: disable the first LLM key and confirm automatic switch with a visible notice; confirm no automatic switch to premium.
- Stock results are cached (second run does not re-call the API within 24 h); attribution is recorded and shown.
- Scene durations match actual audio durations.
- Disclosure checkbox is required before export/download of the YouTube pack.

**Cross-cutting**
- All provider adapters pass a mock-based contract test; real-key tests are manual and documented.
- Record measured timings for each stage in `docs/BENCHMARKS.md`.

---

## 15. Assumptions, risks, open items

| # | Item | Why it matters | How to resolve |
|---|---|---|---|
| 1 | Railway CPU/RAM is enough for ffmpeg + avatar frames within the time targets | Targets are guesses | Phase 0 benchmarks |
| 2 | Devanagari shaping works in the container's ffmpeg/libass | Core product promise | Phase 0 test; Pillow+Raqm fallback |
| 3 | Programmatic mouth sprites on an AI-generated character look acceptable | Biggest art/quality risk | Prototype in Phase 0; allow simpler characters if needed |
| 4 | Edge-TTS keeps working | Unofficial endpoint | Kokoro/other fallback; adapter isolation |
| 5 | Groq/Gemini/OpenRouter free limits change | Fallback chain and docs notes | Read limits in each console and record with dates; Gemini free limits were not verified |
| 6 | Pollinations free access terms may change | Image source | Keep Pexels/Pixabay/Wikimedia as alternatives; verify terms |
| 7 | Browser-only key storage is exposed to XSS and is lost on data clear | Owner's explicit choice | CSP, no third-party scripts, clear UI warning |
| 8 | Keys held in memory during a job vanish on restart | Jobs can fail | Fail clearly, allow resume from last completed step |
| 9 | Premium prices and APIs (Sarvam, ElevenLabs, lip-sync) are unverified | MVP 2 budget (INR 500/month) | Verify before Phase after MVP 1 |
| 10 | Music: licensing of bundled tracks is unverified | Copyright | Default to user-uploaded music; bundle only tracks with a verified license |
| 11 | Hindi historical accuracy | Reputation, YouTube quality | Fact review step with sources; `uncertain` flags; user edits |
| 12 | YouTube monetization policy risk | Revenue | Section 12.3; no batch features |

---

## 16. Appendix: research facts and links (verified on 2026-10-10 unless marked)

**Verified from official sources during research:** MoneyPrinterTurbo (GitHub, MIT, about 127k stars, active); Remotion license (free for individuals and up to 3-person for-profit teams); Edge-TTS (LGPL-3.0, unofficial); Groq free limits (console.groq.com/docs/rate-limits); OpenRouter free model limits (openrouter.ai/docs/api_reference/limits); Pexels API (attribution required, quota program paused); Pixabay API (24 h caching, no hotlinking); Sarvam TTS at INR 3 per 1,000 characters (sarvam.ai/api-pricing); YouTube inauthentic content policy of 15 July 2025; faster-whisper README speeds (measured on an i7); Kokoro Apache-2.0 license.

**Unverified (re-check before relying):** exact Gemini free-tier RPM/RPD; competitor free-tier numbers (Fliki, Descript, Submagic, Vizard, Canva, CapCut, VEED, Kapwing, HeyGen, Runway, Lumen5); status of MoneyPrinterV2/ShortGPT; free credits of video-generation APIs; all performance figures for Railway.

**Reference links**
- Groq limits: https://console.groq.com/docs/rate-limits
- Gemini limits: https://ai.google.dev/gemini-api/docs/rate-limits
- OpenRouter limits: https://openrouter.ai/docs/api_reference/limits
- Pexels API: https://www.pexels.com/api/
- Pixabay API: https://pixabay.com/api/docs/
- Edge-TTS: https://github.com/rany2/edge-tts
- Kokoro: https://github.com/hexgrad/kokoro
- faster-whisper: https://github.com/SYSTRAN/faster-whisper
- Sarvam pricing: https://www.sarvam.ai/api-pricing
- YouTube monetization policy: https://support.google.com/youtube/answer/1311392
- YouTube AI disclosure: https://support.google.com/youtube/answer/14328491
- MoneyPrinterTurbo: https://github.com/harry0703/MoneyPrinterTurbo
- Remotion license: https://www.remotion.dev/docs/license

**Competitive features retained from research (priority, effort):** Devanagari word-synced captions (very high), stock footage per scene (very high), fast ffmpeg rendering with progress/cancel (high), background music with ducking (high), project save/load (high), per-scene regenerate (high), upload-transcribe-cut workflow (very high, the differentiator), LLM highlight selection and auto-reframe 16:9 to 9:16 (later), YouTube metadata (included), transitions and audio cleanup (small, included).

