import { useState } from "react";
import { api, uploadFile } from "../api";

/** Workflow A step 1: create a project and upload the video. */
export function EditNew() {
  const [file, setFile] = useState<File | null>(null);
  const [title, setTitle] = useState("");
  const [language, setLanguage] = useState("hi");
  const [pct, setPct] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [projectId, setProjectId] = useState<string | null>(null);

  async function start() {
    if (!file) return;
    setError(null);
    try {
      let pid = projectId;
      if (!pid) {
        const p = await api<{ id: string }>("/api/projects", { body: { kind: "edit", title: title || file.name.replace(/\.[^.]+$/, "") } });
        pid = p.id;
        setProjectId(pid);
      }
      setPct(0);
      const q = new URLSearchParams({ kind: "source", name: file.name, language });
      await uploadFile(`/api/projects/${pid}/upload?${q}`, file, setPct);
      window.location.hash = `#/edit/${pid}`;
    } catch (e: any) {
      setPct(null);
      setError(e.message);
    }
  }

  const busy = pct !== null;
  return (
    <div>
      <h1>वीडियो एडिट करो</h1>
      <section className="card">
        <h2>1. वीडियो अपलोड करो</h2>
        <p className="small muted">mp4 / mov / webm · अधिकतम 3 मिनट, 300 MB। वीडियो इसी सर्वर पर रहता है।</p>
        <div className="field">
          <label htmlFor="vid">वीडियो फ़ाइल</label>
          <input id="vid" className="input" type="file" accept="video/mp4,video/quicktime,video/webm,.mp4,.mov,.webm,.m4v,.mkv"
                 disabled={busy} onChange={(e) => { setFile(e.target.files?.[0] || null); setError(null); }} />
        </div>
        <div className="field">
          <label htmlFor="title">नाम (वैकल्पिक)</label>
          <input id="title" className="input" value={title} disabled={busy} maxLength={200}
                 placeholder="जैसे: मेरा vlog" onChange={(e) => setTitle(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="lang">वीडियो में बोली गई भाषा</label>
          <select id="lang" className="input" value={language} disabled={busy} onChange={(e) => setLanguage(e.target.value)}>
            <option value="hi">हिंदी / Hinglish (कैप्शन देवनागरी में)</option>
            <option value="en">English</option>
          </select>
        </div>
        <button className="btn primary full" disabled={!file || busy} onClick={start}>
          {busy ? `अपलोड हो रहा है… ${Math.round(pct!)}%` : "अपलोड करो"}
        </button>
        {busy && <div className="progress" style={{ marginTop: 10 }}><div style={{ width: `${pct}%` }} /></div>}
        {error && (
          <div className="msg error" role="alert">
            {error}
            {projectId && <div className="small">फ़ाइल चुनकर फिर से "अपलोड करो" दबाएँ।</div>}
          </div>
        )}
      </section>
    </div>
  );
}
