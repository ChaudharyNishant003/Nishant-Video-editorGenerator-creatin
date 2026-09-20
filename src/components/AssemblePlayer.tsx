import { useEffect, useRef, useState } from "react";
import { useStore } from "../store";
import { IconPlay, IconStop } from "../icons";

// Storyboard preview: advances scene images on a timer synced to the total
// duration, showing on-screen captions, and plays the generated voiceover.
export function AssemblePlayer() {
  const scenes = useStore((s) => s.runtime["visuals"]?.scenes) || [];
  const images = useStore((s) => s.runtime["images"]?.images) || {};
  const videos = useStore((s) => s.runtime["video"]?.videos) || {};
  const audioUrl = useStore((s) => s.runtime["voiceover"]?.audioUrl);
  const dimensions = useStore((s) => s.inputs.dimensions);

  const [playing, setPlaying] = useState(false);
  const [idx, setIdx] = useState(0);
  const [progress, setProgress] = useState(0);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const timerRef = useRef<number | null>(null);

  const ratioClass = dimensions === "9:16" ? "r916" : dimensions === "1:1" ? "r11" : "";

  useEffect(() => () => stop(), []); // cleanup on unmount

  function stop() {
    setPlaying(false);
    if (timerRef.current) window.clearInterval(timerRef.current);
    timerRef.current = null;
    if (audioRef.current) {
      audioRef.current.pause();
      audioRef.current.currentTime = 0;
    }
    setProgress(0);
    setIdx(0);
  }

  function play() {
    if (scenes.length === 0) return;
    setPlaying(true);
    setIdx(0);
    setProgress(0);

    // Total run time (seconds): use the audio length if known, else ~4.5s/scene.
    const audioEl = audioRef.current;
    const totalSec =
      audioEl && audioEl.duration && isFinite(audioEl.duration) ? audioEl.duration : scenes.length * 4.5;
    const totalMs = totalSec * 1000;
    const perMs = totalMs / scenes.length;

    if (audioEl && audioUrl) {
      audioEl.currentTime = 0;
      audioEl.play().catch(() => {});
    }

    const start = Date.now();
    timerRef.current = window.setInterval(() => {
      const elapsed = Date.now() - start;
      setIdx(Math.min(scenes.length - 1, Math.floor(elapsed / perMs)));
      setProgress(Math.min(100, (elapsed / totalMs) * 100));
      if (elapsed >= totalMs) stop();
    }, 120);
  }

  if (scenes.length === 0) {
    return <div className="empty">Run the Visual Director (and ideally Image Generation) to build a storyboard.</div>;
  }

  const current = scenes[idx];
  const currentImg = images[current?.scene];
  const currentVid = videos[current?.scene];

  return (
    <div>
      <div className="player">
        <div className={"scene-thumb " + ratioClass} style={{ aspectRatio: undefined }}>
          {currentVid ? (
            <video key={current?.scene} className="stage-img" src={currentVid} autoPlay loop muted playsInline />
          ) : currentImg ? (
            <img className="stage-img" src={currentImg} alt={`Scene ${current.scene}`} />
          ) : (
            <div style={{ padding: 40, color: "#6b7488" }}>Scene {current?.scene} — no media yet</div>
          )}
        </div>
        {current?.onScreenText ? <div className="caption">{current.onScreenText}</div> : null}
        <div className="bar" style={{ width: `${Math.min(100, progress)}%` }} />
      </div>

      {audioUrl && <audio ref={audioRef} src={audioUrl} preload="auto" style={{ display: "none" }} />}

      <div className="row" style={{ marginTop: 14 }}>
        {playing ? (
          <button className="btn danger" onClick={stop}>
            <IconStop size={15} /> Stop
          </button>
        ) : (
          <button className="btn primary" onClick={play}>
            <IconPlay size={15} /> Play storyboard
          </button>
        )}
        <span className="pill">
          Scene {current?.scene} / {scenes.length}
        </span>
        <span className="pill">{current?.time}</span>
        {!audioUrl && <span className="pill">No voiceover yet — run the Voiceover stage</span>}
      </div>

      <div className="notice" style={{ marginTop: 16 }}>
        This is a synced <b>storyboard preview</b>. True frame-accurate <b>.mp4 export</b> (Ken Burns motion,
        per-scene timing, Edge-TTS narration, MoviePy/ffmpeg stitching) is the <b>Phase-2 backend</b> — it plugs into
        this stage via <code>/render</code>.
      </div>
    </div>
  );
}
