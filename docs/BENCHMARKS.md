# BENCHMARKS.md

Measured timings (PRD §14 cross-cutting). Machine: owner's laptop, Intel i3-5005U (2 cores / 4 threads, 2015), 12 GB RAM, no GPU, Windows 10. **Railway numbers: not measured yet** (deferred by owner).

| Date | What | Setup | Result |
|---|---|---|---|
| 2026-09-22 | Legacy MoviePy render, 10 scenes (~55.8 s video) | legacy `backend/main.py`, per-frame PIL Ken-Burns | 6 m 56 s wall (≈ 42 s per scene) |
| 2026-10-10 | ffmpeg-native single scene, zoompan direct + ASS captions + AAC | 5.5 s scene, 1280×720, libx264 veryfast crf 23 | **3.0 s** (0.55× real time) |
| 2026-10-10 | same, scale→zoompan (smoother) | | 3.8 s (0.69×) |
| 2026-10-10 | same, static image | | 1.7 s (0.32×) |
| 2026-10-10 | Avatar frames, full-frame Pillow composite → ffmpeg pipe | synthetic character, 240 frames @24 fps | 7.3 s for 10 s video (32.8 fps) |
| 2026-10-10 | Avatar frames, region-only composite | same | **5.4 s for 10 s video (44.5 fps)** |
| 2026-10-10 | Edge-TTS Hindi (Swara/Madhur), 18-word sentence, WordBoundary | network | ≈1.5 s; 18/18 word timings |
| 2026-10-10 | v2 job runner: cancel of a running ffmpeg job | pytest `test_cancel_kills_ffmpeg_within_seconds` + UI test | process gone in < 5 s (UI: cancelled at 14 %) |

| 2026-10-11 | Workflow A ingest, 3:00 1280×720 30 fps H.264 → CFR 720p work file + FLAC | local API | **83 s** (≈ 2.2× real time) |
| 2026-10-11 | Workflow A render, same 3:00 video: 2 cuts + remove_silence (35 silences) + word-highlight captions (251 words) + overlay + 2 zooms + 1.5× speed + denoise/loudnorm → 1:42.8 | 36 segments + final pass | **101 s**; duration = time map (102.83 vs 102.833) |
| 2026-10-11 | Workflow A render, 0:30 demo: cut + silence + captions + overlay + zoom → 0:15.5 | UI | 16.2 s |
| 2026-10-11 | same 0:30 demo without silence removal (re-render, plan v2) → 0:25.0 | UI | 25.6 s |

| 2026-10-14 | Workflow B scene render (avatar + insert + captions), 8.5 s scene | 1280×720 / 720×1280, 24 fps, Pillow sprites → ffmpeg stdin | 6.4–9.5 s per scene (≈ 0.75–1.1× real time) |
| 2026-10-14 | Workflow B 1-min run, 27.2 s video, 6 scenes (mocked LLM, real Edge-TTS, synthetic images) | API, 16:9 / 9:16 | 42.6 s / 47.4 s generate |
| 2026-10-14 | Workflow B key-free UI run, 25.7 s video, 3 scenes (real Edge-TTS + real Pollinations) | browser | 105.7 s, mostly Pollinations pacing (~30 s per image on the anonymous tier) |
| 2026-10-14 | Workflow B per-scene "new picture" regenerate | browser | 23.3 s (one scene + final join + pack) |
| 2026-10-14 | Pollinations anonymous tier | 1280×720, flux | 8–31 s per image when requests are ≥ 30 s apart; immediate 402 when they follow each other |

So a 3-minute edit takes about 3 minutes on this laptop (ingest + render), plus STT time. That is within the PRD's ~5 min budget, and Groq STT is untested.

Not measured: Groq Whisper (needs key), LLM plan latency (needs key), anything on Railway, real avatar art.
