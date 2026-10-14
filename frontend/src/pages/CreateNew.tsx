import { useEffect, useRef, useState } from "react";
import { api, uploadFile, type Catalog, type Wizard } from "../api";

const DRAFT_KEY = "aiyt2:wizard-draft";
const DEFAULTS: Wizard = {
  topic: "", notes: "", audience: "", tone: "", language: "hi", aspect: "16:9", minutes: 3, character: "aarav",
  outfit: "blue", background: "study", voice: "hi-IN-SwaraNeural", rate: "normal", layout: "auto",
  caption_style: "hindi_bold_word_highlight", caption_script: "devanagari", music_asset_id: null, music_volume: 0.12,
};
const STEPS = ["टॉपिक", "भाषा", "फ़ॉर्मेट", "अवतार", "आवाज़", "लेआउट", "कैप्शन", "शुरू करें"];
const ASPECT_LABEL: Record<string, string> = { "16:9": "16:9 (YouTube)", "9:16": "9:16 (Shorts / Reels)", "1:1": "1:1 (Instagram / LinkedIn)" };

function loadDraft(): Wizard {
  try {
    const raw = localStorage.getItem(DRAFT_KEY);
    return raw ? { ...DEFAULTS, ...JSON.parse(raw), music_asset_id: null } : DEFAULTS;
  } catch {
    return DEFAULTS;
  }
}

/** Workflow B: the 8-screen setup wizard (PRD §5.1). */
export function CreateNew() {
  const [cat, setCat] = useState<Catalog | null>(null);
  const [w, setW] = useState<Wizard>(loadDraft);
  const [step, setStep] = useState(0);
  const [music, setMusic] = useState<File | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement>(null);

  useEffect(() => {
    api<Catalog>("/api/create/catalog").then(setCat).catch((e) => setError(e.message));
  }, []);
  useEffect(() => {
    try { localStorage.setItem(DRAFT_KEY, JSON.stringify(w)); } catch { /* private mode */ }
  }, [w]);

  const set = <K extends keyof Wizard>(k: K, v: Wizard[K]) => setW((x) => ({ ...x, [k]: v }));
  const char = cat?.characters.find((c) => c.id === w.character);

  function preview() {
    const a = audioRef.current;
    if (!a) return;
    a.src = `/api/create/voice-preview?${new URLSearchParams({ voice: w.voice, rate: w.rate })}`;
    a.play().catch(() => setError("आवाज़ नहीं चल सकी — इंटरनेट जाँचें (Edge-TTS ऑनलाइन है)।"));
  }

  async function start() {
    setError(null);
    setBusy("project");
    try {
      const p = await api<{ id: string }>("/api/projects", { body: { kind: "create", title: w.topic } });
      let wiz = { ...w };
      if (music) {
        setBusy("music");
        const q = new URLSearchParams({ kind: "music", name: music.name });
        const r = await uploadFile(`/api/projects/${p.id}/upload?${q}`, music, () => {});
        wiz = { ...wiz, music_asset_id: r.asset.id };
      }
      await api(`/api/projects/${p.id}/settings`, { method: "PUT", body: { wizard: wiz } });
      try { localStorage.removeItem(DRAFT_KEY); } catch { /* ignore */ }
      window.location.hash = `#/create/${p.id}`;
    } catch (e: any) {
      setError(e.message);
      setBusy(null);
    }
  }

  if (!cat) return error ? <div className="msg error">{error}</div> : <p className="muted">लोड हो रहा है…</p>;
  const canNext = step !== 0 || w.topic.trim().length > 1;

  return (
    <div>
      <a className="small" href="#/">← होम</a>
      <h1>टॉपिक से वीडियो बनाओ</h1>
      <ol className="stepper" aria-label="कदम">
        {STEPS.map((s, i) => (
          <li key={s} className={i === step ? "on" : i < step ? "done" : ""}>
            <button className="link" onClick={() => (i < step || canNext) && setStep(i)} aria-current={i === step ? "step" : undefined}>
              {i + 1}. {s}
            </button>
          </li>
        ))}
      </ol>

      <section className="card">
        {step === 0 && (
          <>
            <h2>1. किस बारे में वीडियो?</h2>
            <Field id="topic" label="टॉपिक">
              <input id="topic" className="input" value={w.topic} maxLength={300} placeholder="जैसे: रायगढ़ किले का इतिहास"
                     onChange={(e) => set("topic", e.target.value)} autoFocus />
            </Field>
            <Field id="notes" label="आपके नोट्स (वैकल्पिक) — तथ्य, अपनी राय, ज़रूरी बातें">
              <textarea id="notes" className="input" rows={4} maxLength={4000} value={w.notes} onChange={(e) => set("notes", e.target.value)} />
            </Field>
            <div className="row">
              <Field id="aud" label="दर्शक (वैकल्पिक)" grow>
                <input id="aud" className="input" value={w.audience} maxLength={200} placeholder="जैसे: कक्षा 8 के छात्र"
                       onChange={(e) => set("audience", e.target.value)} />
              </Field>
              <Field id="tone" label="अंदाज़ (वैकल्पिक)" grow>
                <input id="tone" className="input" value={w.tone} maxLength={100} placeholder="जैसे: कहानी जैसा, मज़ेदार"
                       onChange={(e) => set("tone", e.target.value)} />
              </Field>
            </div>
          </>
        )}

        {step === 1 && (
          <>
            <h2>2. भाषा</h2>
            <Choices name="lang" value={w.language} options={cat.languages} onChange={(v) => set("language", v)} />
            <p className="small muted">दोनों में स्क्रिप्ट देवनागरी में लिखी जाती है ताकि हिंदी आवाज़ सही उच्चारण करे। Hinglish में अंग्रेज़ी शब्द भी देवनागरी में होंगे (जैसे "टेक्नोलॉजी")।</p>
          </>
        )}

        {step === 2 && (
          <>
            <h2>3. फ़ॉर्मेट और लंबाई</h2>
            <Choices name="aspect" value={w.aspect} options={cat.aspects.map((a) => ({ id: a, label: ASPECT_LABEL[a] || a }))}
                     onChange={(v) => set("aspect", v)} />
            <h3>लंबाई</h3>
            <Choices name="min" value={String(w.minutes)} options={cat.minutes.map((m) => ({ id: String(m), label: `${m} मिनट` }))}
                     onChange={(v) => set("minutes", Number(v))} inline />
          </>
        )}

        {step === 3 && (
          <>
            <h2>4. अवतार</h2>
            <div className="pickgrid">
              {cat.characters.map((c) => (
                <button key={c.id} className={"pick" + (w.character === c.id ? " on" : "")} aria-pressed={w.character === c.id}
                        onClick={() => setW((x) => ({ ...x, character: c.id, outfit: c.outfits.some((o) => o.id === x.outfit) ? x.outfit : c.outfits[0].id }))}>
                  <img src={`/api/create/catalog/file/${c.preview}`} alt="" loading="lazy" />
                  <b>{c.label}</b>
                  <span className="small muted">{c.description}</span>
                </button>
              ))}
            </div>
            <h3>कपड़ों का रंग</h3>
            <div className="row">
              {char?.outfits.map((o) => (
                <button key={o.id} className={"swatch" + (w.outfit === o.id ? " on" : "")} aria-pressed={w.outfit === o.id}
                        onClick={() => set("outfit", o.id)}>
                  <span style={{ background: `rgb(${o.color.join(",")})` }} />{o.label}
                </button>
              ))}
            </div>
            <h3>पृष्ठभूमि</h3>
            <div className="pickgrid wide">
              {cat.backgrounds.map((b) => (
                <button key={b.id} className={"pick" + (w.background === b.id ? " on" : "")} aria-pressed={w.background === b.id}
                        onClick={() => set("background", b.id)}>
                  <img src={`/api/create/catalog/file/${b.preview}`} alt="" loading="lazy" />
                  <b>{b.label}</b>
                </button>
              ))}
            </div>
          </>
        )}

        {step === 4 && (
          <>
            <h2>5. आवाज़</h2>
            <label className="small muted" htmlFor="tts">Provider</label>
            <select id="tts" className="input" value="edge_tts" disabled>
              <option value="edge_tts">Edge-TTS — Free (Premium आवाज़ें जल्द)</option>
            </select>
            <h3>आवाज़ चुनें</h3>
            <Choices name="voice" value={w.voice} options={cat.voices} onChange={(v) => set("voice", v)} />
            <h3>रफ़्तार</h3>
            <Choices name="rate" value={w.rate} options={cat.rates} onChange={(v) => set("rate", v)} inline />
            <button className="btn" onClick={preview}>▶ आवाज़ सुनें</button>
            <audio ref={audioRef} preload="none" />
          </>
        )}

        {step === 5 && (
          <>
            <h2>6. लेआउट</h2>
            <Choices name="layout" value={w.layout} options={cat.layouts} onChange={(v) => set("layout", v)} />
          </>
        )}

        {step === 6 && (
          <>
            <h2>7. कैप्शन</h2>
            <Choices name="cs" value={w.caption_style} options={cat.caption_styles} onChange={(v) => set("caption_style", v)} />
            {w.caption_style !== "none" && (
              <>
                <h3>लिपि</h3>
                <Choices name="script" value={w.caption_script} options={cat.caption_scripts} onChange={(v) => set("caption_script", v)} />
              </>
            )}
          </>
        )}

        {step === 7 && (
          <>
            <h2>8. जाँचें और शुरू करें</h2>
            <dl className="summary">
              <dt>टॉपिक</dt><dd>{w.topic || <span className="warn">ख़ाली</span>}</dd>
              <dt>भाषा</dt><dd>{cat.languages.find((l) => l.id === w.language)?.label}</dd>
              <dt>फ़ॉर्मेट</dt><dd>{ASPECT_LABEL[w.aspect]} · {w.minutes} मिनट</dd>
              <dt>अवतार</dt><dd>{char?.label} · {char?.outfits.find((o) => o.id === w.outfit)?.label} · {cat.backgrounds.find((b) => b.id === w.background)?.label}</dd>
              <dt>आवाज़</dt><dd>{cat.voices.find((v) => v.id === w.voice)?.label} · {cat.rates.find((r) => r.id === w.rate)?.label}</dd>
              <dt>लेआउट</dt><dd>{cat.layouts.find((l) => l.id === w.layout)?.label}</dd>
              <dt>कैप्शन</dt><dd>{cat.caption_styles.find((c) => c.id === w.caption_style)?.label}{w.caption_style !== "none" ? ` · ${cat.caption_scripts.find((c) => c.id === w.caption_script)?.label}` : ""}</dd>
            </dl>
            <Field id="music" label="बैकग्राउंड म्यूज़िक (वैकल्पिक, अपनी फ़ाइल — आवाज़ के नीचे अपने-आप धीमा होगा)">
              <input id="music" className="input" type="file" accept="audio/*,.mp3,.m4a,.wav,.ogg,.flac,.aac"
                     onChange={(e) => setMusic(e.target.files?.[0] || null)} />
            </Field>
            {music && (
              <div className="row">
                <label htmlFor="mv" className="small">म्यूज़िक की आवाज़</label>
                <input id="mv" type="range" min={0.03} max={0.4} step={0.01} value={w.music_volume}
                       onChange={(e) => set("music_volume", Number(e.target.value))} />
              </div>
            )}
            <button className="btn primary full" disabled={!w.topic.trim() || !!busy} onClick={start}>
              {busy === "music" ? "म्यूज़िक अपलोड हो रहा है…" : busy ? "बन रहा है…" : "प्रोजेक्ट शुरू करो"}
            </button>
          </>
        )}

        {error && <div className="msg error" role="alert">{error}</div>}
        <div className="row navrow">
          <button className="btn" disabled={step === 0} onClick={() => setStep((s) => s - 1)}>← पीछे</button>
          {step < STEPS.length - 1 && (
            <button className="btn primary" disabled={!canNext} onClick={() => setStep((s) => s + 1)}>आगे →</button>
          )}
        </div>
      </section>
    </div>
  );
}

function Field({ id, label, children, grow }: { id: string; label: string; children: React.ReactNode; grow?: boolean }) {
  return (
    <div className="field" style={grow ? { flex: "1 1 200px" } : undefined}>
      <label htmlFor={id} className="small">{label}</label>
      {children}
    </div>
  );
}

export function Choices({ name, value, options, onChange, inline }: {
  name: string; value: string; options: { id: string; label: string }[]; onChange: (v: string) => void; inline?: boolean;
}) {
  return (
    <div className={"choices" + (inline ? " inline" : "")} role="radiogroup">
      {options.map((o) => (
        <label key={o.id} className={"choice" + (value === o.id ? " on" : "")}>
          <input type="radio" name={name} value={o.id} checked={value === o.id} onChange={() => onChange(o.id)} />
          <span>{o.label}</span>
        </label>
      ))}
    </div>
  );
}
