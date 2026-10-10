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
