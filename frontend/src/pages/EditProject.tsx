import { useCallback, useEffect, useRef, useState } from "react";
import {
  api, fmtTime, followJob, uploadFile,
  type Asset, type EditState, type JobFull, type Plan, type PlanOp, type PlanRow,
} from "../api";
import { PlanEditor } from "../components/PlanEditor";

const RUNNING = ["queued", "running"];
const STEP_LABEL: Record<string, string> = {
  ingest: "वीडियो तैयार हो रहा है", audio: "आवाज़ निकाली जा रही है", stt: "बोले गए शब्द पहचाने जा रहे हैं",
  silence: "खामोशी ढूँढी जा रही है", "b-roll": "B-roll लाया जा रहा है", final: "आख़िरी वीडियो बन रहा है",
};

function stepLabel(step: string | null): string {
  if (!step) return "";
  if (step.startsWith("segment")) return `हिस्से जोड़े जा रहे हैं (${step.slice(8)})`;
  return STEP_LABEL[step] || step;
}

/** Workflow A: transcript → prompt → editable plan → approve → render → result. */
export function EditProject({ id }: { id: string }) {
  const [st, setSt] = useState<EditState | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [live, setLive] = useState<Record<string, JobFull>>({});
  const videoRef = useRef<HTMLVideoElement>(null);
  const autoTranscribed = useRef(false);

  const load = useCallback(async () => {
    try {
      setSt(await api<EditState>(`/api/projects/${id}/state`));
    } catch (e: any) {
      setError(e.message);
    }
  }, [id]);

  useEffect(() => { load(); }, [load]);

  // follow any running job of this project; refresh state when it ends
  useEffect(() => {
    if (!st) return;
    const stops: (() => void)[] = [];
    for (const kind of ["ingest", "transcribe", "render"] as const) {
      const j = st.jobs[kind];
      if (j && RUNNING.includes(j.status)) {
        stops.push(followJob(j.id, (u) => {
          setLive((l) => ({ ...l, [kind]: u as JobFull }));
          if (!RUNNING.includes(u.status)) load();
        }));
      }
    }
    return () => stops.forEach((s) => s());
  }, [st?.jobs.ingest?.id, st?.jobs.transcribe?.id, st?.jobs.render?.id, st?.jobs.ingest?.status,
      st?.jobs.transcribe?.status, st?.jobs.render?.status, load]);

  const job = (kind: "ingest" | "transcribe" | "render"): JobFull | null => {
    const base = st?.jobs[kind] || null;
    const l = live[kind];
    return l && base && l.id === base.id ? { ...base, ...l } : base;
  };

  async function transcribe() {
    setError(null);
    try {
      await api(`/api/projects/${id}/transcribe`, { body: {}, keys: "all" });
      await load();
    } catch (e: any) {
      setError(e.message);
    }
  }

  // PRD 4.1-2: transcribe automatically once the video is ready
  useEffect(() => {
    if (!st || autoTranscribed.current) return;
    if (st.work && !st.transcript && !st.jobs.transcribe) {
      autoTranscribed.current = true;
      transcribe();
    }
  }, [st]);

  if (error && !st) return <div className="msg error">{error}</div>;
  if (!st) return <p className="muted">लोड हो रहा है…</p>;

  const ingest = job("ingest");
  const tjob = job("transcribe");
  const rjob = job("render");
  const ready = !!st.work;
  const latestOut = st.outputs[0];

  return (
    <div>
      <a className="small" href="#/">← होम</a>
      <h1>{st.project.title}</h1>
      {error && <div className="msg error" role="alert">{error}</div>}

      {/* 1. video + ingest */}
      <section className="card">
        <h2>वीडियो</h2>
        {ready ? (
          <video ref={videoRef} className="player" src={st.work!.url} controls playsInline preload="metadata" />
        ) : ingest ? (
          <JobBox job={ingest} title="वीडियो तैयार हो रहा है (constant frame rate, 720p)…" />
        ) : (
          <div className="msg error">इस प्रोजेक्ट में वीडियो नहीं है। <a href="#/edit">नया अपलोड करो</a></div>
        )}
        {ready && (
          <div className="small muted">
            {fmtTime(st.work!.duration_s)} · {st.work!.meta.width}×{st.work!.meta.height} · {st.work!.meta.fps} fps
            {st.work!.meta.source_has_audio === false && " · आवाज़ नहीं"}
          </div>
        )}
      </section>

      {/* 2. transcript */}
      {ready && (
        <section className="card">
          <h2>बोले गए शब्द (transcript)</h2>
          {tjob && RUNNING.includes(tjob.status) && <JobBox job={tjob} title="Transcript बन रहा है…" />}
          {tjob?.status === "failed" && (!st.transcript || (tjob.finished_at || 0) > st.transcript.created_at) && (
            <div className="msg error" role="alert">
              {tjob.error}
              <div className="small">Settings में Groq key डालकर फिर कोशिश करें। बिना transcript के भी एडिट हो सकता है — बस कैप्शन नहीं बनेंगे।</div>
            </div>
          )}
          {st.transcript && (
            st.transcript.segments.length ? (
              <details>
                <summary className="small">{st.transcript.word_count} शब्द · {st.transcript.provider} — देखने के लिए दबाएँ (समय पर दबाकर वीडियो वहाँ ले जाएँ)</summary>
                <ul className="transcript">
                  {st.transcript.segments.map((s, i) => (
                    <li key={i}>
                      <button className="link ts" onClick={() => { if (videoRef.current) { videoRef.current.currentTime = s.start; videoRef.current.play().catch(() => {}); } }}>
                        {fmtTime(s.start)}
                      </button>
                      <span>{s.text}</span>
                    </li>
                  ))}
                </ul>
              </details>
            ) : <p className="small muted">कोई बोले गए शब्द नहीं मिले — कैप्शन नहीं बनेंगे।</p>
          )}
          {(!tjob || ["failed", "cancelled"].includes(tjob.status)) && (
            <button className="btn" onClick={transcribe}>{st.transcript ? "फिर से transcript बनाओ" : "Transcript बनाओ"}</button>
          )}
        </section>
      )}

      {/* 3. prompt + plan */}
      {ready && (
        <PlanSection st={st} videoRef={videoRef} onChanged={load} rendering={!!rjob && RUNNING.includes(rjob.status)}
                     onRender={async () => {
                       setError(null);
                       try {
                         await api(`/api/projects/${id}/approve-and-render`, { method: "POST", keys: "all" });
                         await load();
                       } catch (e: any) { setError(e.message); }
                     }} />
      )}

      {/* 4. render + result */}
      {rjob && (
        <section className="card" id="result">
          <h2>नतीजा</h2>
          {RUNNING.includes(rjob.status) && <JobBox job={rjob} title="रेंडर हो रहा है…" cancellable />}
          {rjob.status === "failed" && <div className="msg error" role="alert">रेंडर विफल: {rjob.error}</div>}
          {rjob.status === "cancelled" && <div className="msg info">रेंडर रोका गया।</div>}
          {rjob.status === "done" && rjob.result?.notices?.length > 0 && (
            <ul className="warnlist">{rjob.result.notices.map((n: string, i: number) => <li key={i}>{n}</li>)}</ul>
          )}
          {latestOut && <ResultView out={latestOut} job={rjob.status === "done" ? rjob : null} />}
        </section>
      )}
    </div>
  );
}

function ResultView({ out, job }: { out: Asset; job: JobFull | null }) {
  return (
    <div>
      <video className="player" src={out.url} controls playsInline preload="metadata" />
      <div className="row">
        <a className="btn primary" href={`${out.url}?download=1`} download>डाउनलोड करो</a>
        <span className="small muted">{fmtTime(out.duration_s)}{job?.result ? ` · ${job.result.render_seconds} s में बना` : ""}</span>
      </div>
      {out.attribution && <div className="small muted">श्रेय: {out.attribution}</div>}
      <p className="small muted">कुछ बदलना है? ऊपर प्रॉम्प्ट/प्लान बदलकर फिर से रेंडर करें — दोबारा अपलोड की ज़रूरत नहीं।</p>
    </div>
  );
}

export function JobBox({ job, title, cancellable }: { job: JobFull; title: string; cancellable?: boolean }) {
  return (
    <div className="jobbox" aria-live="polite">
      <div className="small">{title} {stepLabel(job.step) && <b>· {stepLabel(job.step)}</b>}</div>
      <div className="progress"><div style={{ width: `${job.progress}%` }} /></div>
      <div className="row">
        <span className="small muted">{Math.round(job.progress)}%</span>
        {cancellable && (
          <button className="btn danger" onClick={() => api(`/api/jobs/${job.id}/cancel`, { method: "POST" }).catch(() => {})}>रोको</button>
        )}
      </div>
      {job.log?.length > 0 && (
        <details>
          <summary className="small muted">लॉग</summary>
          <ul className="joblog">{job.log.map((l, i) => <li key={i} className={l.level}>{l.msg}</li>)}</ul>
        </details>
      )}
    </div>
  );
}

function PlanSection({ st, videoRef, onChanged, onRender, rendering }: {
  st: EditState; videoRef: React.RefObject<HTMLVideoElement>; onChanged: () => Promise<void>;
  onRender: () => Promise<void>; rendering: boolean;
}) {
  const row: PlanRow | null = st.plan;
  const [prompt, setPrompt] = useState(row?.prompt || "");
  const [ops, setOps] = useState<PlanOp[]>(row?.plan.ops || []);
  const [dirty, setDirty] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [notices, setNotices] = useState<string[]>([]);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (!dirty) {
      setOps(row?.plan.ops || []);
      if (row?.prompt != null) setPrompt(row.prompt);
    }
  }, [row?.version]);

  const plan: Plan | null = row?.plan || null;
  const duration = st.work?.duration_s || 0;

  async function generate() {
    setErr(null); setNotices([]); setBusy("plan");
    try {
      const r = await api<{ plan: PlanRow; notices: string[]; provider: string }>(`/api/projects/${st.project.id}/plan`,
        { body: { prompt }, keys: "all" });
      setDirty(false);
      setOps(r.plan.plan.ops);
      setNotices([...r.notices, `प्लान ${r.provider} से बना।`]);
      await onChanged();
    } catch (e: any) { setErr(e.message); } finally { setBusy(null); }
  }

  async function save(): Promise<boolean> {
    setErr(null); setBusy("save");
    try {
      const r = await api<{ plan: PlanRow }>(`/api/projects/${st.project.id}/plan`,
        { method: "PUT", body: { plan: { ops }, prompt } });
      setOps(r.plan.plan.ops);
      setDirty(false);
      await onChanged();
      return true;
    } catch (e: any) { setErr(e.message); return false; } finally { setBusy(null); }
  }

  async function approve() {
    if ((dirty || !row) && !(await save())) return;
    setBusy("render");
    await onRender();
    setBusy(null);
    window.setTimeout(() => document.getElementById("result")?.scrollIntoView({ behavior: "smooth" }), 300);
  }

  async function addUpload(kind: "music" | "broll", file: File) {
    setErr(null); setBusy("upload");
    try {
      await uploadFile(`/api/projects/${st.project.id}/upload?${new URLSearchParams({ kind, name: file.name })}`, file, () => {});
      await onChanged();
    } catch (e: any) { setErr(e.message); } finally { setBusy(null); }
  }

  return (
    <section className="card">
      <h2>क्या बदलना है?</h2>
      <label htmlFor="prompt" className="small muted">हिंदी, Hinglish या English में लिखो — जैसे "0:12 से 0:18 काट दो, 0:30 पर 'ज़रूरी बात' लिखो, कैप्शन लगाओ"</label>
      <textarea id="prompt" className="input" rows={3} value={prompt} maxLength={2000}
                onChange={(e) => setPrompt(e.target.value)} />
      <div className="row">
        <button className="btn primary" disabled={!prompt.trim() || !!busy || rendering} onClick={generate}>
          {busy === "plan" ? "AI प्लान बना रहा है…" : "AI से प्लान बनाओ"}
        </button>
        <span className="small muted">या नीचे ख़ुद rows जोड़ो</span>
      </div>
      {notices.map((n, i) => <div key={i} className="small warn">{n}</div>)}
      {err && <div className="msg error" role="alert">{err}</div>}

      {plan?.question && !dirty && <div className="msg info"><b>AI का सवाल:</b> {plan.question}</div>}
      {plan && plan.warnings.length > 0 && !dirty && (
        <ul className="warnlist">{plan.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
      )}

      <PlanEditor ops={ops} duration={duration} uploads={st.uploads} videoRef={videoRef}
                  onChange={(o) => { setOps(o); setDirty(true); }} onUpload={addUpload} disabled={!!busy || rendering} />

      <div className="row">
        <button className="btn" disabled={!dirty || !!busy} onClick={save}>{busy === "save" ? "सहेजा जा रहा है…" : "प्लान सहेजो"}</button>
        {row && !dirty && row.expected_duration_s != null && (
          <span className="small muted">
            नई लंबाई ≈ {fmtTime(row.expected_duration_s)}{ops.some((o) => o.type === "remove_silence") ? " (खामोशी हटाने से पहले)" : ""}
          </span>
        )}
        {dirty && <span className="small warn">बदलाव सहेजे नहीं गए</span>}
      </div>
      <button className="btn primary full" disabled={!ops.length || !!busy || rendering} onClick={approve}>
        {rendering ? "रेंडर चल रहा है…" : busy === "render" ? "शुरू हो रहा है…" : "मंज़ूर करो और वीडियो बनाओ"}
      </button>
      <p className="small muted">रेंडर तभी शुरू होता है जब आप यह बटन दबाते हैं।</p>
    </section>
  );
}
