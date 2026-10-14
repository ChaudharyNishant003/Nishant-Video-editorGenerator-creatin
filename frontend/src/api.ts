import { encodeKeysHeader, loadKeys, type ProviderKeys } from "./keys";

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string) {
    super(message);
  }
}

type Opts = {
  method?: string;
  body?: unknown;
  /** attach provider keys: "all", or a list of provider ids */
  keys?: "all" | string[];
};

function pickKeys(which: Opts["keys"]): ProviderKeys | null {
  if (!which) return null;
  const all = loadKeys();
  if (which === "all") return all;
  const out: ProviderKeys = {};
  for (const id of which) if (all[id]) out[id] = all[id];
  return out;
}

export async function api<T = any>(path: string, opts: Opts = {}): Promise<T> {
  const headers: Record<string, string> = {};
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  const keys = pickKeys(opts.keys);
  if (keys && Object.keys(keys).length) headers["X-Provider-Keys"] = encodeKeysHeader(keys);
  let res: Response;
  try {
    res = await fetch(path, {
      method: opts.method || (opts.body !== undefined ? "POST" : "GET"),
      headers,
      credentials: "same-origin",
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    });
  } catch {
    throw new ApiError(0, "network", "सर्वर से कनेक्शन नहीं हो सका। क्या backend चल रहा है?");
  }
  const text = await res.text();
  let data: any = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = null;
  }
  if (!res.ok) {
    const err = data?.error || {};
    throw new ApiError(res.status, err.code || "error", err.message || `त्रुटि ${res.status}`);
  }
  return data as T;
}

export type KeySpec = { name: string; label: string; docs_url: string };
export type ProviderMeta = {
  id: string;
  label: string;
  capability: string;
  tier: "free" | "premium";
  requires_keys: KeySpec[];
  limits_note: string;
  docs_url: string;
  enabled: boolean;
  note: string;
  key_source: string | null;
};
export type Job = {
  id: string;
  kind: string;
  status: "queued" | "running" | "done" | "failed" | "cancelled";
  step: string | null;
  progress: number;
  log: { t: number; level: string; msg: string }[];
  error: string | null;
};

export type JobFull = Job & { result: any; project_id: string | null; finished_at: number | null; created_at?: number };

export type Asset = {
  id: string;
  kind: string;
  mime: string | null;
  duration_s: number | null;
  name: string | null;
  meta: Record<string, any>;
  attribution: string | null;
  url: string;
  created_at: number;
};

export type PlanOp = { id?: string; type: string; proposed_by_ai?: boolean; [k: string]: any };
export type Plan = { version: number; source_duration_s: number; ops: PlanOp[]; warnings: string[]; question: string | null };
export type PlanRow = { version: number; prompt: string | null; plan: Plan; approved_at: number | null; expected_duration_s: number | null };

export type EditState = {
  project: { id: string; title: string; status: string; settings: Record<string, any> };
  source: Asset | null;
  work: Asset | null;
  uploads: Asset[];
  outputs: Asset[];
  transcript: null | {
    provider: string; language: string; word_count: number; created_at: number;
    segments: { start: number; end: number; text: string }[];
  };
  plan: PlanRow | null;
  jobs: { ingest: JobFull | null; transcribe: JobFull | null; render: JobFull | null };
  limits: { max_upload_mb: number; max_upload_seconds: number };
};

// --- Workflow B (topic → avatar video) ---------------------------------------------------------
export type Opt = { id: string; label: string };
export type Catalog = {
  characters: { id: string; label: string; description: string; preview: string; outfits: (Opt & { color: number[] })[] }[];
  backgrounds: (Opt & { preview: string })[];
  languages: Opt[]; aspects: string[]; minutes: number[]; voices: Opt[]; rates: Opt[];
  layouts: Opt[]; caption_styles: Opt[]; caption_scripts: Opt[]; checklist: string[];
};
export type Wizard = {
  topic: string; notes: string; audience: string; tone: string; language: string; aspect: string; minutes: number;
  character: string; outfit: string; background: string; voice: string; rate: string; layout: string;
  caption_style: string; caption_script: string; music_asset_id: string | null; music_volume: number;
};
export type Fact = { id: string; text: string; source_url: string | null; uncertain: boolean };
export type Visual = { kind: string; query: string; alt_queries: string[] };
export type Scene = { id: string; text: string; layout: string; visual: Visual; fact_refs: string[]; est_seconds: number | null };
export type Chapter = { chapter: number; title: string; scenes: Scene[] };
export type Script = { title: string; chapters: Chapter[]; manual: boolean };
export type PlatformMeta = { title: string; text: string; hashtags: string[] };
export type Meta = {
  titles: string[]; description: string; tags: string[]; platforms: Record<string, PlatformMeta>; source: string;
  youtube_description: string; chapters: { t: number; title: string }[];
};
export type SceneState = {
  duration: number | null; has_audio: boolean; layout: string | null;
  visual: { url: string; attribution: string | null; provider: string | null; media: string | null } | null;
};
export type CreateJobs = Record<"research" | "script" | "generate" | "regenerate" | "pack", JobFull | null>;
export type CreateState = {
  project: { id: string; title: string; status: string; settings: Record<string, any> };
  wizard: Wizard; facts: Fact[] | null; sources: { title: string; url: string; lang: string }[]; facts_provider: string | null;
  outline: any; script: Script | null; script_complete: boolean; scenes: Record<string, SceneState>;
  outputs: Asset[]; thumbnail: Asset | null; music: Asset[]; meta: Meta | null; notices: string[];
  disclosure_ack_at: number | null; jobs: CreateJobs; checklist: string[];
};

/** Raw-body upload with progress (fetch has no upload progress). */
export function uploadFile(url: string, file: File, onProgress: (pct: number) => void): Promise<any> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    xhr.withCredentials = true;
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress((e.loaded / e.total) * 100);
    xhr.onload = () => {
      let data: any = null;
      try { data = JSON.parse(xhr.responseText); } catch { /* ignore */ }
      if (xhr.status >= 200 && xhr.status < 300) resolve(data);
      else reject(new ApiError(xhr.status, data?.error?.code || "error", data?.error?.message || `त्रुटि ${xhr.status}`));
    };
    xhr.onerror = () => reject(new ApiError(0, "network", "Upload बीच में रुक गया — इंटरनेट/सर्वर जाँचें और फिर कोशिश करें।"));
    xhr.send(file);
  });
}

export function fmtTime(t: number | null | undefined): string {
  if (t == null || isNaN(t)) return "";
  const m = Math.floor(t / 60);
  const s = t - m * 60;
  return `${m}:${s.toFixed(1).padStart(4, "0")}`;
}

export function parseTime(v: string): number | null {
  const s = v.trim();
  if (!s) return null;
  const m = s.match(/^(?:(\d+):)?(\d+):(\d+(?:\.\d+)?)$/);
  if (m) return (+(m[1] || 0)) * 3600 + +m[2] * 60 + +m[3];
  const n = Number(s.replace(/s$/, ""));
  return isNaN(n) ? null : n;
}

/** Follow a job via SSE; returns a stop() function. */
export function followJob(id: string, onUpdate: (j: Job) => void): () => void {
  const es = new EventSource(`/api/jobs/${id}/events`);
  es.onmessage = (ev) => {
    const job = JSON.parse(ev.data) as Job;
    onUpdate(job);
    if (["done", "failed", "cancelled"].includes(job.status)) es.close();
  };
  es.onerror = () => es.close();
  return () => es.close();
}
