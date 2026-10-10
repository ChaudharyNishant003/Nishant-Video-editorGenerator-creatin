import { useEffect, useMemo, useState } from "react";
import { api, followJob, type Job, type ProviderMeta } from "../api";
import { clearAllKeys, loadKeys, saveProviderKeys, type ProviderKeys } from "../keys";

const CAP_LABEL: Record<string, string> = {
  llm: "टेक्स्ट / AI मॉडल (LLM)",
  stt: "बोलने से टेक्स्ट (STT)",
  tts: "आवाज़ (TTS)",
  image: "इमेज",
  stock: "स्टॉक फ़ुटेज / फ़ोटो",
  avatar: "अवतार",
};
const CAP_ORDER = ["llm", "stt", "tts", "image", "stock", "avatar"];

type TestStatus = { status: string; message: string; at: number };
const STATUS_LABEL: Record<string, string> = {
  not_set: "Key नहीं डाली",
  valid: "सही है",
  invalid: "ग़लत key",
  rate_limited: "Limit पूरी",
  error: "त्रुटि",
  unavailable: "उपलब्ध नहीं",
};

function hasAllKeys(p: ProviderMeta, keys: ProviderKeys): boolean {
  const mine = keys[p.key_source || p.id] || {};
  return p.requires_keys.every((k) => !!mine[k.name]);
}

export function Settings() {
  const [caps, setCaps] = useState<Record<string, ProviderMeta[]> | null>(null);
  const [prefs, setPrefs] = useState<Record<string, string>>({});
  const [keys, setKeys] = useState<ProviderKeys>(() => loadKeys());
  const [tests, setTests] = useState<Record<string, TestStatus>>({});
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api<{ capabilities: Record<string, ProviderMeta[]> }>("/api/providers"),
                 api<{ values: Record<string, string> }>("/api/preferences")])
      .then(([p, pr]) => { setCaps(p.capabilities); setPrefs(pr.values); })
      .catch((e) => setError(e.message));
  }, []);

  const byId = useMemo(() => {
    const m: Record<string, ProviderMeta> = {};
    Object.values(caps || {}).flat().forEach((p) => (m[p.id] = p));
    return m;
  }, [caps]);

  async function setDefault(cap: string, providerId: string) {
    try {
      const r = await api<{ values: Record<string, string> }>("/api/preferences", {
        method: "PUT", body: { values: { [`default.${cap}`]: providerId } },
      });
      setPrefs(r.values);
      flash("डिफ़ॉल्ट सहेजा गया।");
    } catch (e: any) {
      setError(e.message);
    }
  }

  async function setPref(name: string, value: string) {
    const r = await api<{ values: Record<string, string> }>("/api/preferences", { method: "PUT", body: { values: { [name]: value } } });
    setPrefs(r.values);
    flash("सहेजा गया।");
  }

  function flash(msg: string) {
    setNotice(msg);
    window.setTimeout(() => setNotice(null), 2500);
  }

  async function testKey(p: ProviderMeta) {
    setTests((t) => ({ ...t, [p.id]: { status: "checking", message: "जाँच हो रही है…", at: Date.now() } }));
    try {
      const r = await api<{ status: string; message: string }>(`/api/providers/${p.id}/test`, {
        method: "POST", keys: [p.key_source || p.id],
      });
      setTests((t) => ({ ...t, [p.id]: { status: r.status, message: r.message, at: Date.now() } }));
    } catch (e: any) {
      setTests((t) => ({ ...t, [p.id]: { status: "error", message: e.message, at: Date.now() } }));
    }
  }

  function onSaved(providerId: string, fields: Record<string, string>) {
    saveProviderKeys(providerId, fields);
    setKeys(loadKeys());
    setTests((t) => { const n = { ...t }; delete n[providerId]; return n; });
    flash("Key इस ब्राउज़र में सहेजी गई।");
  }

  function onClearAll() {
    if (!window.confirm("इस ब्राउज़र से सारी API keys हटा दें?")) return;
    clearAllKeys();
    setKeys({});
    setTests({});
    flash("सारी keys हटा दी गईं।");
  }

  if (error && !caps) return <div className="msg error">{error}</div>;
  if (!caps) return <p className="muted">लोड हो रहा है…</p>;

  return (
    <div>
      <h1>सेटिंग्स</h1>
      <div className="msg info">
        Keys सिर्फ़ <b>इस ब्राउज़र</b> में सहेजी जाती हैं, सर्वर पर कभी नहीं। ब्राउज़र डेटा साफ़ करने या दूसरे डिवाइस पर
        आपको इन्हें फिर से डालना होगा।
      </div>
      {notice && <div className="msg success" role="status">{notice}</div>}
      {error && <div className="msg error">{error}</div>}

      {CAP_ORDER.filter((c) => caps[c]).map((cap) => {
        const list = caps[cap];
        const usable = list.filter((p) => p.enabled);
        const current = prefs[`default.${cap}`] || usable[0]?.id || "";
        return (
          <section key={cap} className="card cap">
            <h2>{CAP_LABEL[cap] || cap}</h2>
            <label className="small muted" htmlFor={`def-${cap}`}>डिफ़ॉल्ट provider</label>
            <select id={`def-${cap}`} className="input" value={current} onChange={(e) => setDefault(cap, e.target.value)}>
              {list.map((p) => (
                <option key={p.id} value={p.id} disabled={!p.enabled}>
                  {p.label} — {p.tier === "free" ? "Free" : "Premium"}
                  {!p.enabled ? " (जल्द)" : p.requires_keys.length && !hasAllKeys(p, keys) ? " — key डालो" : ""}
                </option>
              ))}
            </select>
            <div className="providers">
              {list.map((p) => (
                <ProviderCard key={p.id} p={p} keys={keys} source={p.key_source ? byId[p.key_source] : undefined}
                              test={tests[p.id]} onTest={() => testKey(p)} onSave={onSaved} />
              ))}
            </div>
          </section>
        );
      })}

      <section className="card">
        <h2>डेटा</h2>
        <label className="small muted" htmlFor="ret">पूरे हुए प्रोजेक्ट का मीडिया इतने दिन बाद हटाएँ</label>
        <div className="row">
          <input id="ret" className="input narrow" type="number" min={1} max={365}
                 defaultValue={prefs.retention_days || "30"}
                 onBlur={(e) => e.target.value && setPref("retention_days", e.target.value)} />
          <span className="muted">दिन</span>
        </div>
        <button className="btn danger" onClick={onClearAll}>सारी keys हटाओ</button>
      </section>

      <SystemCheck />
    </div>
  );
}

function ProviderCard({ p, keys, source, test, onTest, onSave }: {
  p: ProviderMeta; keys: ProviderKeys; source?: ProviderMeta; test?: TestStatus;
  onTest: () => void; onSave: (id: string, fields: Record<string, string>) => void;
}) {
  const stored = keys[p.id] || {};
  const [draft, setDraft] = useState<Record<string, string>>(stored);
  useEffect(() => setDraft(keys[p.id] || {}), [keys, p.id]);
  const ownsKeys = p.requires_keys.length > 0 && !p.key_source;
  const dirty = p.requires_keys.some((k) => (draft[k.name] || "") !== (stored[k.name] || ""));
  const keyDocs = p.requires_keys[0]?.docs_url;
  const shown = test?.status === "checking" ? "checking" : test?.status;

  return (
    <div className={"pcard" + (p.enabled ? "" : " disabled")}>
      <div className="phead">
        <span className={"badge " + p.tier}>{p.tier === "free" ? "Free" : "Premium"}</span>
        <strong>{p.label}</strong>
        {shown && <span className={"status " + shown}>{shown === "checking" ? "…" : STATUS_LABEL[shown] || shown}</span>}
      </div>
      {p.note && <div className="small muted">{p.note}</div>}
      {p.limits_note && <div className="small muted">{p.limits_note}</div>}
      {!p.enabled ? null : ownsKeys ? (
        <>
          {p.requires_keys.map((k) => (
            <div key={k.name} className="field">
              <label className="small" htmlFor={`${p.id}-${k.name}`}>{k.label}</label>
              <input id={`${p.id}-${k.name}`} className="input" type="password" autoComplete="off" spellCheck={false}
                     value={draft[k.name] || ""} placeholder="यहाँ key चिपकाएँ"
                     onChange={(e) => setDraft((d) => ({ ...d, [k.name]: e.target.value }))} />
            </div>
          ))}
          <div className="row">
            <button className="btn primary" disabled={!dirty} onClick={() => onSave(p.id, draft)}>सहेजो</button>
            <button className="btn" disabled={dirty} onClick={onTest} title={dirty ? "पहले सहेजो" : ""}>Key टेस्ट करें</button>
          </div>
        </>
      ) : (
        <div className="row">
          <span className="small muted">
            {p.key_source ? `${source?.label || p.key_source} वाली key इस्तेमाल होती है।` : "Key की ज़रूरत नहीं।"}
          </span>
          <button className="btn" onClick={onTest}>जाँचें</button>
        </div>
      )}
      {test && test.status !== "checking" && <div className={"small " + (test.status === "valid" ? "ok" : "warn")}>{test.message}</div>}
      {(keyDocs || p.docs_url) && p.enabled && (
        <a className="small" href={keyDocs || p.docs_url} target="_blank" rel="noreferrer">
          {keyDocs ? "Key कैसे लें ↗" : "जानकारी ↗"}
        </a>
      )}
    </div>
  );
}

function SystemCheck() {
  const [job, setJob] = useState<Job | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function start() {
    setErr(null);
    try {
      const r = await api<{ job_id: string }>("/api/jobs/selftest", { body: { seconds: 20 }, keys: "all" });
      followJob(r.job_id, setJob);
    } catch (e: any) {
      setErr(e.message);
    }
  }
  async function cancel() {
    if (job) await api(`/api/jobs/${job.id}/cancel`, { method: "POST" }).catch((e) => setErr(e.message));
  }
  const running = job && (job.status === "queued" || job.status === "running");

  return (
    <section className="card">
      <h2>सिस्टम जाँच</h2>
      <p className="small muted">20 सेकंड का टेस्ट-रेंडर चलाकर job, progress और cancel की जाँच। आपकी keys सिर्फ़ इस job की memory में रहती हैं।</p>
      <div className="row">
        <button className="btn" onClick={start} disabled={!!running}>टेस्ट चलाओ</button>
        <button className="btn danger" onClick={cancel} disabled={!running}>रोको</button>
      </div>
      {job && (
        <div className="jobbox">
          <div className="progress"><div style={{ width: `${job.progress}%` }} /></div>
          <div className="small">स्थिति: <b>{job.status}</b> · {Math.round(job.progress)}%</div>
          <ul className="joblog">{job.log.map((l, i) => <li key={i} className={l.level}>{l.msg}</li>)}</ul>
        </div>
      )}
      {err && <div className="msg error">{err}</div>}
    </section>
  );
}
