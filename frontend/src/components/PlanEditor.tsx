import { useEffect, useState } from "react";
import { fmtTime, parseTime, type Asset, type PlanOp } from "../api";

const LABEL: Record<string, string> = {
  cut: "✂ कट (हिस्सा हटाओ)", remove_silence: "🤫 खामोशी हटाओ", captions: "💬 कैप्शन", text_overlay: "🔤 टेक्स्ट",
  zoom: "🔍 ज़ूम", speed: "⏩ स्पीड", music: "🎵 म्यूज़िक", broll: "🎞 B-roll", audio_cleanup: "🎚 ऑडियो सफ़ाई",
};
const RANGED = ["cut", "text_overlay", "zoom", "speed", "broll"];
const POSITIONS: [string, string][] = [["bottom_center", "नीचे बीच"], ["top_center", "ऊपर बीच"], ["center", "बीच में"],
  ["top_left", "ऊपर बाएँ"], ["top_right", "ऊपर दाएँ"], ["bottom_left", "नीचे बाएँ"], ["bottom_right", "नीचे दाएँ"]];
const OVERLAY_STYLES: [string, string][] = [["bold_yellow", "पीला बोल्ड"], ["white_box", "सफ़ेद पट्टी"], ["red_bold", "लाल बोल्ड"], ["plain_white", "सादा सफ़ेद"]];
const FOCUS: [string, string][] = [["center", "बीच"], ["left", "बाएँ"], ["right", "दाएँ"], ["top", "ऊपर"], ["bottom", "नीचे"]];

function defaults(type: string, t: number, duration: number, uploads: Asset[]): PlanOp {
  const start = Math.min(Math.max(0, t), Math.max(0, duration - 1));
  const end = Math.min(duration, start + 3);
  switch (type) {
    case "cut": return { type, start, end };
    case "remove_silence": return { type, min_silence_ms: 600, threshold_db: -35 };
    case "captions": return { type, style: "hindi_bold_word_highlight" };
    case "text_overlay": return { type, start, end, text: "", position: "bottom_center", style: "bold_yellow" };
    case "zoom": return { type, start, end, scale: 1.3, focus: "center" };
    case "speed": return { type, start, end, factor: 1.5 };
    case "music": {
      const m = uploads.find((u) => u.kind === "music");
      return { type, track: m ? `upload:${m.id}` : "", volume: 0.15, duck: true };
    }
    case "broll": return { type, start, end, source: "stock:", mode: "overlay" };
    default: return { type, denoise: true, loudnorm: true };
  }
}

function TimeField({ label, value, onChange, videoRef, disabled }: {
  label: string; value: number; onChange: (v: number) => void;
  videoRef: React.RefObject<HTMLVideoElement>; disabled?: boolean;
}) {
  const [text, setText] = useState(fmtTime(value));
  useEffect(() => setText(fmtTime(value)), [value]);
  return (
    <div className="tfield">
      <span className="small muted">{label}</span>
      <div className="trow">
        <input className="input" inputMode="decimal" value={text} disabled={disabled} aria-label={label}
               onChange={(e) => setText(e.target.value)}
               onBlur={() => { const v = parseTime(text); if (v == null) setText(fmtTime(value)); else onChange(Math.round(v * 100) / 100); }} />
        <button className="btn icon" type="button" disabled={disabled} title="वीडियो का अभी का समय"
                aria-label={`${label}: वीडियो का अभी का समय`}
                onClick={() => videoRef.current && onChange(Math.round(videoRef.current.currentTime * 100) / 100)}>⏱</button>
      </div>
    </div>
  );
}

function Select({ label, value, options, onChange, disabled }: {
  label: string; value: string; options: [string, string][]; onChange: (v: string) => void; disabled?: boolean;
}) {
  return (
    <label className="tfield">
      <span className="small muted">{label}</span>
      <select className="input" value={value} disabled={disabled} onChange={(e) => onChange(e.target.value)}>
        {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
      </select>
    </label>
  );
}

function Num({ label, value, min, max, step, onChange, disabled }: {
  label: string; value: number; min: number; max: number; step: number; onChange: (v: number) => void; disabled?: boolean;
}) {
  return (
    <label className="tfield">
      <span className="small muted">{label}</span>
      <input className="input" type="number" value={value} min={min} max={max} step={step} disabled={disabled}
             onChange={(e) => e.target.value !== "" && onChange(Number(e.target.value))} />
    </label>
  );
}

function Check({ label, value, onChange, disabled }: { label: string; value: boolean; onChange: (v: boolean) => void; disabled?: boolean }) {
  return (
    <label className="check">
      <input type="checkbox" checked={value} disabled={disabled} onChange={(e) => onChange(e.target.checked)} /> {label}
    </label>
  );
}

/** Editable list of plan operations (PRD §4.1 step 4). Times are on the ORIGINAL video timeline. */
export function PlanEditor({ ops, duration, uploads, videoRef, onChange, onUpload, disabled }: {
  ops: PlanOp[]; duration: number; uploads: Asset[]; videoRef: React.RefObject<HTMLVideoElement>;
  onChange: (ops: PlanOp[]) => void; onUpload: (kind: "music" | "broll", f: File) => void; disabled?: boolean;
}) {
  const [newType, setNewType] = useState("cut");
  const set = (i: number, patch: Partial<PlanOp>) => onChange(ops.map((o, j) => (j === i ? { ...o, ...patch } : o)));
  const music = uploads.filter((u) => u.kind === "music");
  const broll = uploads.filter((u) => u.kind === "broll");

  return (
    <div className="plan">
      <h3 className="small">प्लान ({ops.length} बदलाव) — सारे समय असली वीडियो के हिसाब से</h3>
      {ops.length === 0 && <p className="small muted">अभी कोई बदलाव नहीं। AI से बनवाओ या नीचे से जोड़ो।</p>}
      <ol className="ops">
        {ops.map((op, i) => (
          <li key={op.id || i} className="op">
            <div className="ophead">
              <strong>{LABEL[op.type] || op.type}</strong>
              {op.proposed_by_ai && <span className="tag ai" title="AI ने transcript से अंदाज़ा लगाया — जाँच लें">AI सुझाव</span>}
              <button className="btn danger icon" disabled={disabled} aria-label="यह बदलाव हटाओ"
                      onClick={() => onChange(ops.filter((_, j) => j !== i))}>✕</button>
            </div>
            <div className="opfields">
              {RANGED.includes(op.type) && (
                <>
                  <TimeField label="शुरू" value={op.start ?? 0} videoRef={videoRef} disabled={disabled} onChange={(v) => set(i, { start: v })} />
                  <TimeField label="अंत" value={op.end ?? 0} videoRef={videoRef} disabled={disabled} onChange={(v) => set(i, { end: v })} />
                </>
              )}
              {op.type === "text_overlay" && (
                <>
                  <label className="tfield wide">
                    <span className="small muted">टेक्स्ट</span>
                    <input className="input" value={op.text || ""} maxLength={160} disabled={disabled} onChange={(e) => set(i, { text: e.target.value })} />
                  </label>
                  <Select label="जगह" value={op.position || "bottom_center"} options={POSITIONS} disabled={disabled} onChange={(v) => set(i, { position: v })} />
                  <Select label="स्टाइल" value={op.style || "bold_yellow"} options={OVERLAY_STYLES} disabled={disabled} onChange={(v) => set(i, { style: v })} />
                </>
              )}
              {op.type === "zoom" && (
                <>
                  <Num label="ज़ूम (1.1–2)" value={op.scale ?? 1.3} min={1.1} max={2} step={0.1} disabled={disabled} onChange={(v) => set(i, { scale: v })} />
                  <Select label="किस ओर" value={op.focus || "center"} options={FOCUS} disabled={disabled} onChange={(v) => set(i, { focus: v })} />
                </>
              )}
              {op.type === "speed" && (
                <Num label="गति (0.5–2×)" value={op.factor ?? 1.5} min={0.5} max={2} step={0.25} disabled={disabled} onChange={(v) => set(i, { factor: v })} />
              )}
              {op.type === "remove_silence" && (
                <>
                  <Num label="कम से कम (ms)" value={op.min_silence_ms ?? 600} min={200} max={5000} step={100} disabled={disabled} onChange={(v) => set(i, { min_silence_ms: v })} />
                  <Num label="सीमा (dB)" value={op.threshold_db ?? -35} min={-70} max={-10} step={1} disabled={disabled} onChange={(v) => set(i, { threshold_db: v })} />
                </>
              )}
              {op.type === "captions" && (
                <Select label="स्टाइल" value={op.style || "hindi_bold_word_highlight"} disabled={disabled}
                        options={[["hindi_bold_word_highlight", "शब्द-दर-शब्द हाइलाइट"], ["line", "पूरी लाइन"]]} onChange={(v) => set(i, { style: v })} />
              )}
              {op.type === "music" && (
                <>
                  <Select label="गाना" value={op.track || ""} disabled={disabled}
                          options={[["", music.length ? "चुनो…" : "पहले फ़ाइल जोड़ो"], ...music.map((m) => [`upload:${m.id}`, m.name || m.id] as [string, string])]}
                          onChange={(v) => set(i, { track: v })} />
                  <Num label="आवाज़ (0–1)" value={op.volume ?? 0.15} min={0} max={1} step={0.05} disabled={disabled} onChange={(v) => set(i, { volume: v })} />
                  <Check label="बोलते समय धीमा करो" value={op.duck ?? true} disabled={disabled} onChange={(v) => set(i, { duck: v })} />
                  <FilePick label="+ म्यूज़िक फ़ाइल" accept="audio/*,.mp3,.m4a,.wav,.ogg,.flac,.aac" disabled={disabled} onPick={(f) => onUpload("music", f)} />
                </>
              )}
              {op.type === "broll" && (
                <>
                  <Select label="स्रोत" value={String(op.source || "").startsWith("upload:") ? op.source : "stock"} disabled={disabled}
                          options={[["stock", "स्टॉक वीडियो खोजो (Pexels/Pixabay)"], ...broll.map((b) => [`upload:${b.id}`, b.name || b.id] as [string, string])]}
                          onChange={(v) => set(i, { source: v === "stock" ? "stock:" : v })} />
                  {!String(op.source || "").startsWith("upload:") && (
                    <label className="tfield wide">
                      <span className="small muted">क्या खोजें (English में बेहतर)</span>
                      <input className="input" value={String(op.source || "").replace(/^stock:/, "")} disabled={disabled}
                             placeholder="city traffic" onChange={(e) => set(i, { source: "stock:" + e.target.value })} />
                    </label>
                  )}
                  <Select label="कैसे" value={op.mode || "overlay"} disabled={disabled}
                          options={[["overlay", "कोने में छोटा"], ["replace", "पूरी स्क्रीन"]]} onChange={(v) => set(i, { mode: v })} />
                  <FilePick label="+ अपनी फ़ाइल" accept="video/*,image/*" disabled={disabled} onPick={(f) => onUpload("broll", f)} />
                </>
              )}
              {op.type === "audio_cleanup" && (
                <>
                  <Check label="शोर कम करो" value={op.denoise ?? true} disabled={disabled} onChange={(v) => set(i, { denoise: v })} />
                  <Check label="आवाज़ बराबर करो (loudnorm)" value={op.loudnorm ?? true} disabled={disabled} onChange={(v) => set(i, { loudnorm: v })} />
                </>
              )}
            </div>
          </li>
        ))}
      </ol>
      <div className="row">
        <select className="input grow-select" value={newType} disabled={disabled} aria-label="नया बदलाव चुनो" onChange={(e) => setNewType(e.target.value)}>
          {Object.entries(LABEL).map(([k, l]) => <option key={k} value={k}>{l}</option>)}
        </select>
        <button className="btn" disabled={disabled}
                onClick={() => onChange([...ops, defaults(newType, videoRef.current?.currentTime || 0, duration, [...uploads])])}>+ जोड़ो</button>
      </div>
    </div>
  );
}

function FilePick({ label, accept, onPick, disabled }: { label: string; accept: string; onPick: (f: File) => void; disabled?: boolean }) {
  return (
    <label className={"btn filepick" + (disabled ? " disabled" : "")}>
      {label}
      <input type="file" accept={accept} disabled={disabled} hidden
             onChange={(e) => { const f = e.target.files?.[0]; if (f) onPick(f); e.target.value = ""; }} />
    </label>
  );
}
