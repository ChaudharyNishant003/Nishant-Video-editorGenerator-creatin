import { useCallback, useEffect, useState } from "react";
import {
  api, fmtTime, followJob,
  type Catalog, type Chapter, type CreateState, type Fact, type JobFull, type Scene, type Script, type Wizard,
} from "../api";
import { JobBox } from "./EditProject";

const RUNNING = ["queued", "running"];
type Kind = "research" | "script" | "generate" | "regenerate" | "pack";
const KINDS: Kind[] = ["research", "script", "generate", "regenerate", "pack"];
const VISUAL_KINDS: [string, string][] = [["ai_image", "AI तस्वीर"], ["stock_video", "स्टॉक वीडियो"], ["stock_image", "स्टॉक फ़ोटो"],
  ["wiki_image", "Wikimedia (असली तस्वीर)"], ["none", "कोई नहीं"]];
const PLATFORM_LABEL: Record<string, string> = { youtube: "YouTube", shorts: "Shorts", instagram: "Instagram", linkedin: "LinkedIn", facebook: "Facebook" };

async function copy(text: string) {
  try { await navigator.clipboard.writeText(text); } catch { /* clipboard blocked — user can select manually */ }
}

/** Workflow B project page: facts → script → generate → result / regenerate / YouTube pack / export. */
export function CreateProject({ id }: { id: string }) {
  const [st, setSt] = useState<CreateState | null>(null);
  const [cat, setCat] = useState<Catalog | null>(null);
  const [live, setLive] = useState<Partial<Record<Kind, JobFull>>>({});
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setSt(await api<CreateState>(`/api/projects/${id}/create-state`));
    } catch (e: any) {
      setError(e.message);
    }
  }, [id]);

  useEffect(() => { load(); api<Catalog>("/api/create/catalog").then(setCat).catch(() => {}); }, [load]);

  const runningIds = KINDS.map((k) => (st?.jobs[k] && RUNNING.includes(st.jobs[k]!.status) ? st.jobs[k]!.id : "")).join(",");
  useEffect(() => {
    if (!st) return;
    const stops: (() => void)[] = [];
    for (const k of KINDS) {
      const j = st.jobs[k];
      if (j && RUNNING.includes(j.status)) {
        stops.push(followJob(j.id, (u) => {
          setLive((l) => ({ ...l, [k]: u as JobFull }));
          if (!RUNNING.includes(u.status)) load();
        }));
      }
    }
    return () => stops.forEach((s) => s());
  }, [runningIds, load]);

  const job = (k: Kind): JobFull | null => {
    const base = st?.jobs[k] || null;
    const l = live[k];
    return l && base && l.id === base.id ? { ...base, ...l } : base;
  };

  async function call(path: string, opts: { method?: string; body?: unknown; keys?: "all" } = {}) {
    setError(null);
    try {
      await api(path, { method: opts.method || "POST", body: opts.body ?? {}, keys: opts.keys });
      await load();
      return true;
    } catch (e: any) {
      setError(e.message);
      return false;
    }
  }

  if (error && !st) return <div className="msg error">{error}</div>;
  if (!st) return <p className="muted">लोड हो रहा है…</p>;

  const busy = KINDS.some((k) => { const j = job(k); return !!j && RUNNING.includes(j.status); });
  const genJob = [job("generate"), job("regenerate"), job("pack")].filter(Boolean)
    .sort((a, b) => (b!.created_at || 0) - (a!.created_at || 0))[0] || null;
  const out = st.outputs[0];

  return (
    <div>
      <a className="small" href="#/">← होम</a>
      <h1>{st.project.title}</h1>
      {error && <div className="msg error" role="alert">{error}</div>}

      <SettingsCard st={st} cat={cat} busy={busy} onSaved={load} />

      <FactsCard st={st} job={job("research")} busy={busy} call={call} />

      <ScriptCard st={st} job={job("script")} busy={busy} call={call} reload={load} />

      {st.script && st.script_complete && (
        <section className="card" id="generate">
          <h2>3. वीडियो बनाओ</h2>
          <p className="small muted">आवाज़ → तस्वीरें → अवतार + सीन → जोड़ना → YouTube पैक। बदले हुए सीन ही दोबारा बनते हैं।</p>
          <div className="row">
            <button className="btn primary" disabled={busy} onClick={() => call(`/api/projects/${id}/generate`, { keys: "all" })}>
              {out ? "बदलाव के साथ फिर बनाओ" : "वीडियो बनाओ"}
            </button>
            {out && (
              <button className="btn" disabled={busy} onClick={() => window.confirm("सारी आवाज़ें/सीन फिर से बनें? (धीमा)") &&
                call(`/api/projects/${id}/generate`, { body: { fresh: true }, keys: "all" })}>पूरा नया बनाओ</button>
            )}
          </div>
          {genJob && RUNNING.includes(genJob.status) && <JobBox job={genJob} title="वीडियो बन रहा है…" cancellable />}
          {genJob?.status === "failed" && <div className="msg error" role="alert">विफल: {genJob.error}<div className="small">फिर से दबाने पर जहाँ रुका था वहीं से आगे बढ़ेगा।</div></div>}
          {genJob?.status === "cancelled" && <div className="msg info">रोका गया — फिर से दबाने पर बचा हुआ काम आगे बढ़ेगा।</div>}
        </section>
      )}

      {out && (
        <section className="card" id="result">
          <h2>4. नतीजा</h2>
          <video className={"player" + (out.meta.aspect === "9:16" ? " tall" : "")} src={out.url} controls playsInline preload="metadata" />
          <div className="small muted">{fmtTime(out.duration_s)} · {out.meta.aspect} · {out.meta.width}×{out.meta.height}</div>
          {st.notices.length > 0 && <ul className="warnlist">{st.notices.map((n, i) => <li key={i}>{n}</li>)}</ul>}
          {out.attribution && <div className="small muted">श्रेय: {out.attribution}</div>}
          <SceneList st={st} busy={busy} call={call} />
        </section>
      )}

      {out && st.meta && <PackCard st={st} busy={busy} call={call} />}
      {out && <ExportCard st={st} call={call} />}
    </div>
  );
}

// --- settings (edit after creation) -----------------------------------------------------------------
function SettingsCard({ st, cat, busy, onSaved }: { st: CreateState; cat: Catalog | null; busy: boolean; onSaved: () => Promise<void> }) {
  const [w, setW] = useState<Wizard>(st.wizard);
  const [err, setErr] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  useEffect(() => setW(st.wizard), [JSON.stringify(st.wizard)]);
  if (!cat) return null;
  const char = cat.characters.find((c) => c.id === w.character);
  const dirty = JSON.stringify(w) !== JSON.stringify(st.wizard);
  const sel = (k: keyof Wizard, opts: { id: string; label: string }[], label: string) => (
    <label className="tfield"><span className="small muted">{label}</span>
      <select className="input" value={String(w[k] ?? "")} disabled={busy}
              onChange={(e) => setW((x) => ({ ...x, [k]: k === "minutes" ? Number(e.target.value) : e.target.value }))}>
        {opts.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}
      </select>
    </label>
  );
  async function save() {
    setErr(null);
    try {
      const fixOutfit = char && !char.outfits.some((o) => o.id === w.outfit) ? { outfit: char.outfits[0].id } : {};
      await api(`/api/projects/${st.project.id}/settings`, { method: "PUT", body: { wizard: { ...w, ...fixOutfit } } });
      setSaved(true);
      window.setTimeout(() => setSaved(false), 2000);
      await onSaved();
    } catch (e: any) { setErr(e.message); }
  }
  return (
    <details className="card">
      <summary><b>सेटिंग</b> <span className="small muted">· {w.aspect} · {w.minutes} मिनट · {char?.label} · {cat.layouts.find((l) => l.id === w.layout)?.label}</span></summary>
      <div className="opfields">
        {sel("aspect", cat.aspects.map((a) => ({ id: a, label: a })), "फ़ॉर्मेट")}
        {sel("minutes", cat.minutes.map((m) => ({ id: String(m), label: `${m} मिनट` })), "लंबाई (स्क्रिप्ट के लिए)")}
        {sel("character", cat.characters, "अवतार")}
        {sel("outfit", char?.outfits || [], "कपड़े")}
        {sel("background", cat.backgrounds, "पृष्ठभूमि")}
        {sel("voice", cat.voices, "आवाज़")}
        {sel("rate", cat.rates, "रफ़्तार")}
        {sel("layout", cat.layouts, "लेआउट")}
        {sel("caption_style", cat.caption_styles, "कैप्शन")}
        {sel("caption_script", cat.caption_scripts, "लिपि")}
      </div>
      <div className="row">
        <button className="btn" disabled={!dirty || busy} onClick={save}>सेटिंग सहेजो</button>
        {saved && <span className="small ok">सहेजा गया — "फिर बनाओ" से लागू होगा।</span>}
      </div>
      {err && <div className="msg error">{err}</div>}
    </details>
  );
}

// --- facts --------------------------------------------------------------------------------------------
function FactsCard({ st, job, busy, call }: { st: CreateState; job: JobFull | null; busy: boolean; call: (p: string, o?: any) => Promise<boolean> }) {
  const [facts, setFacts] = useState<Fact[]>(st.facts || []);
  const [dirty, setDirty] = useState(false);
  useEffect(() => { if (!dirty) setFacts(st.facts || []); }, [JSON.stringify(st.facts)]);
  const pid = st.project.id;
  const edit = (i: number, patch: Partial<Fact>) => { setFacts((f) => f.map((x, j) => (j === i ? { ...x, ...patch } : x))); setDirty(true); };
  const running = !!job && RUNNING.includes(job.status);
  return (
    <section className="card">
      <h2>1. तथ्य (research)</h2>
      <p className="small muted">Wikipedia (हिंदी + English) और आपके नोट्स से तथ्य, हर एक के स्रोत के साथ। स्क्रिप्ट सिर्फ़ इन्हीं पर बनेगी — ज़रूर जाँचें।</p>
      <div className="row">
        <button className="btn primary" disabled={busy} onClick={() => call(`/api/projects/${pid}/research`, { keys: "all" })}>
          {st.facts ? "फिर से research करो" : "AI से research करो"}
        </button>
        {!st.facts && <button className="btn" disabled={busy} onClick={() => call(`/api/projects/${pid}/facts`, { method: "PUT", body: { facts: [] } })}>research छोड़ो</button>}
      </div>
      {running && <JobBox job={job!} title="तथ्य जुटाए जा रहे हैं…" cancellable />}
      {job?.status === "failed" && <div className="msg error" role="alert">{job.error}</div>}
      {st.facts && (
        <>
          {facts.length === 0 && <p className="small muted">कोई तथ्य नहीं — स्क्रिप्ट सामान्य जानकारी पर बनेगी।</p>}
          <ul className="ops">
            {facts.map((f, i) => (
              <li key={i} className={"op" + (f.uncertain ? " uncertain" : "")}>
                <textarea className="input" rows={2} value={f.text} maxLength={500} aria-label={`तथ्य ${i + 1}`}
                          onChange={(e) => edit(i, { text: e.target.value })} />
                <div className="row">
                  <label className="check"><input type="checkbox" checked={f.uncertain} onChange={(e) => edit(i, { uncertain: e.target.checked })} />अनिश्चित</label>
                  {f.source_url && (f.source_url === "notes"
                    ? <span className="small muted">स्रोत: आपके नोट्स</span>
                    : <a className="small" href={f.source_url} target="_blank" rel="noreferrer">स्रोत ↗</a>)}
                  <button className="btn icon danger" aria-label="हटाओ" onClick={() => { setFacts((x) => x.filter((_, j) => j !== i)); setDirty(true); }}>✕</button>
                </div>
              </li>
            ))}
          </ul>
          <div className="row">
            <button className="btn" onClick={() => { setFacts((x) => [...x, { id: "", text: "", source_url: "notes", uncertain: false }]); setDirty(true); }}>+ तथ्य जोड़ो</button>
            <button className="btn" disabled={!dirty || busy} onClick={async () => {
              if (await call(`/api/projects/${pid}/facts`, { method: "PUT", body: { facts: facts.filter((f) => f.text.trim()) } })) setDirty(false);
            }}>तथ्य सहेजो</button>
            {dirty && <span className="small warn">बदलाव सहेजे नहीं गए</span>}
          </div>
          {st.sources.length > 0 && (
            <details><summary className="small muted">{st.sources.length} स्रोत</summary>
              <ul className="small">{st.sources.map((s) => <li key={s.url}><a href={s.url} target="_blank" rel="noreferrer">{s.title}</a> ({s.lang})</li>)}</ul>
            </details>
          )}
        </>
      )}
    </section>
  );
}

// --- script ----------------------------------------------------------------------------------------------
function ScriptCard({ st, job, busy, call, reload }: {
  st: CreateState; job: JobFull | null; busy: boolean; call: (p: string, o?: any) => Promise<boolean>; reload: () => Promise<void>;
}) {
  const [script, setScript] = useState<Script | null>(st.script);
  const [dirty, setDirty] = useState(false);
  const [manual, setManual] = useState(false);
  const [text, setText] = useState("");
  const [keywords, setKeywords] = useState("");
  useEffect(() => { if (!dirty) setScript(st.script); }, [JSON.stringify(st.script)]);
  const pid = st.project.id;
  const running = !!job && RUNNING.includes(job.status);
  const ready = st.facts !== null;

  const setScene = (ci: number, si: number, patch: Partial<Scene>) => {
    setScript((s) => s && { ...s, chapters: s.chapters.map((c, i) => i !== ci ? c : { ...c, scenes: c.scenes.map((x, j) => j === si ? { ...x, ...patch } : x) }) });
    setDirty(true);
  };
  const setChapter = (ci: number, patch: Partial<Chapter>) => {
    setScript((s) => s && { ...s, chapters: s.chapters.map((c, i) => (i === ci ? { ...c, ...patch } : c)) });
    setDirty(true);
  };
  const words = script ? script.chapters.reduce((n, c) => n + c.scenes.reduce((m, s) => m + s.text.split(/\s+/).length, 0), 0) : 0;

  return (
    <section className="card">
      <h2>2. स्क्रिप्ट</h2>
      {!ready && <p className="small muted">पहले तथ्य तैयार करें या research छोड़ें।</p>}
      {ready && (
        <div className="row">
          <button className="btn primary" disabled={busy} onClick={() => call(`/api/projects/${pid}/script`, { body: { fresh: true }, keys: "all" })}>
            {st.script ? "AI से नई स्क्रिप्ट" : "AI से स्क्रिप्ट बनाओ"}
          </button>
          {st.script && !st.script_complete && (
            <button className="btn" disabled={busy} onClick={() => call(`/api/projects/${pid}/script`, { body: { fresh: false }, keys: "all" })}>अधूरी स्क्रिप्ट पूरी करो</button>
          )}
          <button className="btn" disabled={busy} onClick={() => setManual((m) => !m)}>मैं ख़ुद लिखूँगा</button>
        </div>
      )}
      {running && <JobBox job={job!} title="स्क्रिप्ट लिखी जा रही है…" cancellable />}
      {job?.status === "failed" && <div className="msg error" role="alert">{job.error}</div>}
      {manual && (
        <div className="field">
          <label htmlFor="manual" className="small muted">पूरी स्क्रिप्ट लिखें या चिपकाएँ। हर पैराग्राफ़ एक अध्याय बनेगा; पहली लाइन "# शीर्षक" हो तो वह अध्याय का नाम बनेगा।</label>
          <textarea id="manual" className="input" rows={8} maxLength={20000} value={text} onChange={(e) => setText(e.target.value)} />
          <label htmlFor="kw" className="small muted">तस्वीरों के लिए English शब्द (वैकल्पिक, पर ज़रूरी सलाह) — जैसे: Raigad fort, Shivaji, Sahyadri mountains</label>
          <input id="kw" className="input" value={keywords} maxLength={160} onChange={(e) => setKeywords(e.target.value)} />
          <button className="btn primary" disabled={!text.trim() || busy} onClick={async () => {
            if (await call(`/api/projects/${pid}/script`, { method: "PUT", body: { manual_text: text, manual_keywords: keywords } })) { setManual(false); setDirty(false); await reload(); }
          }}>स्क्रिप्ट सहेजो</button>
        </div>
      )}
      {script && (
        <>
          <p className="small muted">{script.chapters.length} अध्याय · {script.chapters.reduce((n, c) => n + c.scenes.length, 0)} सीन · ~{words} शब्द (≈ {fmtTime(words / 1.8)})
            {!st.script_complete && <b className="warn"> · अधूरी</b>}</p>
          {script.chapters.map((c, ci) => (
            <details key={ci} className="chapter" open={ci === 0}>
              <summary><b>{ci + 1}. {c.title || "अध्याय"}</b> <span className="small muted">({c.scenes.length} सीन)</span></summary>
              <label className="tfield wide"><span className="small muted">अध्याय का नाम</span>
                <input className="input" aria-label={`अध्याय ${ci + 1} का नाम`} value={c.title} maxLength={120} onChange={(e) => setChapter(ci, { title: e.target.value })} />
              </label>
              <ul className="ops">
                {c.scenes.map((s, si) => (
                  <li key={s.id || si} className="op">
                    <div className="ophead"><span className="tag">{s.id || "नया"}</span>
                      <button className="btn icon danger" aria-label="सीन हटाओ" onClick={() => setChapter(ci, { scenes: c.scenes.filter((_, j) => j !== si) })}>✕</button>
                    </div>
                    <textarea className="input" rows={2} value={s.text} maxLength={700} aria-label={`${s.id || "नया"} नैरेशन`}
                              onChange={(e) => setScene(ci, si, { text: e.target.value })} />
                    <div className="opfields">
                      <label className="tfield"><span className="small muted">तस्वीर</span>
                        <select className="input" aria-label={`${s.id || "नया"} तस्वीर प्रकार`} value={s.visual.kind} onChange={(e) => setScene(ci, si, { visual: { ...s.visual, kind: e.target.value } })}>
                          {VISUAL_KINDS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                        </select>
                      </label>
                      <label className="tfield"><span className="small muted">खोज (English बेहतर)</span>
                        <input className="input" aria-label={`${s.id || "नया"} तस्वीर खोज`} value={s.visual.query} maxLength={160} onChange={(e) => setScene(ci, si, { visual: { ...s.visual, query: e.target.value } })} />
                      </label>
                      <label className="tfield"><span className="small muted">लेआउट</span>
                        <select className="input" aria-label={`${s.id || "नया"} लेआउट`} value={s.layout} onChange={(e) => setScene(ci, si, { layout: e.target.value })}>
                          {[["auto", "Auto"], ["avatar_center_side_inserts", "अवतार + साइड तस्वीर"], ["broll_fullscreen_avatar_corner", "पूरी तस्वीर + कोने में अवतार"], ["avatar_only", "सिर्फ़ अवतार"]]
                            .map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                        </select>
                      </label>
                    </div>
                  </li>
                ))}
              </ul>
              <button className="btn" onClick={() => setChapter(ci, { scenes: [...c.scenes, { id: "", text: "", layout: "auto", visual: { kind: "ai_image", query: st.wizard.topic, alt_queries: [] }, fact_refs: [], est_seconds: null }] })}>+ सीन जोड़ो</button>
            </details>
          ))}
          <div className="row">
            <button className="btn" disabled={!dirty || busy} onClick={async () => {
              if (await call(`/api/projects/${pid}/script`, { method: "PUT", body: { script } })) setDirty(false);
            }}>स्क्रिप्ट सहेजो</button>
            {dirty && <span className="small warn">बदलाव सहेजे नहीं गए</span>}
          </div>
        </>
      )}
    </section>
  );
}

// --- per-scene regenerate ----------------------------------------------------------------------------
function SceneList({ st, busy, call }: { st: CreateState; busy: boolean; call: (p: string, o?: any) => Promise<boolean> }) {
  const [q, setQ] = useState<Record<string, string>>({});
  if (!st.script) return null;
  const pid = st.project.id;
  const regen = (sid: string, what: string, extra: object = {}) =>
    call(`/api/projects/${pid}/scenes/${sid}/regenerate`, { body: { what, ...extra }, keys: "all" });
  return (
    <details>
      <summary><b>सीन बदलो</b> <span className="small muted">— एक सीन की तस्वीर, आवाज़ या टेक्स्ट दोबारा बनाओ</span></summary>
      <ul className="scenes">
        {st.script.chapters.flatMap((c) => c.scenes).map((s) => {
          const ss = st.scenes[s.id];
          return (
            <li key={s.id} className="scene">
              <div className="thumb">
                {ss?.visual ? (ss.visual.media === "video"
                  ? <video src={ss.visual.url} muted playsInline preload="metadata" />
                  : <img src={ss.visual.url} alt="" loading="lazy" />) : <span className="small muted">सिर्फ़ अवतार</span>}
              </div>
              <div className="sbody">
                <div className="small muted">{s.id} · {ss?.duration ? `${ss.duration.toFixed(1)} s` : "—"}</div>
                <div className="stext">{s.text}</div>
                {ss?.visual?.attribution && <div className="small muted">{ss.visual.attribution}</div>}
                <div className="row">
                  <input className="input grow-select" placeholder="नई खोज (वैकल्पिक)" value={q[s.id] || ""} aria-label="नई तस्वीर की खोज"
                         onChange={(e) => setQ((x) => ({ ...x, [s.id]: e.target.value }))} />
                  <button className="btn" disabled={busy} onClick={() => regen(s.id, "visual", q[s.id] ? { query: q[s.id] } : {})}>नई तस्वीर</button>
                  <button className="btn" disabled={busy} onClick={() => regen(s.id, "voice")}>आवाज़ फिर से</button>
                  <button className="btn" disabled={busy} onClick={() => regen(s.id, "text")}>टेक्स्ट AI से सुधारो</button>
                </div>
              </div>
            </li>
          );
        })}
      </ul>
    </details>
  );
}

// --- YouTube pack ----------------------------------------------------------------------------------------
function PackCard({ st, busy, call }: { st: CreateState; busy: boolean; call: (p: string, o?: any) => Promise<boolean> }) {
  const m = st.meta!;
  const [tab, setTab] = useState("youtube");
  const pm = m.platforms[tab];
  return (
    <section className="card">
      <h2>5. YouTube पैक</h2>
      <p className="small muted">{m.source === "template" ? "साधारण टेम्पलेट से बना — AI key डालकर 'AI से फिर बनाओ' दबाएँ।" : "AI से बना। ज़रूरत हो तो बदलकर इस्तेमाल करें।"}</p>
      {st.thumbnail && <img className="thumbimg" src={st.thumbnail.url} alt="थंबनेल" />}
      <div className="tabs" role="tablist">
        {Object.keys(PLATFORM_LABEL).map((p) => (
          <button key={p} role="tab" aria-selected={tab === p} className={"btn" + (tab === p ? " on" : "")} onClick={() => setTab(p)}>{PLATFORM_LABEL[p]}</button>
        ))}
      </div>
      {tab === "youtube" ? (
        <>
          <h3>टाइटल विकल्प</h3>
          <ul className="ops">{m.titles.map((t, i) => (
            <li key={i} className="op row"><span className="grow wrap">{t}</span><button className="btn" onClick={() => copy(t)}>कॉपी</button></li>
          ))}</ul>
          <h3>विवरण (अध्याय-समय के साथ)</h3>
          <textarea className="input" rows={8} readOnly value={m.youtube_description} aria-label="विवरण" />
          <button className="btn" onClick={() => copy(m.youtube_description)}>विवरण कॉपी</button>
          <h3>टैग</h3>
          <p className="small">{m.tags.join(", ")}</p>
          <button className="btn" onClick={() => copy(m.tags.join(", "))}>टैग कॉपी</button>
        </>
      ) : pm ? (
        <>
          <h3>{pm.title}</h3>
          <textarea className="input" rows={5} readOnly value={`${pm.text}\n\n${pm.hashtags.join(" ")}`} aria-label="पोस्ट टेक्स्ट" />
          <button className="btn" onClick={() => copy(`${pm.title}\n\n${pm.text}\n\n${pm.hashtags.join(" ")}`)}>कॉपी</button>
        </>
      ) : null}
      <div className="row"><button className="btn" disabled={busy} onClick={() => call(`/api/projects/${st.project.id}/youtube-pack`, { keys: "all" })}>AI से फिर बनाओ</button></div>
    </section>
  );
}

// --- export + AI disclosure gate (PRD §5.5, §12.3) ------------------------------------------------------------
function ExportCard({ st, call }: { st: CreateState; call: (p: string, o?: any) => Promise<boolean> }) {
  const [checks, setChecks] = useState<boolean[]>(st.checklist.map(() => !!st.disclosure_ack_at));
  const ok = !!st.disclosure_ack_at;
  const out = st.outputs[0];
  const pid = st.project.id;
  return (
    <section className="card" id="export">
      <h2>6. डाउनलोड</h2>
      <div className="msg info">
        YouTube के नियम: AI से बनी आवाज़/तस्वीरों वाले वीडियो पर YouTube Studio में <b>"Altered or synthetic content"</b> disclosure ज़रूरी है।
        एक जैसे टेम्पलेट वाले वीडियो monetize नहीं होते — अपनी आवाज़, राय या रिसर्च जोड़ें।
      </div>
      {st.checklist.map((c, i) => (
        <label key={i} className="check block">
          <input type="checkbox" checked={checks[i] || false} disabled={ok}
                 onChange={(e) => setChecks((x) => x.map((v, j) => (j === i ? e.target.checked : v)))} />{c}
        </label>
      ))}
      {!ok ? (
        <button className="btn primary full" disabled={!checks.every(Boolean)}
                onClick={() => call(`/api/projects/${pid}/disclosure`, { body: { ack: true, checklist: checks } })}>
          पुष्टि करें और डाउनलोड खोलें
        </button>
      ) : (
        <div className="row">
          <a className="btn primary" href={`${out.url}?download=1`} download>वीडियो डाउनलोड</a>
          {st.thumbnail && <a className="btn" href={`${st.thumbnail.url}?download=1`} download>थंबनेल</a>}
          {st.meta && <a className="btn" href={`/api/projects/${pid}/youtube-pack.txt`} download>YouTube पैक (.txt)</a>}
        </div>
      )}
    </section>
  );
}
