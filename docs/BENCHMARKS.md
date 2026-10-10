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

Not measured: Groq Whisper (needs key), anything on Railway, real avatar art.
