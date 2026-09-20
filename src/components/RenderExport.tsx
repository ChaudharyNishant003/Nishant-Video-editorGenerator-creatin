import { useEffect, useState } from "react";
import { useStore } from "../store";
import { IconVideo, IconDownload } from "../icons";

type Backend = "checking" | "online" | "offline";

// Turns a blob:/data: image into a data URI the backend can decode; remote URLs
// are passed through unchanged (the backend fetches them server-side).
async function resolveImage(url: string | undefined): Promise<string | null> {
  if (!url) return null;
  if (url.startsWith("http")) return url;
  if (url.startsWith("data:")) return url;
  if (url.startsWith("blob:")) {
    const blob = await fetch(url).then((r) => r.blob());
    return await new Promise<string>((resolve) => {
      const fr = new FileReader();
      fr.onload = () => resolve(fr.result as string);
      fr.readAsDataURL(blob);
    });
  }
  return url;
}

export function RenderExport() {
  const scenes = useStore((s) => s.runtime["visuals"]?.scenes) || [];
  const images = useStore((s) => s.runtime["images"]?.images) || {};
  const dimensions = useStore((s) => s.inputs.dimensions);

  const [backend, setBackend] = useState<Backend>("checking");
  const [voice, setVoice] = useState("en-US-AriaNeural");
  const [rendering, setRendering] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resultUrl, setResultUrl] = useState<string | null>(null);

  async function checkBackend() {
    setBackend("checking");
    try {
      const r = await fetch("/render/health");
      setBackend(r.ok ? "online" : "offline");
    } catch {
      setBackend("offline");
    }
  }

  useEffect(() => {
    checkBackend();
  }, []);

  async function exportMp4() {
    setError(null);
    setResultUrl(null);
    setRendering(true);
    try {
      const payloadScenes = await Promise.all(
        scenes.map(async (s) => ({
          scene: s.scene,
          narration: s.narration,
          onScreenText: s.onScreenText,
          image: await resolveImage(images[s.scene]),
        })),
      );
      const res = await fetch("/render/video", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ dimensions, voice, fps: 24, scenes: payloadScenes }),
      });
      if (!res.ok) {
        const txt = await res.text();
        throw new Error(`${res.status} — ${txt.slice(0, 300)}`);
      }
      const blob = await res.blob();
      setResultUrl(URL.createObjectURL(blob));
    } catch (e: any) {
      setError(e?.message || String(e));
    } finally {
      setRendering(false);
    }
  }

  const canExport = backend === "online" && scenes.length > 0 && !rendering;

  return (
    <div className="card" style={{ marginTop: 18 }}>
      <h3>Export real .mp4 — Phase 2 backend</h3>

      <div className="row" style={{ marginBottom: 12 }}>
        <span className={"badge " + (backend === "online" ? "free" : "paid")}>
          {backend === "checking" ? "checking…" : backend === "online" ? "backend online" : "backend offline"}
        </span>
        <button className="btn sm ghost" onClick={checkBackend}>
          Re-check
        </button>
        <div className="field" style={{ minWidth: 220 }}>
          <label>Edge-TTS voice</label>
          <input className="input" value={voice} onChange={(e) => setVoice(e.target.value)} spellCheck={false} />
        </div>
      </div>

      {backend === "offline" && (
        <div className="notice" style={{ marginBottom: 12 }}>
          The render backend isn’t running. Start it once, then click <b>Re-check</b>:
          <div className="output mono" style={{ marginTop: 8 }}>
            cd backend{"\n"}
            python -m venv .venv{"\n"}
            .venv\Scripts\activate{"\n"}
            pip install -r requirements.txt{"\n"}
            uvicorn main:app --port 8000
          </div>
        </div>
      )}

      <div className="row">
        <button className="btn primary" disabled={!canExport} onClick={exportMp4}>
          <IconVideo size={15} /> {rendering ? "Rendering…" : "Render .mp4 (images + narration)"}
        </button>
        {rendering && (
          <span className="pill">Edge-TTS + ffmpeg — a 6–10 scene video takes ~30–90s.</span>
        )}
        {scenes.length === 0 && <span className="pill">Run the Visual Director first.</span>}
      </div>

      {error && <div className="error-box">{error}</div>}

      {resultUrl && (
        <div style={{ marginTop: 16 }}>
          <video controls src={resultUrl} style={{ width: "100%", borderRadius: 12, background: "#000" }} />
          <div className="row" style={{ marginTop: 10 }}>
            <a className="btn sm" href={resultUrl} download="ai-yt-studio.mp4">
              <IconDownload size={14} /> Download .mp4
            </a>
          </div>
        </div>
      )}

      <div className="notice" style={{ marginTop: 14 }}>
        This renders each scene’s <b>image + burned-in caption</b>, timed to its <b>Edge-TTS narration</b>, into one
        video. Stitching the generated <b>video clips</b> (stage 5) and Ken-Burns motion are the next backend
        enhancement.
      </div>
    </div>
  );
}
